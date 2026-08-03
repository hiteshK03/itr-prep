"""The Black Money Act s.43 aggregate-value report.

What this answers
-----------------
s.43 of the Black Money (Undisclosed Foreign Income and Assets) and Imposition of Tax Act
2015 penalises a failure to disclose foreign assets at a flat penalty per assessment year.
A proviso inserted by the Finance (No.2) Act 2024 with effect from 1 October 2024
disapplies that penalty where the aggregate value of the foreign assets -- other than
immovable property -- does not exceed a stated figure.

So a single number per year, tested against that figure, decides whether an omitted
Schedule FA costs nothing or the full penalty. Everything needed to compute it was already
in the pipeline; this module is the part that adds it up and says which side of the line it
falls on. Both statutory figures come from the rules registry, cited -- neither is written
into this module, because the threshold has already moved once and can move again.

Why both bases are reported
---------------------------
The proviso says "value" without saying *when*. For bank accounts the Act's valuation
rules (s.3 read with Rule 3) fix a date, but Parliament widened the proviso to all
non-immovable assets in 2024 without extending the valuation machinery to match, so for
shares there is no settled valuation date. Peak-during-the-year and closing-at-31-December
are both defensible and can land on opposite sides of the line. Picking one and hiding the
other would conceal exactly the uncertainty that matters, so both are always shown, and a
year where they straddle the line is called out.

This is arithmetic on the taxpayer's own broker data. It is not advice on which basis a
tribunal would accept.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
from dataclasses import dataclass, field
from decimal import Decimal

from . import rules as rules_registry
from .models import DataError
from .positions import (
    PEAK_BASIS_INR,
    PEAK_BASIS_USD,
    compute_rows,
    value_cash,
)

_RULES = None


def rules():
    """The rules registry, loaded once.

    Both figures this report turns on -- the penalty and the relief threshold -- are
    cited in rules/AY<year>.json rather than written here. The proviso's figure has
    already moved once, replacing an earlier Rs 5,00,000 bank-balance carve-out, so a
    literal in this module would be a claim with nothing behind it. Loaded lazily so
    `--help` still works if the registry is missing, and loudly when it is used.
    """
    global _RULES
    if _RULES is None:
        _RULES = rules_registry.load()
    return _RULES


def threshold_inr() -> int:
    """The proviso's figure: the aggregate below which the s.43 penalty is disapplied."""
    return rules().int_value("black_money_relief_threshold_inr")


def penalty_inr() -> int:
    """The flat s.43 penalty per assessment year for an omitted Schedule FA."""
    return rules().int_value("black_money_s43_penalty_inr")

# Within this fraction of the line, the verdict should not be relied on: FX and
# price sourcing move a total by more than this.
MARGIN_FRACTION = Decimal("0.10")

VERDICT_OVER = "OVER"
VERDICT_UNDER = "UNDER"
VERDICT_NO_DATA = "NO DATA"


@dataclass
class HoldingLine:
    account_id: str
    ticker: str
    lot_id: str
    acquire_date: dt.date
    peak_inr: int
    peak_inr_conservative: int
    closing_inr: int
    peak_date: dt.date | None
    closing_qty: Decimal


@dataclass
class AccountLine:
    account_id: str
    institution: str
    securities_peak: int = 0
    securities_peak_conservative: int = 0
    securities_closing: int = 0
    cash_peak: int = 0
    cash_closing: int = 0

    @property
    def peak(self) -> int:
        return self.securities_peak + self.cash_peak

    @property
    def peak_conservative(self) -> int:
        return self.securities_peak_conservative + self.cash_peak

    @property
    def closing(self) -> int:
        return self.securities_closing + self.cash_closing


