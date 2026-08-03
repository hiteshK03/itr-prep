"""Turning transactions into per-lot daily position timelines and Schedule FA amounts.

This is where the peak-value work happens, and where the interpretive choices live. The
README's "Peak value" section explains each choice in prose; the code comments here say
which ITD sentence drives it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from . import rules as rules_registry
from .models import (
    DISPOSAL_TAX_WITHHOLDING,
    TXN_BUY,
    TXN_DIVIDEND,
    TXN_SELL,
    DataError,
    Lot,
    Transaction,
)

# Peak basis options.
#   "usd" -- find the day on which the USD value peaked, then convert that USD value at
#            that day's TT buying rate. This is the literal reading of the ITD sentence
#            "the telegraphic transfer buying rate ... as on ... the date of peak balance",
#            which identifies the peak first and only then converts. Default.
#   "inr" -- maximise the INR product (shares x USD close x that day's TT rate) directly.
#            Always >= the "usd" figure, so it is the more conservative disclosure.
PEAK_BASIS_USD = "usd"
PEAK_BASIS_INR = "inr"
PEAK_BASES = (PEAK_BASIS_USD, PEAK_BASIS_INR)


def to_inr_int(amount: Decimal) -> int:
    """Round to whole rupees. The A3/A2 money fields are schema type `integer`."""
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class FaRow:
    """One computed Schedule FA Table A3 row, plus the audit trail behind it."""

    account_id: str
    ticker: str
    lot_id: str
    acquire_date: dt.date
    acq_kind: str

    initial_value_inr: int
    peak_value_inr: int
    closing_value_inr: int
    gross_credited_inr: int
    gross_proceeds_inr: int

    # Audit detail, written to the CSV report rather than into the JSON.
    peak_date: dt.date | None = None
    peak_qty: Decimal = Decimal(0)
    peak_price_usd: Decimal = Decimal(0)
    peak_fx: Decimal = Decimal(0)
    peak_fx_date: dt.date | None = None
    closing_qty: Decimal = Decimal(0)
    closing_price_usd: Decimal = Decimal(0)
    closing_fx: Decimal = Decimal(0)
    initial_qty: Decimal = Decimal(0)
    initial_price_usd: Decimal = Decimal(0)
    initial_fx: Decimal = Decimal(0)
    dividends_usd: Decimal = Decimal(0)
    proceeds_usd: Decimal = Decimal(0)
    notes: list[str] = field(default_factory=list)

    # Provenance: which export row each figure on this line was read from, as
    # `file:line`. A disclosure schedule is only as defensible as its ability to answer
    # "where did this number come from?" years after the export folder has gone.
    source_ref: str = ""
    proceeds_source_refs: list[str] = field(default_factory=list)
    dividend_source_refs: list[str] = field(default_factory=list)


@dataclass
class YearTotals:
    """Aggregates for the schedules that Schedule FA does not itself cover."""

    dividends_usd: Decimal = Decimal(0)
    dividends_inr: int = 0
    dividend_tax_withheld_usd: Decimal = Decimal(0)
    dividend_tax_withheld_inr: int = 0
    stcg_proceeds_inr: int = 0
    stcg_cost_inr: int = 0
    ltcg_proceeds_inr: int = 0
    ltcg_cost_inr: int = 0

    @property
    def stcg_gain_inr(self) -> int:
        return self.stcg_proceeds_inr - self.stcg_cost_inr

    @property
    def ltcg_gain_inr(self) -> int:
        return self.ltcg_proceeds_inr - self.ltcg_cost_inr


def build_lots(transactions: list[Transaction]) -> list[Lot]:
    """Create a lot per acquisition and apply disposals against them.

    Disposals name a specific `lot_id` when the broker export identified one (E*TRADE and
    Fidelity stock-plan sales usually do). Otherwise they are applied FIFO within the same
    account and ticker, which is both the Indian default for identifying shares sold and
    the only defensible choice when the export is silent.

    A `disposal_kind` of TAX_WITHHOLDING is the exception: shares withheld at vest can
    only come out of the lot that vest created, so they are matched on the acquisition
    date. E*TRADE stamps every vest of one award with the same grant number, so lot_id
    alone would let an older vest of the same grant absorb the withholding and leave both
    lots holding the wrong number of shares at the wrong cost.
    """
    lots: list[Lot] = []
    by_key: dict[tuple[str, str], list[Lot]] = {}
    auto_id = 0

    acquisitions = [t for t in transactions if t.txn_type == TXN_BUY]
    disposals = [t for t in transactions if t.txn_type == TXN_SELL]

    for txn in sorted(acquisitions, key=lambda t: (t.date, t.ticker)):
        auto_id += 1
        lot_id = txn.lot_id or f"{txn.ticker}-{txn.date.isoformat()}-{auto_id:03d}"
        lot = Lot(
            uid=f"{auto_id:04d}:{txn.account_id}:{txn.ticker}:{txn.date.isoformat()}",
            lot_id=lot_id,
            account_id=txn.account_id,
            ticker=txn.ticker,
            acquire_date=txn.date,
            original_qty=txn.quantity,
            price_usd=txn.price_usd,
            acq_kind=txn.acq_kind,
            purchase_expense_usd=txn.expense_usd,
            source_ref=txn.source_ref,
        )
        lots.append(lot)
        by_key.setdefault((txn.account_id, txn.ticker), []).append(lot)

    for txn in sorted(disposals, key=lambda t: (t.date, t.ticker)):
        candidates = by_key.get((txn.account_id, txn.ticker), [])
        if not candidates:
            raise DataError(
                f"{txn.source_file} line {txn.source_row}: SELL of {txn.quantity} "
                f"{txn.ticker} in account {txn.account_id} on {txn.date}, but there is "
                f"no matching BUY for that ticker in that account.\n"
                f"If the shares were acquired in an earlier year, add the original "
                f"acquisition as a BUY row -- Schedule FA needs its acquisition date and "
                f"cost regardless of how long ago it happened."
            )
        remaining = txn.quantity
        if txn.disposal_kind == DISPOSAL_TAX_WITHHOLDING:
            same_day = [l for l in candidates if l.acquire_date == txn.date
                        and (not txn.lot_id or l.lot_id == txn.lot_id)]
            if not same_day:
                raise DataError(
                    f"{txn.source_file} line {txn.source_row}: SELL of {txn.quantity} "
                    f"{txn.ticker} is marked disposal_kind="
                    f"{DISPOSAL_TAX_WITHHOLDING} (shares withheld at vest), but no "
                    f"acquisition in account {txn.account_id} has acquisition date "
                    f"{txn.date}"
                    + (f" and lot_id {txn.lot_id!r}" if txn.lot_id else "")
                    + ".\nWithheld shares come out of the vest that created them, so "
                      "that vest must be present as a BUY on the same date. If this is "
                      "an ordinary later sale, clear disposal_kind."
                )
            ordered = same_day
        elif txn.lot_id:
            matches = [l for l in candidates if l.lot_id == txn.lot_id]
            if not matches:
                raise DataError(
                    f"{txn.source_file} line {txn.source_row}: SELL names lot_id "
                    f"{txn.lot_id!r} but no acquisition has that lot_id."
                )
            ordered = matches
        else:
            ordered = sorted(
                [l for l in candidates if l.acquire_date <= txn.date],
                key=lambda l: l.acquire_date,
            )
        for lot in ordered:
            if remaining <= 0:
                break
            available = lot.qty_on(txn.date)
            if available <= 0:
                continue
            take = min(available, remaining)
            lot.disposals.append((txn.date, take))
            remaining -= take
        if remaining > 0:
            raise DataError(
                f"{txn.source_file} line {txn.source_row}: SELL of {txn.quantity} "
                f"{txn.ticker} exceeds the shares held on {txn.date} by {remaining}.\n"
                f"Either an acquisition is missing from transactions.csv, or the "
                f"quantity is wrong. Schedule FA cannot be computed from an "
                f"over-drawn position."
            )
    return lots


def _days_in_window(start: dt.date, end: dt.date):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def compute_rows(
    lots: list[Lot],
    transactions: list[Transaction],
    year: int,
    prices,
    fx,
    peak_basis: str = PEAK_BASIS_USD,
) -> list[FaRow]:
    """One FaRow per lot that was held at any point during the calendar year.

    "Held at any time during the relevant calendar year" is the ITD's own reporting test,
    so a lot bought and fully sold inside the year still gets a row (with a zero closing
    balance), and a lot disposed of before the year began gets none.
    """
    if peak_basis not in PEAK_BASES:
        raise ValueError(f"peak_basis must be one of {PEAK_BASES}")

    jan1 = dt.date(year, 1, 1)
    dec31 = dt.date(year, 12, 31)
    dividends = _dividends_by_ticker_date(transactions, year)
    proceeds = _proceeds_by_lot(lots, transactions, year, fx)
    grouped = group_by_position(lots)

    rows: list[FaRow] = []
    for lot in lots:
        if lot.acquire_date > dec31:
            continue  # acquired after the reporting year
        # Held at any time during the year? Check the day before the window too: a lot
        # that still had shares at the close of 31 Dec of the prior year was held on 1 Jan.
        held_days = [
            d for d in _days_in_window(max(lot.acquire_date, jan1), dec31)
            if lot.qty_on(d) > 0
        ]
        # Acquired and fully disposed of on one day -- a vest sold entirely to cover tax,
        # or a cashless exercise -- leaves no day with a positive end-of-day balance. It
        # was still "held at any time during the relevant calendar year", which is the
        # ITD's own reporting test, so it gets a row instead of vanishing.
        same_day_exit = not held_days and jan1 <= lot.acquire_date <= dec31
        if same_day_exit:
            held_days = [lot.acquire_date]
        # A lot sold on 5 Jan was held on 1-5 Jan, which the loop above catches. A lot
        # whose entire quantity was disposed of before 1 Jan yields no held days.
        if not held_days and not (
            lot.acquire_date <= dec31 and lot.qty_on(jan1) > 0
        ):
            continue

        series = prices.series(lot.ticker, year)
        notes: list[str] = []
        if same_day_exit:
            notes.append(
                "acquired and fully disposed of on the same day; peak taken at the "
                "acquisition quantity, closing balance nil"
            )

        # -- initial value: cost at acquisition, at the TT rate on the investment date --
        init_fx, init_fx_date = fx.rate_on(lot.acquire_date)
        if init_fx_date != lot.acquire_date:
            notes.append(f"initial FX carried from {init_fx_date}")
        initial_inr = lot.cost_usd * init_fx

        # -- peak value across the days held inside the year --
        peak_date = None
        peak_qty = Decimal(0)
        peak_price = Decimal(0)
        peak_fx = Decimal(0)
        peak_fx_date = None
        best_usd = Decimal(0)
        best_inr = Decimal(0)
        for day in held_days:
            qty = lot.original_qty if same_day_exit else lot.qty_on(day)
            price, _price_date = series.close_on(day)
            value_usd = qty * price
            day_fx, day_fx_date = fx.rate_on(day)
            value_inr = value_usd * day_fx
            if peak_basis == PEAK_BASIS_USD:
                # The USD value ties across every day of a weekend or holiday run,
                # because the position is carried at its last traded price. Breaking such
                # ties towards the higher INR keeps the peak from ever coming out below
                # the 31 December closing value, which would otherwise happen for a lot
                # acquired just before a year-end weekend when the rupee weakened over it.
                better = value_usd > best_usd or (
                    value_usd == best_usd and value_inr > best_inr
                )
            else:
                better = value_inr > best_inr
            if peak_date is None or better:
                peak_date, peak_qty, peak_price = day, qty, price
                peak_fx, peak_fx_date = day_fx, day_fx_date
                best_usd, best_inr = value_usd, value_inr
        peak_inr = best_usd * peak_fx if peak_basis == PEAK_BASIS_USD else best_inr
        if peak_fx_date and peak_date and peak_fx_date != peak_date:
            notes.append(f"peak FX carried from {peak_fx_date}")

        # -- closing value: holding at 31 Dec at the 31 Dec TT rate --
        closing_qty = lot.qty_on(dec31)
        closing_fx, closing_fx_date = fx.rate_on(dec31)
        if closing_qty > 0:
            closing_price, closing_price_date = series.close_on(dec31)
            closing_inr = closing_qty * closing_price * closing_fx
            if closing_price_date != dec31:
                notes.append(f"closing price from {closing_price_date}")
        else:
            closing_price = Decimal(0)
            closing_inr = Decimal(0)
            notes.append("fully exited during the year; closing balance nil")
        if closing_fx_date != dec31:
            notes.append(f"closing FX carried from {closing_fx_date}")

        # -- income and proceeds attributable to this lot --
        siblings = grouped.get((lot.account_id, lot.ticker), [lot])
        div_usd, div_inr, div_refs = _lot_dividends(lot, dividends, fx, siblings)
        proceeds_usd, proceeds_inr, proceeds_refs = proceeds.get(
            lot.uid, (Decimal(0), Decimal(0), [])
        )

        rows.append(
            FaRow(
                account_id=lot.account_id,
                ticker=lot.ticker,
                lot_id=lot.lot_id,
                acquire_date=lot.acquire_date,
                acq_kind=lot.acq_kind,
                initial_value_inr=to_inr_int(initial_inr),
                peak_value_inr=to_inr_int(peak_inr),
                closing_value_inr=to_inr_int(closing_inr),
                gross_credited_inr=to_inr_int(div_inr),
                gross_proceeds_inr=to_inr_int(proceeds_inr),
                peak_date=peak_date,
                peak_qty=peak_qty,
                peak_price_usd=peak_price,
                peak_fx=peak_fx,
                peak_fx_date=peak_fx_date,
                closing_qty=closing_qty,
                closing_price_usd=closing_price,
                closing_fx=closing_fx,
                initial_qty=lot.original_qty,
                initial_price_usd=lot.price_usd,
                initial_fx=init_fx,
                dividends_usd=div_usd,
                proceeds_usd=proceeds_usd,
                notes=notes,
                source_ref=lot.source_ref,
                proceeds_source_refs=proceeds_refs,
                dividend_source_refs=div_refs,
            )
        )
    return rows


@dataclass
class CashValue:
    """A cash balance converted to rupees, with the conversion shown."""

    account_id: str
    peak_usd: Decimal
    closing_usd: Decimal
    peak_inr: int
    closing_inr: int
    peak_date: dt.date | None
    peak_fx: Decimal
    closing_fx: Decimal
    notes: list[str] = field(default_factory=list)
    source_ref: str = ""


def value_cash(cash_balances, year: int, fx) -> dict[str, CashValue]:
    """Convert per-account cash balances to rupees on the Schedule FA rules.

    The closing balance is converted at the 31 December rate. The peak is converted at the
    rate of the day the user gave as `peak_date`; with no date, the 31 December rate is
    used and the substitution is recorded in the audit trail, since the peak's true
    conversion date is unknowable from a balance alone.
    """
    dec31 = dt.date(year, 12, 31)
    closing_fx, closing_fx_date = fx.rate_on(dec31)
    out: dict[str, CashValue] = {}
    for (account_id, cash_year), balance in cash_balances.items():
        if cash_year != year:
            continue
        notes: list[str] = []
        if balance.peak_date:
            peak_fx, peak_fx_date = fx.rate_on(balance.peak_date)
            if peak_fx_date != balance.peak_date:
                notes.append(f"cash peak FX carried from {peak_fx_date}")
        else:
            peak_fx = closing_fx
            notes.append(
                "no cash peak_date given; peak converted at the 31 Dec TT rate"
            )
        if closing_fx_date != dec31:
            notes.append(f"cash closing FX carried from {closing_fx_date}")
        if balance.notes:
            notes.append(balance.notes)
        out[account_id] = CashValue(
            account_id=account_id,
            peak_usd=balance.peak_usd,
            closing_usd=balance.closing_usd,
            peak_inr=to_inr_int(balance.peak_usd * peak_fx),
            closing_inr=to_inr_int(balance.closing_usd * closing_fx),
            peak_date=balance.peak_date,
            peak_fx=peak_fx,
            closing_fx=closing_fx,
            notes=notes,
            source_ref=balance.source_ref,
        )
    return out


def _dividends_by_ticker_date(transactions, year):
    """Dividends per (account, ticker, date), with the rows each total came from."""
    out: dict[tuple[str, str, dt.date], tuple[Decimal, list[str]]] = {}
    for txn in transactions:
        if txn.txn_type != TXN_DIVIDEND or txn.date.year != year:
            continue
        key = (txn.account_id, txn.ticker, txn.date)
        amount, refs = out.get(key, (Decimal(0), []))
        out[key] = (amount + txn.gross_usd, _add_ref(refs, txn.source_ref))
    return out


def _add_ref(refs: list[str], ref: str) -> list[str]:
    """Append a source reference, keeping the list unique and in encounter order."""
    if ref and ref not in refs:
        refs.append(ref)
    return refs


def group_by_position(lots: list[Lot]) -> dict[tuple[str, str], list[Lot]]:
    """Group lots by (account, ticker) -- the unit a dividend is actually paid on."""
    grouped: dict[tuple[str, str], list[Lot]] = {}
    for lot in lots:
        grouped.setdefault((lot.account_id, lot.ticker), []).append(lot)
    return grouped


def _lot_dividends(lot: Lot, dividends, fx, siblings: list[Lot]):
    """Split each dividend across the lots that held shares on the dividend date.

    Dividends are paid per share, not per lot, so with a lot-per-row model they have to be
    apportioned. Pro-rating by shares held on the payment date reproduces what the lot
    actually earned, and the apportioned amounts sum back to the dividend total.
    """
    total_usd = Decimal(0)
    total_inr = Decimal(0)
    refs: list[str] = []
    for (account_id, ticker, day), (amount, day_refs) in dividends.items():
        if account_id != lot.account_id or ticker != lot.ticker:
            continue
        lot_qty = lot.qty_on(day)
        if lot_qty <= 0:
            continue
        position_qty = sum((s.qty_on(day) for s in siblings), Decimal(0))
        if position_qty <= 0:
            continue
        share = amount * (lot_qty / position_qty)
        rate, _ = fx.rate_on(day)
        total_usd += share
        total_inr += share * rate
        for ref in day_refs:
            _add_ref(refs, ref)
    return total_usd, total_inr, refs


def _proceeds_by_lot(lots, transactions, year, fx):
    """Sale proceeds during the reporting year, attributed to the lots actually sold.

    `lot.disposals` records only (date, qty) -- it has no link back to which SELL
    transaction caused it. When two or more SELL transactions share the same
    (account, ticker, date), every one of them would otherwise re-match the SAME full
    day's disposals, so grouping (and summing gross_usd) by that key BEFORE matching is
    required -- matching per-transaction double- (or N-) counts the day's disposals once
    per transaction sharing the key. This is common with fractional-share DCA exports
    that place several same-day sells in separate rows.
    """
    out: dict[str, tuple[Decimal, Decimal, list[str]]] = {}
    grouped = group_by_position(lots)

    sell_groups: dict[tuple[str, str, dt.date], tuple[Decimal, list[str]]] = {}
    for txn in transactions:
        if txn.txn_type != TXN_SELL or txn.date.year != year:
            continue
        key = (txn.account_id, txn.ticker, txn.date)
        gross, refs = sell_groups.get(key, (Decimal(0), []))
        sell_groups[key] = (gross + txn.gross_usd, _add_ref(refs, txn.source_ref))

    for (account_id, ticker, date), (gross_usd, sell_refs) in sell_groups.items():
        # Re-derive the split the same way build_lots applied it: for this sale date,
        # each lot's disposal entry on that date is its share of the day's total sale.
        matched = [
            (lot, qty)
            for lot in grouped.get((account_id, ticker), [])
            for (sold_date, qty) in lot.disposals
            if sold_date == date
        ]
        total_matched = sum((q for _, q in matched), Decimal(0))
        if total_matched <= 0:
            continue
        rate, _ = fx.rate_on(date)
        for lot, qty in matched:
            portion = gross_usd * (qty / total_matched)
            prev_usd, prev_inr, refs = out.get(lot.uid, (Decimal(0), Decimal(0), []))
            for ref in sell_refs:
                _add_ref(refs, ref)
            out[lot.uid] = (prev_usd + portion, prev_inr + portion * rate, refs)
    return out


def _rule115_specified_date(d: dt.date) -> dt.date:
    """Rule 115(2) "specified date": the last day of the month immediately preceding.

    Applies to Schedule CG (capital gains, sub-clause (f)) and Schedule OS dividend
    income (sub-clause (e)) -- NOT to Schedule FA, which the ITD's own step-by-step
    guide separately and explicitly pins to per-date TT-buy rates (see
    docs/VERIFIED_FINDINGS.md #10). Confirmed against a real broker's own tax report:
    their displayed per-leg exchange rate for both the purchase and the sale side of a
    trade matched this specified date exactly, not the actual transaction date's rate --
    e.g. a 2024-08-02 purchase showed the 2024-07-31 rate, not the 2024-08-02 rate.
    """
    first_of_month = d.replace(day=1)
    return first_of_month - dt.timedelta(days=1)


def compute_year_totals(lots, transactions, year, fx, rules=None) -> YearTotals:
    """Aggregate figures for Schedule CG (two blocks) and Schedule OS/FSI/TR.

    Capital gains are on the FINANCIAL year (1 Apr - 31 Mar), unlike Schedule FA. The
    `year` argument here is the financial year's starting calendar year, so year=2025
    means FY 2025-26 = 1 Apr 2025 to 31 Mar 2026.

    FX conversion here follows Rule 115(2) of the Income-tax Rules, 1962, NOT the
    per-date convention Schedule FA uses -- see `_rule115_specified_date`.

    `rules` is a loaded rules registry; the newest on disk is used when none is given.
    The long-term holding period comes from it rather than from a literal here.
    """
    if rules is None:
        rules = rules_registry.load()
    long_term_days = rules.int_field("foreign_share_long_term_holding", "days")
    totals = YearTotals()
    fy_start = dt.date(year, 4, 1)
    fy_end = dt.date(year + 1, 3, 31)

    for txn in transactions:
        if txn.txn_type == TXN_DIVIDEND and fy_start <= txn.date <= fy_end:
            rate, _ = fx.rate_on(_rule115_specified_date(txn.date))
            totals.dividends_usd += txn.gross_usd
            totals.dividends_inr += to_inr_int(txn.gross_usd * rate)
            totals.dividend_tax_withheld_usd += txn.tax_withheld_usd
            totals.dividend_tax_withheld_inr += to_inr_int(
                txn.tax_withheld_usd * rate
            )

    by_key: dict[tuple[str, str], list[Lot]] = {}
    for lot in lots:
        by_key.setdefault((lot.account_id, lot.ticker), []).append(lot)

    # `lot.disposals` records only (date, qty), with no link back to which SELL
    # transaction caused it. Group and sum gross_usd by (account, ticker, date) BEFORE
    # matching against disposals -- matching per-transaction instead re-matches the
    # SAME day's full disposal set once per transaction sharing that key, inflating
    # cost (and skewing the proceeds split) whenever two or more sells share a day. This
    # is common with fractional-share DCA exports.
    sell_groups: dict[tuple[str, str, dt.date], Decimal] = {}
    sell_expense_groups: dict[tuple[str, str, dt.date], Decimal] = {}
    for txn in transactions:
        if txn.txn_type != TXN_SELL or not (fy_start <= txn.date <= fy_end):
            continue
        key = (txn.account_id, txn.ticker, txn.date)
        sell_groups[key] = sell_groups.get(key, Decimal(0)) + txn.gross_usd
        sell_expense_groups[key] = (
            sell_expense_groups.get(key, Decimal(0)) + txn.expense_usd
        )

    for (account_id, ticker, date), gross_usd in sell_groups.items():
        sale_rate, _ = fx.rate_on(_rule115_specified_date(date))
        sale_expense_usd = sell_expense_groups.get((account_id, ticker, date), Decimal(0))
        candidates = by_key.get((account_id, ticker), [])
        matched = [
            (lot, qty)
            for lot in candidates
            for (sold_date, qty) in lot.disposals
            if sold_date == date
        ]
        total_matched = sum((q for _, q in matched), Decimal(0))
        if total_matched <= 0:
            continue
        for lot, qty in matched:
            share = qty / total_matched
            portion_usd = gross_usd * share
            # Sale-side expense (brokerage on the sell) reduces net consideration;
            # purchase-side expense (brokerage on the original buy) adds to cost of
            # acquisition. Both deductible under Section 48.
            proceeds_inr = to_inr_int((portion_usd - sale_expense_usd * share) * sale_rate)
            cost_rate, _ = fx.rate_on(_rule115_specified_date(lot.acquire_date))
            lot_expense_share = (
                lot.purchase_expense_usd * (qty / lot.original_qty)
                if lot.original_qty else Decimal(0)
            )
            cost_inr = to_inr_int((qty * lot.price_usd + lot_expense_share) * cost_rate)
            # Unlisted/foreign shares: long term needs a holding period over 24 months.
            # The figure is cited in the rules registry, not written here -- holding
            # periods were rewritten by the Finance (No. 2) Act 2024 and can move again.
            held_days = (date - lot.acquire_date).days
            if held_days > long_term_days:
                totals.ltcg_proceeds_inr += proceeds_inr
                totals.ltcg_cost_inr += cost_inr
            else:
                totals.stcg_proceeds_inr += proceeds_inr
                totals.stcg_cost_inr += cost_inr
    return totals
