"""Indian mutual fund capital gains, for ITR-2 Schedule 112A and Schedule CG.

This is the pipeline the Schedule FA work deliberately refused: an Indian mutual fund
unit is an Indian asset wherever it is held, so it belongs nowhere in Schedule FA and
everything here computes its capital gains under the provisions the registry cites.

Three things shape the design, and none of them is optional:

* **Every figure is read from the assessment year's registry.** Holding periods, the
  grandfathering dates and formula, the lot-matching method -- all of them come out of
  ``rules/AY2027-28.json`` (or a later registry) through ``itrprep/rules.py``. Nothing
  here is computed from memory, in the same sense the rest of the codebase means it.

* **The engine classifies nothing.** Which side of the equity-oriented line a fund
  sits on is a question the registry answers in law but that no data in this pipeline
  can answer in fact -- a fund's asset mix is not in any statement we read. The caller
  therefore declares each scheme's classification, and the engine refuses to guess.
  The registry's specified-mutual-fund debt-threshold entry is ``contested``
  (KNOWN-ISSUES.md issue 2) and is not read at all; a scheme declared specified-mutual-
  fund is refused rather than taxed on an unsettled test.

* **Money in whole rupees, per-unit figures to four decimals.** The department's
  Schedule 112A schema makes the five per-unit fields ``multipleOf: 0.0001`` and the
  aggregate rupee fields integers; the utility's own CSV template rounds the rupee
  columns the same way. ``itrprep/validate.py`` carries the exact-decimal multipleOf
  check (KNOWN-ISSUES.md issue 1), so four-decimal per-unit values validate cleanly.

What the engine does NOT do: tax. It produces the Schedule 112A rows and the
long/short-term gain aggregates; charging provisions, set-off and the section 198
exemption are the utility's computation, and the upload JSON keeps coming out of the
department's own software, exactly as with Schedule FA.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .rules import Rules

# Registry keys this module reads. Listed here, not scattered, so the registry test's
# drift check sees one place that owns them.
KEY_GRANDFATHERING_CUTOFF = "mf_grandfathering_cutoff_date"
KEY_GRANDFATHERING_VALUATION = "mf_grandfathering_valuation_date"
KEY_HOLDING_PERIODS = "mf_holding_period_months"
KEY_LOT_MATCHING = "mf_lot_matching_method"
KEY_BONUS_UNIT_COST = "mf_bonus_unit_cost"
KEY_INDEXATION = "mf_unit_indexation_available"

# Every registry entry this module reads, for the pre-flight "does this assessment
# year's registry carry mutual fund law at all" gate in the CLI. A registry that lacks
# these must refuse the computation rather than have the engine raise mid-flight.
REQUIRED_KEYS = (
    KEY_GRANDFATHERING_CUTOFF,
    KEY_GRANDFATHERING_VALUATION,
    KEY_HOLDING_PERIODS,
    KEY_LOT_MATCHING,
    KEY_BONUS_UNIT_COST,
    KEY_INDEXATION,
)

# The section 196/197/198 rates and the section 198 exemption live in the registry too,
# but nothing here reads them: this engine computes gains, not tax. Charging, set-off
# and the exemption are the utility's computation. If that ever changes, those keys
# belong in this list -- and only then.

# Unit-quantity and per-unit-value precision the 112A schema permits (multipleOf 0.0001).
FOUR_DP = Decimal("0.0001")
# Rupee aggregates are integers in the schema.
RUPEE = Decimal("1")

# What a scheme declaration may say about the section 198(8) classification.
EQUITY_ORIENTED = "equity_oriented"
OTHER_FUND = "other"


class MfError(Exception):
    """A refusal with the reason attached. Raised, never returned, so a caller cannot
    silently build on a ledger it was told not to."""


def _dec(value) -> Decimal:
    """Everything enters the engine as an exact decimal. A float here would be a
    rounding decision nobody made."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q4(value: Decimal) -> Decimal:
    """Round to the schema's four decimal places, half-up -- the only rounding the
    per-unit fields may see, and it is visible in the audit output."""
    return value.quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def _rupees(value: Decimal) -> int:
    """Whole rupees, half-up, matching the utility's CSV template convention."""
    return int(value.quantize(RUPEE, rounding=ROUND_HALF_UP))


