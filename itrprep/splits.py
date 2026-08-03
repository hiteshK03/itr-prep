"""Stock split detection and restatement.

Why this module has to exist
----------------------------
Yahoo's daily closes are *retroactively* split-adjusted: the close it reports for a day
before a 10-for-1 split is the real price of that day divided by ten. A broker statement
is not. So for a holding that spans a split, multiplying the statement's share count by
Yahoo's close understates the position by the split factor -- for AVGO's June 2024 10:1
split, by a factor of ten. That error would flow straight into the Schedule FA rows and
into the s.43 threshold verdict.

The trap is that the correct fix depends on something the data cannot tell us: whether the
quantities in transactions.csv are stated in *current* (post-split) terms or in the terms
that were current on the transaction date. Brokers restate historical lots when you
re-download, so a CSV pulled today is usually post-split, while a statement saved in 2023
is pre-split. Both are legitimate and they differ by exactly the factor we are trying to
correct for.

So the default is to stop, name the split, and say which basis the data *looks* like it is
in, rather than guess. `--split-basis` then records the user's decision:

  current    -- quantities already restated for the split. No adjustment needed: on a
                pre-split day, (post-split qty) x (adjusted close) is already the right
                value, because both sides were divided by the same factor.
  historical -- quantities are as printed at the time. Each transaction is restated onto
                the current basis (quantity x factor, price / factor) before any valuation
                happens, which puts it in the `current` case above.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from .models import DataError, Transaction

SPLIT_BASIS_CURRENT = "current"
SPLIT_BASIS_HISTORICAL = "historical"
SPLIT_BASES = (SPLIT_BASIS_CURRENT, SPLIT_BASIS_HISTORICAL)

# How far the recorded price may sit from the reference price and still count as evidence
# of a basis. Generous on purpose: an ESPP price carries a 15% statutory discount, and a
# vest price is a day's FMV that need not equal the close. The factors we are trying to
# tell apart are 2x, 3x, 10x, so a loose band still separates them cleanly.
_TOLERANCE = Decimal("0.30")


@dataclass
class SplitEvent:
    ticker: str
    date: dt.date
    ratio: Decimal

    @property
    def label(self) -> str:
        ratio = self.ratio.normalize()
        if ratio == ratio.to_integral_value():
            return f"{int(ratio)}-for-1"
        return f"{ratio} -for-1"


@dataclass
class SplitExposure:
    """One transaction sitting on the wrong side of one or more splits."""

    txn: Transaction
    events: list[SplitEvent]
    factor: Decimal
    verdict: str  # "current", "historical" or "unknown"
    evidence: str


@dataclass
class SplitScan:
    events: list[SplitEvent] = field(default_factory=list)
    exposures: list[SplitExposure] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)

    @property
    def affected(self) -> bool:
        return bool(self.exposures)


def scan(transactions: list[Transaction], prices, year: int) -> SplitScan:
    """Find every transaction whose quantity could be on the wrong split basis.

    A split matters for a transaction if it took effect *after* that transaction and on or
    before today -- including splits later than the reporting year, because Yahoo has
    already folded those into the historical closes we are about to read.
    """
    result = SplitScan()
    if not transactions:
        return result

    today = dt.date.today()
    tickers = sorted({t.ticker for t in transactions if t.ticker})
    first_year = min((t.date.year for t in transactions), default=year)
    scan_years = range(min(first_year, year), max(today.year, year) + 1)

    per_ticker: dict[str, list[SplitEvent]] = {}
    for ticker in tickers:
        try:
            raw, missing = prices.all_known_splits(ticker, scan_years)
        except Exception as exc:  # noqa: BLE001 -- advisory scan, never fatal by itself
            result.unchecked.append(f"{ticker}: {exc}")
            continue
        if missing:
            result.unchecked.append(
                f"{ticker}: no price data for "
                + ", ".join(str(y) for y in missing)
                + ", so any split in those years was NOT checked"
            )
        events = [SplitEvent(ticker, day, ratio) for day, ratio in raw if day <= today]
        per_ticker[ticker] = events
        result.events.extend(events)

    result.events.sort(key=lambda e: (e.date, e.ticker))

    for txn in transactions:
        if txn.quantity <= 0:
            continue  # dividends carry no share count to restate
        events = [e for e in per_ticker.get(txn.ticker, []) if e.date > txn.date]
        if not events:
            continue
        factor = Decimal(1)
        for event in events:
            factor *= event.ratio
        verdict, evidence = _classify(txn, factor, prices)
        result.exposures.append(
            SplitExposure(txn=txn, events=events, factor=factor,
                          verdict=verdict, evidence=evidence)
        )
    return result


def _classify(txn: Transaction, factor: Decimal, prices) -> tuple[str, str]:
    """Guess the basis of a transaction by comparing its price to the adjusted close.

    If the recorded price is near Yahoo's (adjusted) close for that day, the row is on the
    current basis. If it is near the close times the split factor, it is the historical
    price and the quantity will be historical too.
    """
    if txn.price_usd <= 0:
        return "unknown", "no price recorded, cannot infer basis"
    try:
        series = prices.series(txn.ticker, txn.date.year)
        close, close_date = series.close_on(txn.date)
    except Exception as exc:  # noqa: BLE001
        return "unknown", f"no reference price ({exc})"
    if close <= 0:
        return "unknown", "reference close is zero"

    as_current = abs(txn.price_usd / close - 1)
    as_historical = abs(txn.price_usd / (close * factor) - 1)
    stamp = "" if close_date == txn.date else f" (close of {close_date})"
    if as_current <= _TOLERANCE and as_current < as_historical:
        return "current", (
            f"recorded {txn.price_usd} vs split-adjusted close {close}{stamp}: "
            f"looks already restated"
        )
    if as_historical <= _TOLERANCE and as_historical < as_current:
        return "historical", (
            f"recorded {txn.price_usd} vs unadjusted close {close * factor}{stamp} "
            f"(adjusted {close} x {factor}): looks like the price of the day"
        )
    return "unknown", (
        f"recorded {txn.price_usd} matches neither the adjusted close {close} nor the "
        f"unadjusted {close * factor}{stamp}"
    )


def describe(scan_result: SplitScan) -> str:
    """The hard-failure message. Names ticker, date and ratio, per the brief."""
    lines = [
        "STOCK SPLIT DETECTED -- refusing to compute values that could be wrong by the "
        "split factor.",
        "",
        "Splits affecting your holdings:",
    ]
    seen = set()
    for exposure in scan_result.exposures:
        for event in exposure.events:
            key = (event.ticker, event.date)
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"  {event.ticker}: {event.label} split effective {event.date}"
            )

    lines += [
        "",
        "Yahoo's historical prices are already restated for these splits; your broker CSV",
        "may or may not be. Getting this wrong misstates the holding by the split factor.",
        "",
        "Transactions acquired or sold before a split:",
    ]
    for exposure in sorted(scan_result.exposures, key=lambda e: (e.txn.date, e.txn.ticker)):
        txn = exposure.txn
        lines.append(
            f"  {txn.date} {txn.ticker} {txn.txn_type} qty={txn.quantity} "
            f"@ {txn.price_usd} [{txn.source_file} line {txn.source_row}] "
            f"factor {exposure.factor}"
        )
        lines.append(f"      evidence: {exposure.evidence} -> looks {exposure.verdict}")

    votes = [e.verdict for e in scan_result.exposures if e.verdict != "unknown"]
    if votes and len(set(votes)) == 1:
        suggestion = votes[0]
        confidence = f"Every priced row looks like the '{suggestion}' basis."
    elif votes:
        suggestion = "historical"
        confidence = (
            "Rows disagree with each other. Check each one against the broker statement "
            "before choosing."
        )
    else:
        suggestion = "historical"
        confidence = "No row could be classified automatically. Check the statement."

    lines += [
        "",
        confidence,
        "",
        "Decide which basis your transactions.csv is on, then re-run with:",
        "",
        "  --split-basis current      quantities ALREADY restated for the split",
        "                             (a CSV freshly downloaded from the broker usually is:",
        "                              e.g. a pre-split AVGO lot shows as 10x the shares)",
        "  --split-basis historical   quantities as printed at the time, pre-split",
        "                             (the tool will restate them for you)",
        "",
        f"  Based on the evidence above, '{suggestion}' is the likely answer -- but verify",
        "  against the broker statement. Compare the share count on a statement dated after",
        "  the split with the one in your CSV: if they match, you are on 'current'.",
    ]
    return "\n".join(lines)


def restate(transactions: list[Transaction], scan_result: SplitScan) -> list[Transaction]:
    """Move historical-basis quantities and prices onto the current basis.

    Dollar amounts (gross proceeds, dividends, tax withheld) are untouched: a split does
    not change how many dollars changed hands.
    """
    factors = {id(e.txn): e.factor for e in scan_result.exposures}
    out: list[Transaction] = []
    for txn in transactions:
        factor = factors.get(id(txn))
        if not factor or factor == 1:
            out.append(txn)
            continue
        out.append(dataclasses.replace(
            txn,
            quantity=txn.quantity * factor,
            price_usd=(txn.price_usd / factor) if txn.price_usd else txn.price_usd,
            notes=(txn.notes + f"; restated for {factor}x split").lstrip("; "),
        ))
    return out


def apply(transactions: list[Transaction], prices, year: int,
          basis: str | None) -> tuple[list[Transaction], SplitScan]:
    """Scan, then either hard-fail or restate according to the declared basis."""
    scan_result = scan(transactions, prices, year)
    if not scan_result.affected:
        return transactions, scan_result
    if basis is None:
        raise DataError(describe(scan_result))
    if basis not in SPLIT_BASES:
        raise DataError(f"--split-basis must be one of {SPLIT_BASES}")
    if basis == SPLIT_BASIS_CURRENT:
        return transactions, scan_result
    return restate(transactions, scan_result), scan_result
