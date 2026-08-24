"""The mutual fund capital gains engine, against hand-computed figures.

Every expected value below was worked out by hand from the provisions the registry
cites (holding periods per section 2(101) of the Income-tax Act, 2025; grandfathering
per section 90(7); FIFO per section 67(7)(c); bonus-unit cost per section 90(6)(d)).
The engine reads the actual registry, so a test failure here is either a bug in the
engine or a change in the law that nobody has reconciled -- both worth stopping for.

Run:  .venv/bin/python tests/test_capgain.py
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import capgain, rules

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(f"{label}{(' -- ' + detail) if detail else ''}")
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


def refuses(label: str, fn, needle: str = "") -> None:
    """A refusal with the reason attached is a behaviour, not a crash: the engine must
    raise MfError, and the reason must say why."""
    try:
        fn()
    except capgain.MfError as exc:
        if needle and needle.lower() not in str(exc).lower():
            failures.append(f"{label}: refusal does not say {needle!r} -- {exc}")
            print(f"  FAIL  {label}: refusal text lacks {needle!r}")
            print(f"        {exc}")
        else:
            print(f"  ok    {label} (refused: {str(exc)[:80]}...)")
        return
    failures.append(f"{label}: no refusal raised")
    print(f"  FAIL  {label}: expected an MfError, got a result")


def _engine():
    return capgain.Engine(rules.load("2027-28"))


def _scheme(classification=capgain.EQUITY_ORIENTED, fmv=None,
            isin="INF123F01234", name="SYNTHETIC EQUITY FUND TEST SCHEME"):
    return capgain.SchemeDecl(isin=isin, name=name, classification=classification,
                              listed=True, fmv_2018_01_31=fmv)


def main() -> int:
    eng = _engine()

    # ------------------------------------------------------------ registry wiring
    print("\n[registry wiring]")
    check("the engine's cutoff is the registry's 2018-02-01",
          eng.cutoff == dt.date(2018, 2, 1), str(eng.cutoff))
    check("the valuation date is the registry's 2018-01-31",
          eng.valuation_date == dt.date(2018, 1, 31), str(eng.valuation_date))
    check("equity-oriented long-term threshold is 12 months",
          eng.long_term_months == 12, str(eng.long_term_months))
    check("the default long-term threshold is 24 months",
          eng.default_long_term_months == 24, str(eng.default_long_term_months))
    check("bonus units cost the registry's figure (zero)",
          eng.bonus_cost == Decimal(0), str(eng.bonus_cost))

    # A registry that contradicts the engine's premises must stop it.
    reg2 = rules.load("2027-28")
    reg2.entries[capgain.KEY_INDEXATION].value = True
    refuses("an indexation-offering registry is refused", lambda: capgain.Engine(reg2),
            "indexation")
    reg3 = rules.load("2027-28")
    reg3.entries[capgain.KEY_LOT_MATCHING].value = "LIFO"
    refuses("a non-FIFO lot method is refused", lambda: capgain.Engine(reg3), "FIFO")

    # ------------------------------------------------------------ FIFO matching
    print("\n[FIFO matching]")
    scheme = _scheme()
    ledger = capgain.Ledger(scheme)
    ledger.add(capgain.Purchase("INF123F01234", dt.date(2026, 4, 15), "100", "50.00",
                                "synthetic"))
    ledger.add(capgain.Purchase("INF123F01234", dt.date(2026, 6, 1), "100", "60.00",
                                "synthetic"))
    sale = capgain.Sale("INF123F01234", dt.date(2026, 12, 20), "150", "75.00",
                        source_ref="synthetic")
    ledger.add(sale)
    lots = eng.match_sale(ledger, sale)
    check("a 150-unit sale matches two lots, oldest first",
          len(lots) == 2 and lots[0].units == 100 and lots[1].units == 50,
          str([(str(l.units), str(l.cost_per_unit)) for l in lots]))
    check("the first lot carries the April price",
          lots[0].cost_per_unit == Decimal("50.00"), str(lots[0].cost_per_unit))
    check("the second lot carries the June price",
          lots[1].cost_per_unit == Decimal("60.00"), str(lots[1].cost_per_unit))

    rows = eng.scheme_gains(ledger)
    # Both lots are short-term: 8 months and 6 months, both inside the 12-month
    # threshold. Gains: 100 * (75 - 50) = 2500; 50 * (75 - 60) = 750.
    check("both matched lots are short-term",
          all(not r.long_term for r in rows), str([r.long_term for r in rows]))
    ltcg, stcg = eng.sums(rows)
    check("short-term gain is 3250", stcg == Decimal("3250"), str(stcg))
    check("long-term gain is zero", ltcg == Decimal("0"), str(ltcg))

    refuses("selling more than the ledger holds is refused",
            lambda: eng.match_sale(ledger, capgain.Sale(
                "INF123F01234", dt.date(2027, 1, 5), "100", "80.00",
                source_ref="synthetic")),
            "exceeds the open balance")

    # ------------------------------------------------------------ holding period
    print("\n[holding period boundary]")
    # Section 2(101) makes the SHORT-TERM asset one held "not more than" twelve
    # months: exactly twelve months is still short-term.
    scheme2 = _scheme(isin="INF123F01235", name="SYNTHETIC BOUNDARY FUND")
    exactly = capgain.Ledger(scheme2)
    exactly.add(capgain.Purchase("INF123F01235", dt.date(2026, 4, 15), "10", "100",
                                 "synthetic"))
    exactly.add(capgain.Sale("INF123F01235", dt.date(2027, 4, 15), "10", "120",
                             source_ref="synthetic"))
    row = eng.scheme_gains(exactly)[0]
    check("exactly twelve months is still SHORT-term",
          not row.long_term, f"{row.holding_days} days")
    over = capgain.Ledger(scheme2)
    over.add(capgain.Purchase("INF123F01235", dt.date(2026, 4, 15), "10", "100",
                              "synthetic"))
    over.add(capgain.Sale("INF123F01235", dt.date(2027, 4, 16), "10", "120",
                          source_ref="synthetic"))
    row = eng.scheme_gains(over)[0]
    check("twelve months and one day is long-term",
          row.long_term, f"{row.holding_days} days")

    other = _scheme(classification=capgain.OTHER_FUND, isin="INF123F01236",
                    name="SYNTHETIC OTHER FUND")
    twentyfour = capgain.Ledger(other)
    twentyfour.add(capgain.Purchase("INF123F01236", dt.date(2024, 5, 1), "100", "10",
                                    "synthetic"))
    twentyfour.add(capgain.Sale("INF123F01236", dt.date(2026, 5, 1), "100", "18",
                                source_ref="synthetic"))
    rows = eng.scheme_gains(twentyfour)
    check("exactly twenty-four months on an other-fund is still short-term",
          all(not r.long_term for r in rows))
    twentyfour2 = capgain.Ledger(other)
    twentyfour2.add(capgain.Purchase("INF123F01236", dt.date(2024, 5, 1), "100", "10",
                                     "synthetic"))
    twentyfour2.add(capgain.Sale("INF123F01236", dt.date(2026, 5, 2), "100", "18",
                                 source_ref="synthetic"))
    rows = eng.scheme_gains(twentyfour2)
    check("twenty-four months and a day on an other-fund is long-term",
          all(r.long_term for r in rows))
    check("an other-fund's pre-cutoff lot keeps its actual cost (no FMV regime)",
          rows[0].cost_of_acquisition == Decimal("1000")
          and not rows[0].grandfathered,
          f"cost={rows[0].cost_of_acquisition} gf={rows[0].grandfathered}")

    # ------------------------------------------------------------ grandfathering
    print("\n[grandfathering, section 90(7)]")
    # cost = higher of (actual cost) and (lower of valuation-date FMV, proceeds).
    base = dict(isin="INF123F01237", name="SYNTHETIC GRANDFATHERED FUND")

    def be_scheme(fmv):
        return _scheme(fmv=fmv, **base)

    def be_ledger(scheme, sale_price):
        ledger = capgain.Ledger(scheme)
        ledger.add(capgain.Purchase(base["isin"], dt.date(2017, 6, 1), "100", "30",
                                    "synthetic"))
        ledger.add(capgain.Sale(base["isin"], dt.date(2026, 5, 10), "100", sale_price,
                                source_ref="synthetic"))
        return ledger

    # FMV 45 sits between cost 30 and proceeds 60: cost becomes the FMV.
    rows = eng.scheme_gains(be_ledger(be_scheme("45"), "60"))
    check("FMV between cost and proceeds: cost is the FMV",
          rows[0].cost_of_acquisition == Decimal("4500")
          and rows[0].gain == Decimal("1500"),
          f"cost={rows[0].cost_of_acquisition} gain={rows[0].gain}")
    check("the lot records its valuation-date FMV",
          rows[0].fmv_value == Decimal("4500"), str(rows[0].fmv_value))

    # Proceeds 40 fall below the FMV: cost is capped at the proceeds, gain is nil --
    # grandfathering never manufactures a loss.
    rows = eng.scheme_gains(be_ledger(be_scheme("45"), "40"))
    check("proceeds below FMV: gain is nil, not negative",
          rows[0].cost_of_acquisition == Decimal("4000") and rows[0].gain == Decimal("0"),
          f"cost={rows[0].cost_of_acquisition} gain={rows[0].gain}")

    # Proceeds 25 fall below the ACTUAL cost too: the loss is real and unchanged by
    # grandfathering (the formula takes the higher of cost and the FMV/proceeds leg).
    rows = eng.scheme_gains(be_ledger(be_scheme("45"), "25"))
    check("proceeds below actual cost: the real loss survives grandfathering",
          rows[0].cost_of_acquisition == Decimal("3000")
          and rows[0].gain == Decimal("-500"),
          f"cost={rows[0].cost_of_acquisition} gain={rows[0].gain}")

    refuses("a pre-cutoff scheme without a declared FMV is refused",
            lambda: eng.scheme_gains(be_ledger(be_scheme(None), "60")),
            "fmv_2018_01_31")

    # ------------------------------------------------------------ bonus units
    print("\n[bonus units, section 90(6)(d)]")
    scheme_b = _scheme(isin="INF123F01238", name="SYNTHETIC BONUS FUND")
    ledger_b = capgain.Ledger(scheme_b)
    ledger_b.add(capgain.Purchase("INF123F01238", dt.date(2026, 1, 10), "100", "20",
                                  "synthetic"))
    ledger_b.add(capgain.Bonus("INF123F01238", dt.date(2026, 3, 1), "10", "synthetic"))
    ledger_b.add(capgain.Sale("INF123F01238", dt.date(2027, 2, 1), "110", "25",
                              source_ref="synthetic"))
    rows = eng.scheme_gains(ledger_b)
    paid = [r for r in rows if r.lot.cost_per_unit == Decimal("20")]
    free = [r for r in rows if r.lot.cost_per_unit == Decimal("0")]
    check("the paid lot matches 100 units long-term at its price",
          len(paid) == 1 and paid[0].lot.units == Decimal("100") and paid[0].long_term
          and paid[0].gain == Decimal("500"),
          str([(str(r.lot.units), str(r.gain)) for r in paid]))
    check("the bonus lot costs zero and is short-term",
          len(free) == 1 and not free[0].long_term and free[0].gain == Decimal("250"),
          str([(str(r.lot.units), str(r.gain), r.long_term) for r in free]))

    # ------------------------------------------------------------ declarations
    print("\n[declarations and refusals]")
    refuses("an undeclared classification is refused",
            lambda: _scheme(classification="hybrid"), "classification")
    refuses("a wrong-ISIN event is refused",
            lambda: capgain.Ledger(scheme).add(
                capgain.Purchase("INFOTHER00001", dt.date(2026, 1, 1), "1", "1")),
            "ledger for")
    refuses("Schedule 112A refuses a non-equity-oriented scheme",
            lambda: capgain.schedule_112a_row(other, eng.scheme_gains(twentyfour2),
                                              eng.cutoff),
            "section 198")

    # Mixed vintages: one scheme, lots on both sides of the cutoff. The schema's row
    # flag cannot say both, so the emitter refuses rather than choose. (Both lots must
    # actually be long-term for the mixed check to be the one that fires: the AE lot
    # bought 2026-01-15 needs more than twelve months, hence the 2027 sale.)
    mixed_scheme = _scheme(fmv="45", isin="INF123F01239",
                           name="SYNTHETIC MIXED VINTAGE FUND")
    mixed = capgain.Ledger(mixed_scheme)
    mixed.add(capgain.Purchase("INF123F01239", dt.date(2017, 6, 1), "50", "30",
                               "synthetic"))
    mixed.add(capgain.Purchase("INF123F01239", dt.date(2026, 1, 15), "50", "55",
                               "synthetic"))
    mixed.add(capgain.Sale("INF123F01239", dt.date(2027, 2, 1), "100", "70",
                           source_ref="synthetic"))
    refuses("a scheme with lots on both sides of the cutoff is refused",
            lambda: capgain.schedule_112a_row(mixed_scheme, eng.scheme_gains(mixed),
                                              eng.cutoff),
            "both sides")

    # ------------------------------------------------------------ the 112A row
    print("\n[Schedule 112A row]")
    rows = eng.scheme_gains(be_ledger(be_scheme("45"), "60"))
    row = capgain.schedule_112a_row(be_scheme("45"), rows, eng.cutoff)
    expected = {
        "ShareOnOrBefore": "BE",
        "ISINCode": "INF123F01237",
        "ShareUnitName": "SYNTHETIC GRANDFATHERED FUND",
        "NumSharesUnits": 100.0,
        "SalePricePerShareUnit": 60.0,
        "TotSaleValue": 6000,
        "CostAcqWithoutIndx": 4500,
        "AcquisitionCost": 45.0,
        "LTCGBeforelowerB1B2": 1500,
        "FairMktValuePerShareunit": 45.0,
        "TotFairMktValueCapAst": 4500,
        "ExpExclCnctTransfer": 0.0,
        "TotalDeductions": 4500,
        "Balance": 1500,
    }
    for field, want in expected.items():
        got = row[field]
        check(f"112A row {field} is {want!r}",
              got == want and type(got) is type(want),
              f"got {got!r} ({type(got).__name__})")

    # An AE (post-cutoff) row: no FMV columns, actual cost throughout.
    ae_scheme = _scheme(isin="INF123F01240", name="SYNTHETIC AE FUND")
    ae_ledger = capgain.Ledger(ae_scheme)
    ae_ledger.add(capgain.Purchase("INF123F01240", dt.date(2025, 8, 1), "200", "40",
                                   "synthetic"))
    ae_ledger.add(capgain.Sale("INF123F01240", dt.date(2026, 9, 1), "200", "52",
                               source_ref="synthetic"))
    ae_row = capgain.schedule_112a_row(ae_scheme, eng.scheme_gains(ae_ledger),
                                       eng.cutoff)
    check("an AE row says AE", ae_row["ShareOnOrBefore"] == "AE")
    check("an AE row's FMV columns are zero",
          ae_row["FairMktValuePerShareunit"] == 0.0
          and ae_row["TotFairMktValueCapAst"] == 0,
          f"{ae_row['FairMktValuePerShareunit']}, {ae_row['TotFairMktValueCapAst']}")
    check("an AE row's cost is the actual cost",
          ae_row["CostAcqWithoutIndx"] == 8000 and ae_row["AcquisitionCost"] == 40.0,
          f"{ae_row['CostAcqWithoutIndx']}, {ae_row['AcquisitionCost']}")
    # 200 units * (52 - 40) = 2400.
    check("an AE row's balance is 2400", ae_row["Balance"] == 2400,
          str(ae_row["Balance"]))

    # Four-decimal per-unit values survive quantisation exactly.
    frac_scheme = _scheme(isin="INF123F01241", name="SYNTHETIC FRACTIONAL FUND")
    frac = capgain.Ledger(frac_scheme)
    frac.add(capgain.Purchase("INF123F01241", dt.date(2025, 1, 1), "123.4567",
                              "10.1234", "synthetic"))
    frac.add(capgain.Sale("INF123F01241", dt.date(2026, 3, 1), "123.4567", "15.5678",
                          source_ref="synthetic"))
    frow = capgain.schedule_112a_row(frac_scheme, eng.scheme_gains(frac), eng.cutoff)
    check("fractional units round-trip to four decimals",
          frow["NumSharesUnits"] == 123.4567, str(frow["NumSharesUnits"]))
    check("the sale price per unit round-trips to four decimals",
          frow["SalePricePerShareUnit"] == 15.5678, str(frow["SalePricePerShareUnit"]))
    # Rupee aggregates are integers: proceeds 123.4567 * 15.5678 = 1921.932...
    check("rupee aggregates are ints",
          all(type(frow[k]) is int for k in
              ("TotSaleValue", "CostAcqWithoutIndx", "LTCGBeforelowerB1B2",
               "TotFairMktValueCapAst", "TotalDeductions", "Balance")),
          str({k: type(frow[k]).__name__ for k in
               ("TotSaleValue", "TotalDeductions", "Balance")}))

    # If the department's schema is on disk, the row must validate against it --
    # which also exercises the exact-decimal multipleOf override for a real row.
    try:
        from itrprep import validate
        schema, schema_path = validate.load_schema()
        subschema = {
            "$schema": schema.get("$schema"),
            "definitions": schema["definitions"],
            "$ref": "#/definitions/Schedule112A115ADType",
        }
        for label, candidate in (("BE grandfathered row", row), ("AE row", ae_row),
                                 ("fractional row", frow)):
            errs = validate._format_errors(validate._validator(subschema), candidate)
            check(f"the {label} validates against the official schema",
                  not errs, "; ".join(errs[:3]))
        print(f"  note  validated against {os.path.basename(schema_path)}")
    except Exception as exc:
        print(f"  note  official schema not available ({exc.__class__.__name__}); "
              "row-shape checks ran without it")

    # ------------------------------------------------------------ verdict
    print()
    if failures:
        print(f"FAILED: {len(failures)} engine check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All engine checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