@dataclass
class SchemeDecl:
    """The caller's declaration of one scheme's classification.

    The engine will not infer any of these: ``classification`` is the caller's reading
    of the fund's asset mix against section 198(8) (for AY 2027-28), and
    ``fmv_2018_01_31`` is the caller's figure for the valuation-date fair market value
    per unit -- the highest quoted price that day for a listed scheme, the NAV for an
    unlisted one, from the source the registry entry names. Both are auditable
    declarations, and both must exist before a pre-cutoff unit can be sold.
    """

    isin: str
    name: str
    classification: str  # EQUITY_ORIENTED or OTHER_FUND
    listed: bool = True
    fmv_2018_01_31: object = None

    def __post_init__(self):
        if self.classification not in (EQUITY_ORIENTED, OTHER_FUND):
            raise MfError(
                f"scheme {self.isin}: classification must be {EQUITY_ORIENTED!r} or "
                f"{OTHER_FUND!r}, not {self.classification!r}. The engine does not "
                "guess which side of the section 198(8) line a fund sits on -- the "
                "fund's asset mix is not in any statement this pipeline reads."
            )
        if self.fmv_2018_01_31 is not None:
            self.fmv_2018_01_31 = _dec(self.fmv_2018_01_31)


@dataclass
class Purchase:
    isin: str
    date: dt.date
    units: object
    price_per_unit: object
    source_ref: str = ""

    def __post_init__(self):
        self.units = _dec(self.units)
        self.price_per_unit = _dec(self.price_per_unit)
        if self.units <= 0:
            raise MfError(f"{self.isin}: purchase units must be positive ({self.source_ref})")
        if self.price_per_unit < 0:
            raise MfError(f"{self.isin}: purchase price is negative ({self.source_ref})")

    @property
    def cost(self) -> Decimal:
        return self.units * self.price_per_unit


@dataclass
class Bonus:
    """Units allotted without payment on the basis of a holding. Their cost is the
    registry's ``mf_bonus_unit_cost`` -- declared there, not assumed here."""

    isin: str
    date: dt.date
    units: object
    source_ref: str = ""

    def __post_init__(self):
        self.units = _dec(self.units)
        if self.units <= 0:
            raise MfError(f"{self.isin}: bonus units must be positive ({self.source_ref})")


@dataclass
class Sale:
    isin: str
    date: dt.date
    units: object
    price_per_unit: object
    transfer_expense: object = Decimal(0)
    source_ref: str = ""

    def __post_init__(self):
        self.units = _dec(self.units)
        self.price_per_unit = _dec(self.price_per_unit)
        self.transfer_expense = _dec(self.transfer_expense)
        if self.units <= 0:
            raise MfError(f"{self.isin}: sale units must be positive ({self.source_ref})")
        if self.price_per_unit <= 0:
            raise MfError(f"{self.isin}: sale price must be positive ({self.source_ref})")
        if self.transfer_expense < 0:
            raise MfError(f"{self.isin}: transfer expense is negative ({self.source_ref})")


@dataclass
class Ledger:
    """One scheme's purchases, bonuses and sales, kept in date order."""

    scheme: SchemeDecl
    purchases: list = field(default_factory=list)
    bonuses: list = field(default_factory=list)
    sales: list = field(default_factory=list)

    def add(self, item) -> None:
        if item.isin != self.scheme.isin:
            raise MfError(
                f"ledger for {self.scheme.isin} given an event for {item.isin}"
            )
        if isinstance(item, Purchase):
            self.purchases.append(item)
        elif isinstance(item, Bonus):
            self.bonuses.append(item)
        elif isinstance(item, Sale):
            self.sales.append(item)
        else:
            raise MfError(f"unknown ledger item {item!r}")
        for bucket in (self.purchases, self.bonuses, self.sales):
            bucket.sort(key=lambda e: e.date)


@dataclass
class MatchedLot:
    """One FIFO match: `units` taken from the lot acquired on `acquired`, at that
    lot's cost, inside the sale dated `sold`."""

    acquired: dt.date
    sold: dt.date
    units: Decimal
    cost_per_unit: Decimal
    sale_price_per_unit: Decimal
    transfer_expense: Decimal

    @property
    def cost(self) -> Decimal:
        return self.units * self.cost_per_unit

    @property
    def proceeds(self) -> Decimal:
        return self.units * self.sale_price_per_unit


