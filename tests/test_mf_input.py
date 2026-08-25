"""The mutual fund CSV layer: reading, refusing, and the financial-year window.

The engine's arithmetic lives in tests/test_capgain.py; this file covers the CSV
contract that surrounds it: malformed rows are refused with file and line, undeclared
schemes are refused, sales outside the return's financial year are excluded from the
totals (but still consume lots in the FIFO replay), and the Schedule 112A block the
builder assembles is exactly the department's schema shape -- integers where the
schema says integer, four-decimal floats where it says multipleOf 0.0001.

Every figure below is invented. Run:  .venv/bin/python tests/test_mf_input.py
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import capgain, mf_input, rules

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(f"{label}{(' -- ' + detail) if detail else ''}")
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


def refuses(label: str, fn, needle: str = "", exc_type: type[Exception] = mf_input.MfInputError) -> None:
    try:
        fn()
    except exc_type as exc:
        if needle and needle.lower() not in str(exc).lower():
            failures.append(f"{label}: refusal lacks {needle!r} -- {exc}")
            print(f"  FAIL  {label}: refusal text lacks {needle!r}")
        else:
            print(f"  ok    {label}")
        return
    failures.append(f"{label}: no refusal raised")
    print(f"  FAIL  {label}: expected MfInputError")


def _write(tmp: str, name: str, lines: list[str]) -> str:
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


SCHEME_ROW = "INF123F01000,SYNTHETIC EQUITY FUND TEST SCHEME,equity_oriented,yes,"


def main() -> int:
    engine = capgain.Engine(rules.load("2027-28"))
    window = capgain.fy_window("2026-27")
    check("the FY 2026-27 window is 1 Apr 2026 to 31 Mar 2027",
          window == (dt.date(2026, 4, 1), dt.date(2027, 3, 31)), str(window))
    refuses("a malformed financial year is refused",
            lambda: capgain.fy_window("2026/27"), "YYYY-YY",
            exc_type=capgain.MfError)

    print("\n[CSV reading]")
    with tempfile.TemporaryDirectory() as tmp:
        schemes = _write(tmp, "mf_schemes.csv", [
            ",".join(mf_input.SCHEMES_COLUMNS), SCHEME_ROW,
        ])
        txns = _write(tmp, "mf_transactions.csv", [
            ",".join(mf_input.TRANSACTIONS_COLUMNS),
            "INF123F01000,purchase,2026-04-01,200,40.0000,,synthetic",
            "INF123F01000,bonus,2026-06-01,20,,,synthetic",
            "INF123F01000,sale,2026-11-01,220,52.0000,120.50,synthetic",
        ])
        ledgers = mf_input.load_ledgers(schemes, txns)
        check("a declared scheme with activity loads as one ledger",
              len(ledgers) == 1 and len(ledgers[0].sales) == 1)
        rows = engine.scheme_gains(ledgers[0])
        check("the bonus units match at zero cost inside the sale",
              any(r.lot.cost_per_unit == Decimal(0) for r in rows),
              str([str(r.lot.cost_per_unit) for r in rows]))

    with tempfile.TemporaryDirectory() as tmp:
        schemes = _write(tmp, "mf_schemes.csv", [
            ",".join(mf_input.SCHEMES_COLUMNS), SCHEME_ROW,
        ])
        txns = _write(tmp, "mf_transactions.csv", [
            ",".join(mf_input.TRANSACTIONS_COLUMNS),
            "INF123F01000,purchase,2026-04-01,200,40.0000,,synthetic",
            "INFNOTDECLARED0,sale,2026-11-01,10,50,,synthetic",
        ])
        refuses("a sale of an undeclared scheme is refused",
                lambda: mf_input.load_ledgers(schemes, txns), "mf_schemes.csv")

        txns2 = _write(tmp, "bad_type.csv", [
            ",".join(mf_input.TRANSACTIONS_COLUMNS),
            "INF123F01000,transfer,2026-04-01,200,40.0000,,synthetic",
        ])
        refuses("an unknown transaction type is refused",
                lambda: mf_input.load_ledgers(schemes, txns2), "must be one of")

        txns3 = _write(tmp, "bad_date.csv", [
            ",".join(mf_input.TRANSACTIONS_COLUMNS),
            "INF123F01000,purchase,01/04/2026,200,40.0000,,synthetic",
        ])
        refuses("a non-ISO date is refused",
                lambda: mf_input.load_ledgers(schemes, txns3), "ISO")

        schemes2 = _write(tmp, "dup_schemes.csv", [
            ",".join(mf_input.SCHEMES_COLUMNS), SCHEME_ROW, SCHEME_ROW,
        ])
        refuses("a duplicate scheme declaration is refused",
                lambda: mf_input.load_schemes(schemes2), "declared twice")

    print("\n[financial-year window]")
    with tempfile.TemporaryDirectory() as tmp:
        schemes = _write(tmp, "mf_schemes.csv", [
            ",".join(mf_input.SCHEMES_COLUMNS), SCHEME_ROW,
        ])
        # Two sales: one inside FY 2026-27, one in FY 2025-26. The earlier sale MUST
        # consume its lots first or the in-window sale would match against units that
        # no longer existed in November 2026.
        txns = _write(tmp, "mf_transactions.csv", [
            ",".join(mf_input.TRANSACTIONS_COLUMNS),
            "INF123F01000,purchase,2025-04-01,100,30.0000,,synthetic",
            "INF123F01000,purchase,2025-10-01,100,40.0000,,synthetic",
            "INF123F01000,sale,2026-03-15,100,45.0000,,synthetic",
            "INF123F01000,sale,2026-11-01,100,52.0000,,synthetic",
        ])
        ledgers = mf_input.load_ledgers(schemes, txns)
        rows_112a, summary = mf_input.run_engine(ledgers, engine, window)
        check("the out-of-window sale is named in the summary",
              any("outside this return's financial year" in line for line in summary),
              str(summary))
        # In-window sale matches the SECOND lot (FIFO after the March sale took the
        # first): 100 * (52 - 40) = 1200.
        row = rows_112a[0]
        check("the in-window sale matched against the correct surviving lot",
              row["LTCGBeforelowerB1B2"] == 1200 and row["AcquisitionCost"] == 40.0,
              f"ltcg={row['LTCGBeforelowerB1B2']} cost={row['AcquisitionCost']}")

    print("\n[Schedule 112A assembly]")
    row = {
        "ShareOnOrBefore": "AE", "ISINCode": "INF123F01000",
        "ShareUnitName": "SYNTHETIC EQUITY FUND TEST SCHEME",
        "NumSharesUnits": 200.0, "SalePricePerShareUnit": 52.0,
        "TotSaleValue": 10400, "CostAcqWithoutIndx": 8000,
        "AcquisitionCost": 40.0, "LTCGBeforelowerB1B2": 2280,
        "FairMktValuePerShareunit": 0.0, "TotFairMktValueCapAst": 0,
        "ExpExclCnctTransfer": 120.5, "TotalDeductions": 8121, "Balance": 2280,
    }
    schedule = mf_input.build_schedule_112a([row])
    check("the aggregate expense rounds to whole rupees (120.5 -> 121)",
          schedule["ExpExclCnctTransfer112A"] == 121,
          str(schedule["ExpExclCnctTransfer112A"]))
    check("every aggregate except the detail list is an int",
          all(type(schedule[k]) is int for k in schedule if k != "Schedule112ADtls"),
          str({k: type(schedule[k]).__name__ for k in schedule}))
    check("the acquisition-cost aggregate sums totals, not per-unit values",
          schedule["AcquisitionCost112A"] == 8000,
          str(schedule["AcquisitionCost112A"]))

    try:
        from itrprep import validate
        schema, schema_path = validate.load_schema()
        subschema = {
            "$schema": schema.get("$schema"),
            "definitions": schema["definitions"],
            "$ref": "#/definitions/Schedule112A",
        }
        errs = validate._format_errors(validate._validator(subschema), schedule)
        check("the assembled Schedule112A validates against the official schema",
              not errs, "; ".join(errs[:3]))
        print(f"  note  validated against {os.path.basename(schema_path)}")
    except Exception as exc:
        print(f"  note  official schema not available ({exc.__class__.__name__}); "
              "skipped the schema check")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All mf_input checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