@dataclass
class YearResult:
    year: int
    has_data: bool
    reason: str = ""
    holdings: list[HoldingLine] = field(default_factory=list)
    accounts: list[AccountLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cash_supplied: bool = False

    @property
    def peak_total(self) -> int:
        return sum(a.peak for a in self.accounts)

    @property
    def peak_total_conservative(self) -> int:
        return sum(a.peak_conservative for a in self.accounts)

    @property
    def closing_total(self) -> int:
        return sum(a.closing for a in self.accounts)

    def verdict(self, total: int) -> str:
        if not self.has_data:
            return VERDICT_NO_DATA
        return VERDICT_OVER if total > threshold_inr() else VERDICT_UNDER

    @property
    def straddles(self) -> bool:
        """The two bases disagree about which side of the line the year falls on."""
        if not self.has_data:
            return False
        return self.verdict(self.peak_total) != self.verdict(self.closing_total)

    @property
    def marginal(self) -> bool:
        """Either basis sits close enough to the line that the verdict is not safe."""
        if not self.has_data:
            return False
        band = int(threshold_inr() * MARGIN_FRACTION)
        return any(
            abs(total - threshold_inr()) <= band
            for total in (self.peak_total, self.peak_total_conservative,
                          self.closing_total)
        )


@dataclass
class ThresholdReport:
    years: list[YearResult]
    peak_basis: str
    generated: dt.datetime = field(default_factory=dt.datetime.now)

    @property
    def any_straddle(self) -> bool:
        return any(y.straddles for y in self.years)


def compute(
    lots,
    transactions,
    years,
    prices,
    fx,
    accounts,
    cash_balances=None,
    peak_basis: str = PEAK_BASIS_USD,
) -> ThresholdReport:
    """Aggregate every non-immovable foreign asset, per calendar year.

    Both peak bases are computed for every year regardless of `peak_basis`, because the
    threshold question needs the conservative figure even when the Schedule FA rows are
    being produced on the literal one.
    """
    cash_balances = cash_balances or {}
    results: list[YearResult] = []

    earliest = min((t.date for t in transactions), default=None)
    latest_txn = max((t.date for t in transactions), default=None)

    for year in years:
        dec31 = dt.date(year, 12, 31)
        year_cash = value_cash(cash_balances, year, fx)
        relevant_lots = [l for l in lots if l.acquire_date <= dec31]

        if not relevant_lots and not year_cash:
            reason = "no holdings recorded for this year"
            if earliest and earliest.year > year:
                reason = (
                    f"no holdings recorded; the earliest transaction in your data is "
                    f"{earliest}"
                )
            results.append(YearResult(year=year, has_data=False, reason=reason))
            continue

        rows_literal = compute_rows(
            relevant_lots, transactions, year, prices, fx, PEAK_BASIS_USD
        )
        rows_conservative = compute_rows(
            relevant_lots, transactions, year, prices, fx, PEAK_BASIS_INR
        )
        conservative_by_key = {
            (r.account_id, r.lot_id, r.acquire_date, r.ticker): r
            for r in rows_conservative
        }

        if not rows_literal and not year_cash:
            results.append(YearResult(
                year=year, has_data=False,
                reason="all holdings were disposed of before this year began",
            ))
            continue

        holdings: list[HoldingLine] = []
        per_account: dict[str, AccountLine] = {}

        for row in rows_literal:
            key = (row.account_id, row.lot_id, row.acquire_date, row.ticker)
            conservative = conservative_by_key.get(key, row)
            holdings.append(HoldingLine(
                account_id=row.account_id,
                ticker=row.ticker,
                lot_id=row.lot_id,
                acquire_date=row.acquire_date,
                peak_inr=row.peak_value_inr,
                peak_inr_conservative=conservative.peak_value_inr,
                closing_inr=row.closing_value_inr,
                peak_date=row.peak_date,
                closing_qty=row.closing_qty,
            ))
            line = _account_line(per_account, row.account_id, accounts)
            line.securities_peak += row.peak_value_inr
            line.securities_peak_conservative += conservative.peak_value_inr
            line.securities_closing += row.closing_value_inr

        notes: list[str] = []
        for account_id, value in year_cash.items():
            line = _account_line(per_account, account_id, accounts)
            line.cash_peak += value.peak_inr
            line.cash_closing += value.closing_inr
            notes.extend(f"{account_id}: {n}" for n in value.notes)

        accounts_without_cash = sorted(set(per_account) - set(year_cash))
        if accounts_without_cash:
            notes.append(
                "no cash balance supplied for "
                + ", ".join(accounts_without_cash)
                + " -- these totals count securities only and understate the account "
                "by whatever uninvested cash it held"
            )

        result = YearResult(
            year=year,
            has_data=True,
            holdings=sorted(
                holdings, key=lambda h: (h.account_id, h.ticker, h.acquire_date)
            ),
            accounts=[per_account[a] for a in sorted(per_account)],
            notes=notes,
            cash_supplied=bool(year_cash),
        )
        if latest_txn and year > latest_txn.year:
            result.notes.append(
                f"no transactions recorded after {latest_txn}; this year is valued by "
                f"carrying the earlier holdings forward, so it is only right if nothing "
                f"was bought or sold in {year}"
            )
        results.append(result)

    return ThresholdReport(years=results, peak_basis=peak_basis)


def _account_line(per_account, account_id, accounts) -> AccountLine:
    if account_id not in per_account:
        account = accounts.get(account_id)
        per_account[account_id] = AccountLine(
            account_id=account_id,
            institution=account.institution_name if account else account_id,
        )
    return per_account[account_id]


# -- rendering -------------------------------------------------------------------

_WIDTH = 78


def _rule(char: str = "-") -> str:
    return char * _WIDTH


def _inr(amount: int) -> str:
    """Indian digit grouping (12,34,567), so a reader can see lakhs at a glance."""
    digits = str(abs(int(amount)))
    if len(digits) <= 3:
        grouped = digits
    else:
        head, tail = digits[:-3], digits[-3:]
        chunks = []
        while len(head) > 2:
            chunks.insert(0, head[-2:])
            head = head[:-2]
        if head:
            chunks.insert(0, head)
        grouped = ",".join(chunks + [tail])
    return ("-" if amount < 0 else "") + grouped


def _lakh(amount: int) -> str:
    return f"{amount / 100000:.2f} lakh"


def render(report: ThresholdReport) -> str:
    lines: list[str] = []
    add = lines.append

    add(_rule("="))
    add(
        f"AGGREGATE FOREIGN ASSET VALUE vs the Rs {_inr(threshold_inr())} "
        f"s.43 threshold".center(_WIDTH)
    )
    add(_rule("="))
    add("")
    add(f"Black Money Act s.43 penalty: Rs {_inr(penalty_inr())} per assessment year for")
    add("an omitted Schedule FA. The proviso inserted w.e.f. 1-10-2024 disapplies it where")
    add("the aggregate value of foreign assets other than immovable property does not")
    add(f"exceed Rs {_inr(threshold_inr())}.")
    add("")
    add("The proviso fixes no valuation date for non-bank assets, so both a peak-during-")
    add("the-year and a closing-at-31-December basis are shown. Neither is settled law.")
    add("")
    # Both figures above come from the registry, so say which one, and when it was last
    # checked. A verdict worth Rs 10,00,000 an assessment year should not rest on a
    # number whose provenance the report declines to state.
    add(f"Both figures are taken from rules/AY{rules().assessment_year}.json, verified")
    add(f"{rules().verified_on}. Sources are in that file; "
        f"docs/ANNUAL-REVIEW.md says what to")
    add("re-check. Neither figure is computed or remembered.")
    add("")

    add(_rule("="))
    add("SUMMARY")
    add(_rule("="))
    add("")
    header = (f"{'Year':<6} {'Peak basis':>18} {'Verdict':>9} "
              f"{'31 Dec basis':>18} {'Verdict':>9}")
    add(header)
    add(_rule())
    for year in report.years:
        if not year.has_data:
            add(f"{year.year:<6} {'-- no data --':>18} {VERDICT_NO_DATA:>9} "
                f"{'--':>18} {VERDICT_NO_DATA:>9}")
            continue
        add(
            f"{year.year:<6} {_inr(year.peak_total):>18} "
            f"{year.verdict(year.peak_total):>9} "
            f"{_inr(year.closing_total):>18} "
            f"{year.verdict(year.closing_total):>9}"
        )
    add(_rule())
    add("")

    flagged = [y for y in report.years if y.straddles]
    if flagged:
        add(_rule("!"))
        add("STRADDLE WARNING -- the two bases disagree for:")
        for year in flagged:
            add(f"  {year.year}: peak {_inr(year.peak_total)} "
                f"({year.verdict(year.peak_total)}) vs "
                f"31 Dec {_inr(year.closing_total)} "
                f"({year.verdict(year.closing_total)})")
        add("")
        add("For these years the answer turns entirely on a valuation date that the")
        add("proviso does not specify. This is the situation where professional advice")
        add(f"is worth the most: the difference is Rs {_inr(penalty_inr())} of penalty")
        add("exposure per assessment year, decided by an unsettled point of law.")
        add(_rule("!"))
        add("")

    marginal = [y for y in report.years if y.marginal and not y.straddles]
    if marginal:
        add("CLOSE TO THE LINE (within 10%), where sourcing differences could flip the")
        add("verdict on their own:")
        for year in marginal:
            add(f"  {year.year}: peak {_inr(year.peak_total)}, "
                f"31 Dec {_inr(year.closing_total)}")
        add("")

    for year in report.years:
        add(_rule("="))
        add(f"CALENDAR YEAR {year.year}")
        add(_rule("="))
        if not year.has_data:
            add("")
            add(f"  NO DATA -- {year.reason}.")
            add("")
            add("  This is not a nil holding. It means nothing in your transactions.csv")
            add("  covers this year. If an account was open and funded in this year, its")
            add("  acquisitions have to be added before the year can be judged.")
            add("")
            continue

        add("")
        for label, total, extra in (
            ("PEAK basis (sum of per-holding peaks)", year.peak_total, ""),
            ("PEAK basis, conservative (max INR product)",
             year.peak_total_conservative, ""),
            ("CLOSING basis (31 December)", year.closing_total, ""),
        ):
            verdict = year.verdict(total)
            gap = total - threshold_inr()
            if verdict == VERDICT_OVER:
                relation = f"EXCESS over threshold : Rs {_inr(gap)} ({_lakh(gap)})"
            else:
                relation = f"HEADROOM below limit  : Rs {_inr(-gap)} ({_lakh(-gap)})"
            add(f"  {label}")
            add(f"    Aggregate value       : Rs {_inr(total)} ({_lakh(total)}){extra}")
            add(f"    Verdict               : {verdict} Rs {_inr(threshold_inr())}")
            add(f"    {relation}")
            add("")

        add("  Per account:")
        add(f"    {'Account':<16} {'Securities pk':>15} {'Cash pk':>11} "
            f"{'Peak':>13} {'31 Dec':>13}")
        for account in year.accounts:
            add(f"    {account.account_id[:16]:<16} "
                f"{_inr(account.securities_peak):>15} "
                f"{_inr(account.cash_peak):>11} "
                f"{_inr(account.peak):>13} "
                f"{_inr(account.closing):>13}")
        add("")

        add("  Per holding (one line per lot):")
        add(f"    {'Account':<12} {'Ticker':<7} {'Acquired':<11} {'Peak':>13} "
            f"{'Peak date':<11} {'31 Dec':>13}")
        for holding in year.holdings:
            peak_date = holding.peak_date.isoformat() if holding.peak_date else "-"
            add(f"    {holding.account_id[:12]:<12} {holding.ticker[:7]:<7} "
                f"{holding.acquire_date.isoformat():<11} "
                f"{_inr(holding.peak_inr):>13} {peak_date:<11} "
                f"{_inr(holding.closing_inr):>13}")
        add("")

        if year.notes:
            add("  Notes affecting this year:")
            for note in year.notes:
                add(f"    - {note}")
            add("")

    add(_rule("="))
    add("HOW TO READ THIS")
    add(_rule("="))
    add("")
    add("- 'Sum of per-holding peaks' adds each holding's own best day. Holdings do not")
    add("  all peak on the same day, so this is at or above any single-day total. It is")
    add("  the conservative direction for a threshold test.")
    add("- Cash is included only for accounts listed in cash_balances.csv. Any account")
    add("  missing from that file is counted on its securities alone and is understated.")
    add("- Values are rupees, converted at the SBI TT buying rate, per the Schedule FA")
    add("  rule. Every figure traces to the per-lot CSV written alongside this report.")
    add("- Every figure is reconstructed from the taxpayer's own broker statements only.")
    add("")
    add(f"Peak basis used for the Schedule FA rows themselves: {report.peak_basis}")
    add(f"Generated {report.generated.strftime('%Y-%m-%d %H:%M:%S')} by itr-prep.")
    add("")
    add("Arithmetic, not advice. Where a year straddles the line, or is close to it,")
    add("have a professional confirm the valuation basis before relying on the verdict.")
    return "\n".join(lines)


def write_csv(report: ThresholdReport, path: str) -> None:
    """Per-lot audit trail behind every total in the rendered report."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "year", "level", "account_id", "ticker", "lot_id", "acquire_date",
            "peak_inr", "peak_inr_conservative", "peak_date", "closing_inr",
            "verdict_peak", "verdict_closing", "threshold_inr", "note",
        ])
        for year in report.years:
            if not year.has_data:
                writer.writerow([
                    year.year, "YEAR", "", "", "", "", "", "", "", "",
                    VERDICT_NO_DATA, VERDICT_NO_DATA, threshold_inr(), year.reason,
                ])
                continue
            for holding in year.holdings:
                writer.writerow([
                    year.year, "LOT", holding.account_id, holding.ticker,
                    holding.lot_id, holding.acquire_date.isoformat(),
                    holding.peak_inr, holding.peak_inr_conservative,
                    holding.peak_date.isoformat() if holding.peak_date else "",
                    holding.closing_inr, "", "", "", "",
                ])
            for account in year.accounts:
                writer.writerow([
                    year.year, "ACCOUNT", account.account_id, "", "", "",
                    account.peak, account.peak_conservative, "", account.closing,
                    "", "", "",
                    f"securities peak {account.securities_peak}, "
                    f"cash peak {account.cash_peak}, "
                    f"securities closing {account.securities_closing}, "
                    f"cash closing {account.cash_closing}",
                ])
            writer.writerow([
                year.year, "YEAR", "", "", "", "",
                year.peak_total, year.peak_total_conservative, "",
                year.closing_total,
                year.verdict(year.peak_total),
                year.verdict(year.closing_total),
                threshold_inr(),
                "; ".join(year.notes),
            ])


def parse_years(spec: str) -> list[int]:
    """Accept '2022-2025' or '2022,2023,2025'."""
    spec = (spec or "").strip()
    if not spec:
        raise DataError("--years is empty")
    years: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, _, end = part.partition("-")
            try:
                first, last = int(start), int(end)
            except ValueError as exc:
                raise DataError(f"--years: cannot read range {part!r}") from exc
            if last < first:
                raise DataError(f"--years: range {part!r} runs backwards")
            years.extend(range(first, last + 1))
        else:
            try:
                years.append(int(part))
            except ValueError as exc:
                raise DataError(f"--years: {part!r} is not a year") from exc
    for year in years:
        if not 2000 <= year <= 2100:
            raise DataError(f"--years: {year} is not a plausible calendar year")
    return sorted(set(years))