@dataclass
class GainRow:
    """One matched lot's gain, with the holding-period and grandfathering decisions
    the registry supplies."""

    isin: str
    scheme_name: str
    lot: MatchedLot
    long_term: bool
    grandfathered: bool
    cost_of_acquisition: Decimal  # after the section 90(7) formula, if it applies
    fmv_value: Decimal | None  # valuation-date FMV of the lot, when grandfathered
    gain: Decimal

    @property
    def holding_days(self) -> int:
        return (self.lot.sold - self.lot.acquired).days


def _add_months(day: dt.date, months: int) -> dt.date:
    """Calendar month addition with end-of-month clamping (31 Jan + 1 = 28/29 Feb)."""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day to the target month's length, trying the same day-of-month first.
    for candidate in range(day.day, 0, -1):
        try:
            return dt.date(year, month, candidate)
        except ValueError:
            continue
    return dt.date(year, month, 1)


def _months_between(a: dt.date, b: dt.date) -> tuple[int, int]:
    """Whole months from `a` to `b` and leftover days. Holding periods are counted in
    months by statute, so a months-and-days comparison is the honest test, not a day
    count against a fictional 30-day month. Example: 2026-01-10 to 2027-02-01 is 12
    months and 22 days."""
    months = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        months -= 1
    days = (b - _add_months(a, months)).days
    if days < 0:
        # Defensive: the borrow above should already have handled it.
        months -= 1
        days = (b - _add_months(a, months)).days
    return months, days


