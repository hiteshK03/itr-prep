"""Checks for the three additions: split handling, cash balances, threshold report.

The split checks are the important ones. AVGO's 10-for-1 split of 15 July 2024 is a real
corporate action sitting in the middle of the reporting years, and getting it wrong moves
a holding by a factor of ten -- enough on its own to flip the Rs 20 lakh verdict. So these
assert the *size* of the error, not just that something was detected.

Run:  .venv/bin/python tests/test_splits_cash_threshold.py
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import emit, intermediate, positions, splits, threshold
from itrprep.fx import FxRates
from itrprep.models import DataError
from itrprep.prices import PriceStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNTH = os.path.join(ROOT, "tests", "synthetic")
SPLIT_SYNTH = os.path.join(ROOT, "tests", "synthetic_split")
FX_CACHE = os.path.join(ROOT, "data", "sbi_ttbuy_usd.csv")
PRICE_CACHE = os.path.join(ROOT, "data", "prices")

AVGO_SPLIT_DATE = dt.date(2024, 7, 15)
AVGO_SPLIT_RATIO = Decimal(10)

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        failures.append(f"{label}: {detail}")


def _load(work_dir: str):
    transactions = intermediate.read_transactions(
        os.path.join(work_dir, "transactions.csv")
    )
    issuers = intermediate.read_issuers(os.path.join(work_dir, "issuers.csv"))
    accounts = intermediate.read_accounts(os.path.join(work_dir, "accounts.csv"))
    cash = intermediate.read_cash_balances(
        os.path.join(work_dir, "cash_balances.csv")
    )
    return transactions, issuers, accounts, cash


def _write(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


CASH_HEADER = "account_id,year,peak_usd,peak_date,closing_usd,notes\n"


def main() -> int:
    fx = FxRates.load(FX_CACHE)
    prices = PriceStore(PRICE_CACHE)

    # ---------------------------------------------------------------- splits
    print("\n[split detection]")
    txns, issuers, accounts, cash = _load(SPLIT_SYNTH)

    scan = splits.scan(txns, prices, 2024)
    check("a real split is found from the Yahoo events feed", scan.affected)
    found = {(e.ticker, e.date, e.ratio) for e in scan.events}
    check(
        "AVGO 10-for-1 of 2024-07-15 is identified with the right ratio",
        ("AVGO", AVGO_SPLIT_DATE, AVGO_SPLIT_RATIO) in found,
        str(sorted(found)),
    )
    check(
        "the pre-split lot is flagged, and only that one",
        len(scan.exposures) == 1
        and scan.exposures[0].txn.date == dt.date(2023, 11, 15),
        f"{len(scan.exposures)} exposure(s)",
    )
    check(
        "cumulative factor is 10",
        scan.exposures[0].factor == AVGO_SPLIT_RATIO,
        str(scan.exposures[0].factor),
    )
    check(
        "the price heuristic reads this file as the historical basis",
        scan.exposures[0].verdict == "historical",
        scan.exposures[0].evidence,
    )

    try:
        splits.apply(txns, prices, 2024, None)
        check("build refuses to proceed with no --split-basis", False, "no error")
    except DataError as exc:
        message = str(exc)
        check("build refuses to proceed with no --split-basis", True)
        check(
            "the refusal names ticker, date and ratio",
            "AVGO" in message and "2024-07-15" in message and "10-for-1" in message,
        )

    restated, _ = splits.apply(txns, prices, 2024, splits.SPLIT_BASIS_HISTORICAL)
    original = [t for t in txns if t.quantity > 0][0]
    moved = [t for t in restated if t.quantity > 0][0]
    check(
        "historical basis multiplies quantity by the split factor",
        moved.quantity == original.quantity * AVGO_SPLIT_RATIO,
        f"{original.quantity} -> {moved.quantity}",
    )
    check(
        "and divides the price by it, leaving cost unchanged",
        moved.quantity * moved.price_usd == original.quantity * original.price_usd,
    )
    untouched, _ = splits.apply(txns, prices, 2024, splits.SPLIT_BASIS_CURRENT)
    check(
        "current basis leaves quantities alone",
        [t.quantity for t in untouched] == [t.quantity for t in txns],
    )

    # The whole point: the two bases differ by exactly the split factor, and that
    # difference is what would silently corrupt the disclosure.
    values = {}
    for basis in (splits.SPLIT_BASIS_HISTORICAL, splits.SPLIT_BASIS_CURRENT):
        adjusted, _ = splits.apply(txns, prices, 2024, basis)
        rows = positions.compute_rows(
            positions.build_lots(adjusted), adjusted, 2024, prices, fx
        )
        values[basis] = sum(r.peak_value_inr for r in rows)
    ratio = values[splits.SPLIT_BASIS_HISTORICAL] / values[splits.SPLIT_BASIS_CURRENT]
    check(
        "choosing the wrong basis is a factor-of-ten error",
        abs(ratio - 10) < 0.01,
        f"{values[splits.SPLIT_BASIS_HISTORICAL]} vs "
        f"{values[splits.SPLIT_BASIS_CURRENT]} (ratio {ratio:.4f})",
    )

    # A year whose prices cannot be read is a year whose splits were not checked. That has
    # to be reported, or offline mode would quietly downgrade the whole guarantee.
    cold = PriceStore("/tmp/itrprep-empty-price-cache", offline=True)
    cold_scan = splits.scan(txns, cold, 2024)
    check(
        "an unreadable year is reported as an incomplete split check",
        cold_scan.unchecked and "NOT checked" in cold_scan.unchecked[0],
        str(cold_scan.unchecked),
    )

    # A holding bought after the split must not be touched at all.
    main_txns, _, _, _ = _load(SYNTH)
    main_scan = splits.scan(main_txns, prices, 2025)
    check(
        "a lot acquired after the split is not flagged",
        not main_scan.affected,
        f"{len(main_scan.exposures)} exposure(s)",
    )

    # ---------------------------------------------------------------- cash
    print("\n[cash balances]")
    check("cash rows load", len(cash) == 3, f"{len(cash)} row(s)")
    values_2025 = positions.value_cash(cash, 2025, fx)
    check("only the requested year is returned", set(values_2025) == {"indmoney_us"})
    cash_2025 = values_2025["indmoney_us"]
    check(
        "a blank peak_date is recorded as an assumption, not hidden",
        any("31 Dec" in n for n in cash_2025.notes),
        str(cash_2025.notes),
    )
    check(
        "peak converts at the stated rate",
        cash_2025.peak_inr == positions.to_inr_int(
            cash_2025.peak_usd * cash_2025.peak_fx
        ),
    )

    restated_2025, _ = splits.apply(
        txns, prices, 2025, splits.SPLIT_BASIS_HISTORICAL
    )
    rows_2025 = positions.compute_rows(
        positions.build_lots(restated_2025), restated_2025, 2025, prices, fx
    )
    with_cash = emit.build_a2_rows(rows_2025, accounts, 2025, values_2025)
    without_cash = emit.build_a2_rows(rows_2025, accounts, 2025, None)
    check(
        "Table A2 peak rises by exactly the cash peak",
        with_cash[0]["PeakBalanceDuringPeriod"]
        - without_cash[0]["PeakBalanceDuringPeriod"] == cash_2025.peak_inr,
    )
    check(
        "Table A2 closing rises by exactly the cash closing",
        with_cash[0]["ClosingBalance"] - without_cash[0]["ClosingBalance"]
        == cash_2025.closing_inr,
    )
    check(
        "Table A3 is untouched by cash (cash is not an equity interest)",
        len(emit.build_a3_rows(rows_2025, issuers)) == len(rows_2025),
    )

    # An account holding only cash still has to be reported.
    only_cash = positions.value_cash(
        {("ghost_acct", 2025): intermediate.read_cash_balances(
            _write("/tmp/itrprep_cash_only.csv",
                   CASH_HEADER + "ghost_acct,2025,900,,900,\n")
        )[("ghost_acct", 2025)]},
        2025, fx,
    )
    accounts_plus = dict(accounts)
    accounts_plus["ghost_acct"] = accounts["indmoney_us"]
    ghost_rows = emit.build_a2_rows([], accounts_plus, 2025, only_cash)
    check("an account with cash but no securities still gets an A2 row",
          len(ghost_rows) == 1 and ghost_rows[0]["PeakBalanceDuringPeriod"] > 0)

    print("\n[cash validation]")
    for label, body in (
        ("negative cash is rejected", "a,2025,-5,,0,\n"),
        ("closing above peak is rejected", "a,2025,100,,500,\n"),
        ("duplicate account+year is rejected", "a,2025,100,,50,\na,2025,10,,5,\n"),
        ("non-numeric year is rejected", "a,twenty,100,,50,\n"),
        ("peak_date outside the year is rejected", "a,2025,100,2024-06-01,50,\n"),
    ):
        path = _write("/tmp/itrprep_cash_bad.csv", CASH_HEADER + body)
        try:
            intermediate.read_cash_balances(path)
            check(label, False, "no error raised")
        except DataError:
            check(label, True)
    check(
        "a missing cash file is not an error",
        intermediate.read_cash_balances("/tmp/does-not-exist-at-all.csv") == {},
    )

    # ---------------------------------------------------------------- threshold
    print("\n[threshold report]")
    check("a year range parses", threshold.parse_years("2022-2025")
          == [2022, 2023, 2024, 2025])
    check("a year list parses", threshold.parse_years("2023,2025") == [2023, 2025])
    for bad in ("", "2022-2019", "abc", "1899"):
        try:
            threshold.parse_years(bad)
            check(f"bad --years {bad!r} is rejected", False, "no error")
        except DataError:
            check(f"bad --years {bad!r} is rejected", True)

    adjusted, _ = splits.apply(txns, prices, 2025, splits.SPLIT_BASIS_HISTORICAL)
    report = threshold.compute(
        positions.build_lots(adjusted), adjusted, [2022, 2023, 2024, 2025],
        prices, fx, accounts, cash_balances=cash,
    )
    by_year = {y.year: y for y in report.years}

    check(
        "a year before any holding is NO DATA, not zero",
        not by_year[2022].has_data
        and by_year[2022].verdict(by_year[2022].peak_total) == "NO DATA",
        by_year[2022].reason,
    )
    check(
        "the NO DATA reason names the earliest transaction",
        "2023-11-15" in by_year[2022].reason,
        by_year[2022].reason,
    )
    for year in (2023, 2024, 2025):
        result = by_year[year]
        check(f"{year} has data", result.has_data)
        check(
            f"{year} totals equal the sum of their account lines",
            result.peak_total == sum(a.peak for a in result.accounts)
            and result.closing_total == sum(a.closing for a in result.accounts),
        )
        check(
            f"{year} account peaks equal securities plus cash",
            all(a.peak == a.securities_peak + a.cash_peak for a in result.accounts),
        )
        check(
            f"{year} conservative peak is never below the literal peak",
            result.peak_total_conservative >= result.peak_total,
            f"{result.peak_total_conservative} vs {result.peak_total}",
        )
        check(
            f"{year} peak is never below closing",
            result.peak_total >= result.closing_total,
            f"{result.peak_total} vs {result.closing_total}",
        )
        check(
            f"{year} verdict matches the arithmetic",
            result.verdict(result.peak_total)
            == ("OVER" if result.peak_total > threshold.threshold_inr() else "UNDER"),
        )

    # This dataset is built so 2024 lands on opposite sides of the line on the two
    # bases. That is the case the report has to shout about.
    check(
        "2024 straddles Rs 20 lakh on this dataset",
        by_year[2024].straddles,
        f"peak {by_year[2024].peak_total}, closing {by_year[2024].closing_total}",
    )
    check("the report knows it contains a straddle", report.any_straddle)

    text = threshold.render(report)
    for needle in ("STRADDLE WARNING", "20,00,000", "NO DATA", "CALENDAR YEAR 2024",
                   "Per account:", "Per holding"):
        check(f"rendered report contains {needle!r}", needle in text)
    check(
        "the straddle warning names the straddling year",
        "2024: peak" in text.split("STRADDLE WARNING")[1].split("=====")[0],
    )
    check(
        "cash is visible in the per-account breakdown",
        "Cash pk" in text,
    )

    csv_path = "/tmp/itrprep_threshold_audit.csv"
    threshold.write_csv(report, csv_path)
    import csv as _csv
    with open(csv_path, newline="", encoding="utf-8") as fh:
        audit = list(_csv.DictReader(fh))
    year_rows = {r["year"]: r for r in audit if r["level"] == "YEAR"}
    check("audit CSV carries a YEAR row per year", len(year_rows) == 4)
    check(
        "audit CSV year totals match the rendered totals",
        int(year_rows["2024"]["peak_inr"]) == by_year[2024].peak_total
        and int(year_rows["2024"]["closing_inr"]) == by_year[2024].closing_total,
    )
    lot_rows = [r for r in audit if r["level"] == "LOT" and r["year"] == "2024"]
    check(
        "audit CSV lot rows sum to the account securities total",
        sum(int(r["peak_inr"]) for r in lot_rows)
        == sum(a.securities_peak for a in by_year[2024].accounts),
    )
    check(
        "the NO DATA year is marked as such in the CSV rather than as 0",
        year_rows["2022"]["verdict_peak"] == "NO DATA"
        and year_rows["2022"]["peak_inr"] == "",
    )

    print()
    if failures:
        print(f"FAILED -- {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All split / cash / threshold checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