class Engine:
    """The registry-backed capital gains engine for one assessment year."""

    def __init__(self, registry: Rules):
        self.registry = registry
        cutoff_raw = registry.value(KEY_GRANDFATHERING_CUTOFF)
        valuation_raw = registry.value(KEY_GRANDFATHERING_VALUATION)
        if not isinstance(cutoff_raw, str) or not isinstance(valuation_raw, str):
            raise MfError(
                "the grandfathering date entries in the registry are not ISO date "
                "strings -- the engine cannot compute on what it cannot read"
            )
        self.cutoff = dt.date.fromisoformat(cutoff_raw)
        self.valuation_date = dt.date.fromisoformat(valuation_raw)
        periods = registry.value(KEY_HOLDING_PERIODS)
        if not isinstance(periods, dict):
            raise MfError("mf_holding_period_months is not a dict of period classes")
        self.long_term_months = int(periods["equity_oriented"])
        self.default_long_term_months = int(periods["default"])
        lot_method = registry.value(KEY_LOT_MATCHING)
        if lot_method != "FIFO":
            raise MfError(
                f"the registry's lot-matching method is {lot_method!r}; this engine "
                "only implements the FIFO it was written against"
            )
        self.bonus_cost = _dec(registry.value(KEY_BONUS_UNIT_COST))
        if registry.value(KEY_INDEXATION) is not False:
            raise MfError(
                "the registry says indexation is available for fund units; this engine "
                "computes no indexed cost -- resolve the contradiction before computing"
            )

    # ------------------------------------------------------------------ lots

    def match_sale(self, ledger: Ledger, sale: Sale) -> list[MatchedLot]:
        """FIFO matching of one sale against the ledger's open lots.

        Every event dated up to and including the sale date is replayed in order:
        purchases and bonuses open lots, earlier sales close them. What remains open is
        matched oldest-first against this sale. A sale bigger than the open balance is
        a hard error -- the ledger does not hold those units, and inventing a cost for
        them is the failure this module exists to refuse.
        """
        open_lots: list[list] = []  # [acquired, units_open, cost_per_unit]
        events: list = []
        events.extend(ledger.purchases)
        events.extend(ledger.bonuses)
        events.extend(s for s in ledger.sales if s is not sale)
        events.sort(key=lambda e: (e.date, isinstance(e, Sale)))
        for event in events:
            if event.date > sale.date:
                continue
            if isinstance(event, Purchase):
                open_lots.append([event.date, event.units, event.price_per_unit])
            elif isinstance(event, Bonus):
                open_lots.append([event.date, event.units, self.bonus_cost])
            else:
                self._take(open_lots, event.units, event)

        matches: list[MatchedLot] = []
        remaining = sale.units
        for acquired, units_open, cost_per_unit in open_lots:
            if remaining <= 0:
                break
            take = min(units_open, remaining)
            matches.append(MatchedLot(
                acquired=acquired,
                sold=sale.date,
                units=take,
                cost_per_unit=cost_per_unit,
                sale_price_per_unit=sale.price_per_unit,
                transfer_expense=(sale.transfer_expense * take / sale.units
                                  if sale.transfer_expense else Decimal(0)),
            ))
            remaining -= take
        if remaining > 0:
            raise MfError(
                f"{sale.isin}: the sale of {sale.units} units on {sale.date.isoformat()} "
                f"exceeds the open balance by {remaining} units -- the ledger does not "
                "hold them. Every unit sold must have a purchase or bonus before it."
            )
        return matches

    @staticmethod
    def _take(open_lots: list[list], units: Decimal, event) -> None:
        remaining = units
        while remaining > 0:
            if not open_lots:
                raise MfError(
                    f"{event.isin}: a sale dated {event.date.isoformat()} has no units "
                    "left to match against -- the ledger is overdrawn"
                )
            lot = open_lots[0]
            take = min(lot[1], remaining)
            lot[1] -= take
            remaining -= take
            if lot[1] == 0:
                open_lots.pop(0)

    # ------------------------------------------------------------------ gains

    def lot_gain(self, scheme: SchemeDecl, lot: MatchedLot) -> GainRow:
        """One matched lot's gain under the registry's provisions.

        The holding-period boundary follows the statute's own words: section 2(101)
        defines the SHORT-TERM asset as one held "not more than" the threshold months,
        so exactly twelve months (equity-oriented) or twenty-four (default) is still
        short-term, and long-term needs strictly more.

        Grandfathering is section 90(7)'s, which names equity shares, units of
        equity-oriented funds and units of business trusts: it applies here only to an
        EQUITY_ORIENTED declaration. An OTHER_FUND lot keeps its actual cost whatever
        its vintage -- there is no FMV regime for it, and the registry records that
        indexation is unavailable too.
        """
        if scheme.classification == EQUITY_ORIENTED:
            months_needed = self.long_term_months
        else:
            months_needed = self.default_long_term_months
        months, days = _months_between(lot.acquired, lot.sold)
        long_term = months > months_needed or (months == months_needed and days > 0)

        grandfathered = (lot.acquired < self.cutoff
                         and scheme.classification == EQUITY_ORIENTED)
        fmv_value = None
        cost = lot.cost
        if grandfathered:
            if scheme.fmv_2018_01_31 is None:
                raise MfError(
                    f"{scheme.isin}: units acquired {lot.acquired.isoformat()} are before "
                    f"the {self.cutoff.isoformat()} grandfathering cutoff, but the scheme "
                    f"declaration carries no fair market value as on "
                    f"{self.valuation_date.isoformat()}. Declare fmv_2018_01_31 -- the "
                    "engine does not fetch or guess valuation-date prices."
                )
            if not long_term:
                raise MfError(
                    f"{scheme.isin}: a lot acquired {lot.acquired.isoformat()} and sold "
                    f"{lot.sold.isoformat()} cannot be short-term under any holding "
                    "period the registry gives -- check the ledger dates"
                )
            fmv_value = scheme.fmv_2018_01_31 * lot.units
            proceeds = lot.proceeds
            # Section 90(7): cost of acquisition = higher of the actual cost and the
            # lower of (i) the valuation-date FMV and (ii) the full value of
            # consideration. Grandfathering can never manufacture a loss.
            cost = max(lot.cost, min(fmv_value, proceeds))

        gain = lot.proceeds - cost - lot.transfer_expense
        return GainRow(
            isin=scheme.isin,
            scheme_name=scheme.name,
            lot=lot,
            long_term=long_term,
            grandfathered=grandfathered,
            cost_of_acquisition=cost,
            fmv_value=fmv_value,
            gain=gain,
        )

    def scheme_gains(self, ledger: Ledger) -> list[GainRow]:
        rows: list[GainRow] = []
        for sale in ledger.sales:
            for lot in self.match_sale(ledger, sale):
                rows.append(self.lot_gain(ledger.scheme, lot))
        return rows

    # ------------------------------------------------------------------ aggregates

    @staticmethod
    def sums(rows: list[GainRow]) -> tuple[Decimal, Decimal]:
        """(long_term_gain, short_term_gain) across the matched lots of one scheme.

        Plain arithmetic on the engine's own rows. What happens to each half -- 112A
        rows and the section 198 exemption for equity-oriented long-term gains, Schedule
        CG treatment for everything else -- is the emission layer's routing and the
        utility's computation, not this engine's.
        """
        ltcg = sum((r.gain for r in rows if r.long_term), Decimal(0))
        stcg = sum((r.gain for r in rows if not r.long_term), Decimal(0))
        return ltcg, stcg


def fy_window(financial_year: str) -> tuple[dt.date, dt.date]:
    """The filing year's gain-recognition window: transfers during the previous year.

    Schedule FA reports a CALENDAR year; capital gains attach to the FINANCIAL year.
    The registry names its financial year ("2026-27" for AY 2027-28), so the window is
    read from the same source as every other figure: 1 April of the first year through
    31 March of the second. Sales before the window still matter -- they consume lots
    -- but they are not gains of this return.
    """
    try:
        start_year, _ = financial_year.split("-")
        start = dt.date(int(start_year), 4, 1)
        end = dt.date(int(start_year) + 1, 3, 31)
    except (ValueError, AttributeError):
        raise MfError(f"financial_year {financial_year!r} is not 'YYYY-YY'") from None
    return start, end


def schedule_112a_row(scheme: SchemeDecl, rows: list[GainRow],
                      cutoff: dt.date) -> dict:
    """One Schedule 112A detail row per scheme, in the department's schema shape
    (definition Schedule112A115ADType), with the utility's CSV template's rounding:
    rupee aggregates as integers, per-unit figures to four decimals.

    Every row here is long-term and equity-oriented by construction -- that is the
    only kind of gain Schedule 112A carries, and both conditions are enforced rather
    than assumed.
    """
    if scheme.classification != EQUITY_ORIENTED:
        raise MfError(
            f"{scheme.isin}: Schedule 112A carries gains of section 198 assets only; "
            "a scheme declared other-fund has no row there -- its gains belong in "
            "Schedule CG and the utility computes their treatment"
        )
    if not rows:
        raise MfError(f"{scheme.isin}: no gains to emit")
    short_term = [r for r in rows if not r.long_term]
    if short_term:
        raise MfError(
            f"{scheme.isin}: Schedule 112A carries long-term gains only, but "
            f"{len(short_term)} matched lot(s) are short-term"
        )

    units = sum((r.lot.units for r in rows), Decimal(0))
    proceeds = sum((r.lot.proceeds for r in rows), Decimal(0))
    cost = sum((r.cost_of_acquisition for r in rows), Decimal(0))
    expense = sum((r.lot.transfer_expense for r in rows), Decimal(0))
    fmv_total = sum((r.fmv_value for r in rows if r.fmv_value is not None), Decimal(0))
    gained = sum((r.gain for r in rows), Decimal(0))

    # The acquisition flag is per the utility's column 1a: were the units acquired on
    # or before 31 January 2018? A scheme can hold both vintages; each vintage was
    # matched separately above, but the schema's row is per scheme, so the flag says
    # BE when any lot is grandfathered and the FMV column carries the grandfathered
    # lots' valuation-date value. (The department's own template works the same way.)
    any_be = any(r.grandfathered for r in rows)
    all_be = all(r.grandfathered for r in rows)
    if any_be and not all_be:
        # Mixed vintages in one scheme: the schema's single flag cannot say both, so
        # split the row at the caller instead. Refuse here loudly.
        raise MfError(
            f"{scheme.isin}: the scheme has lots on both sides of the "
            f"{cutoff.isoformat()} cutoff. Split it into one declaration per vintage "
            "(the same ISIN, distinguished only by the flag) and emit separately -- "
            "the schema's per-row flag cannot carry both."
        )

    return {
        "ShareOnOrBefore": "BE" if any_be else "AE",
        "ISINCode": scheme.isin,
        "ShareUnitName": scheme.name[:125],
        "NumSharesUnits": float(_q4(units)),
        "SalePricePerShareUnit": float(_q4(proceeds / units)),
        "TotSaleValue": _rupees(proceeds),
        "CostAcqWithoutIndx": _rupees(cost),
        "AcquisitionCost": float(_q4(cost / units)),
        "LTCGBeforelowerB1B2": _rupees(gained),
        "FairMktValuePerShareunit": float(_q4(fmv_total / units)) if fmv_total else 0.0,
        "TotFairMktValueCapAst": _rupees(fmv_total),
        "ExpExclCnctTransfer": float(_q4(expense)),
        "TotalDeductions": _rupees(cost + expense),
        "Balance": _rupees(gained),
    }
