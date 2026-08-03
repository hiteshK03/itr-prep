"""End-to-end checks on the synthetic dataset.

These assert conservation properties rather than golden numbers, because share prices come
from a live source and golden numbers would rot. The invariants are the things that must
hold for the disclosure to be arithmetically honest:

  - apportioned dividends sum back to the dividends actually received
  - apportioned sale proceeds sum back to the sales actually made
  - a lot fully sold during the year has a nil closing balance
  - peak value is never below the closing value of the same lot
  - a lot's peak share count never exceeds what it ever actually held

The proceeds invariant is the one that catches the E*TRADE duplicate-grant-number bug,
where several vests share one lot_id and per-lot amounts got merged and double-counted.

Run:  .venv/bin/python tests/test_pipeline.py
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import adapters, cli, emit, intermediate, positions, validate
from itrprep.fx import FxRates
from itrprep.models import TXN_BUY, TXN_DIVIDEND, TXN_SELL, Transaction
from itrprep.prices import PriceStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNTH = os.path.join(ROOT, "tests", "synthetic")
FX_CACHE = os.path.join(ROOT, "data", "sbi_ttbuy_usd.csv")
PRICE_CACHE = os.path.join(ROOT, "data", "prices")

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(f"{label}{(' -- ' + detail) if detail else ''}")
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    transactions = intermediate.read_transactions(
        os.path.join(SYNTH, "transactions.csv")
    )
    issuers = intermediate.read_issuers(os.path.join(SYNTH, "issuers.csv"))
    accounts = intermediate.read_accounts(os.path.join(SYNTH, "accounts.csv"))
    intermediate.cross_check(transactions, issuers, accounts)
    fx = FxRates.load(FX_CACHE)
    prices = PriceStore(PRICE_CACHE)

    lots = positions.build_lots(transactions)

    print("\n[lot construction]")
    check("every lot has a unique uid",
          len({l.uid for l in lots}) == len(lots),
          f"{len(lots)} lots, {len({l.uid for l in lots})} uids")
    duplicate_labels = len({l.lot_id for l in lots}) < len(lots)
    print(f"  note  broker lot_id labels are"
          f" {'NOT unique (as expected)' if duplicate_labels else 'unique here'}")
    check("no lot ends up with a negative position",
          all(l.qty_on(dt.date(2026, 12, 31)) >= 0 for l in lots))

    for year in (2023, 2024, 2025):
        print(f"\n[calendar {year}]")
        rows = positions.compute_rows(lots, transactions, year, prices, fx)
        check("produced at least one row", len(rows) > 0)

        # -- dividends must be conserved --
        received = sum(
            (t.gross_usd for t in transactions
             if t.txn_type == TXN_DIVIDEND and t.date.year == year),
            Decimal(0),
        )
        apportioned = sum((r.dividends_usd for r in rows), Decimal(0))
        check("apportioned dividends sum to dividends received",
              abs(received - apportioned) < Decimal("0.01"),
              f"received {received}, apportioned {apportioned}")

        # -- proceeds must be conserved (catches duplicate-lot_id merging) --
        sold = sum(
            (t.gross_usd for t in transactions
             if t.txn_type == TXN_SELL and t.date.year == year),
            Decimal(0),
        )
        attributed = sum((r.proceeds_usd for r in rows), Decimal(0))
        check("attributed proceeds sum to sales made",
              abs(sold - attributed) < Decimal("0.01"),
              f"sold {sold}, attributed {attributed}")

        # -- per-row sanity --
        check("peak >= closing for every row",
              all(r.peak_value_inr >= r.closing_value_inr for r in rows),
              str([r.lot_id for r in rows
                   if r.peak_value_inr < r.closing_value_inr]))
        check("no negative amounts",
              all(r.peak_value_inr >= 0 and r.closing_value_inr >= 0
                  and r.initial_value_inr >= 0 for r in rows))
        check("fully-exited lots have nil closing balance",
              all(r.closing_value_inr == 0 for r in rows if r.closing_qty == 0))
        check("lots still held have a non-zero closing balance",
              all(r.closing_value_inr > 0 for r in rows if r.closing_qty > 0))
        check("peak share count never exceeds the original lot size",
              all(r.peak_qty <= r.initial_qty for r in rows))
        check("every row has a peak date inside the reporting year",
              all(r.peak_date and r.peak_date.year == year for r in rows))

        # -- emit + validate --
        schedule_fa = emit.build_schedule_fa(rows, issuers, accounts, year)
        try:
            schema, _ = validate.load_schema(year=year)
            errors = validate.validate_schedule_fa(schedule_fa, schema)
            check("emitted ScheduleFA validates against the ITD schema",
                  not errors, "; ".join(errors[:2]))
        except validate.SchemaError:
            # The schema is not redistributed with the repo, so a fresh clone may not have
            # it. Everything else in this suite is self-contained and still runs.
            print("  SKIP  ITD schema not present -- see schemas/README.md")

        a3 = schedule_fa["DtlsForeignEquityDebtInterest"]
        check("one A3 row per computed holding", len(a3) == len(rows))
        check("every A3 country code is the string \"2\"",
              all(r["CountryCodeExcludingIndia"] == "2" for r in a3))
        check("every A3 money field is an int",
              all(isinstance(r[k], int) for r in a3 for k in
                  ("InitialValOfInvstmnt", "PeakBalanceDuringPeriod",
                   "ClosingBalance", "TotGrossAmtPaidCredited", "TotGrossProceeds")))
        check("A2 peak equals the sum of its holdings' peaks",
              all(
                  acc["PeakBalanceDuringPeriod"] == sum(
                      r.peak_value_inr for r in rows
                      if accounts[r.account_id].account_number == acc["AccountNumber"]
                  )
                  for acc in schedule_fa["DtlsForeignCustodialAcc"]
              ))

        # -- the prefill variant must carry the same row count --
        prefill = emit.to_prefill_format(schedule_fa)
        check("prefill format nests under lastFiledITR.scheduleFA",
              "dtlsForeignEquityDebtInterest"
              in prefill["lastFiledITR"]["scheduleFA"])
        check("prefill format keeps every row",
              len(prefill["lastFiledITR"]["scheduleFA"]
                  ["dtlsForeignEquityDebtInterest"]) == len(a3))

    # -- peak basis: the INR-maximising reading can never be lower --
    print("\n[peak basis]")
    usd_rows = positions.compute_rows(lots, transactions, 2025, prices, fx,
                                      peak_basis=positions.PEAK_BASIS_USD)
    inr_rows = positions.compute_rows(lots, transactions, 2025, prices, fx,
                                      peak_basis=positions.PEAK_BASIS_INR)
    by_uid_usd = {r.lot_id + str(r.acquire_date): r for r in usd_rows}
    check("inr basis is never lower than usd basis",
          all(
              r.peak_value_inr >= by_uid_usd[r.lot_id + str(r.acquire_date)].peak_value_inr
              for r in inr_rows
          ))

    # -- provenance: every figure names the export row it came from --
    # A disclosure schedule is only as defensible as its ability to answer "where did
    # this number come from?" long after the download folder is gone. The transactions
    # already carried source_file/source_row for error messages; these assert the trail
    # survives lot construction, apportionment and the audit CSV, which is the artefact
    # that outlives everything else.
    print("\n[provenance]")
    check("every lot names the row it was built from",
          all(l.source_ref for l in lots),
          str([l.uid for l in lots if not l.source_ref][:3]))
    check("a source reference is a basename and a line, not an absolute path",
          all(l.source_ref.startswith("transactions.csv:") for l in lots),
          str({l.source_ref for l in lots if "/" in l.source_ref}))

    prov_rows = positions.compute_rows(lots, transactions, 2025, prices, fx)
    check("every computed row carries its acquisition source",
          all(r.source_ref for r in prov_rows))
    with_proceeds = [r for r in prov_rows if r.proceeds_usd > 0]
    with_dividends = [r for r in prov_rows if r.dividends_usd > 0]
    check("the dataset exercises both apportioned figures",
          bool(with_proceeds) and bool(with_dividends),
          f"{len(with_proceeds)} rows with proceeds, "
          f"{len(with_dividends)} with dividends")
    check("a row with proceeds names the sale rows behind them",
          all(r.proceeds_source_refs for r in with_proceeds))
    check("a row with dividends names the dividend rows behind them",
          all(r.dividend_source_refs for r in with_dividends))
    check("a row with no proceeds claims no sale rows",
          all(not r.proceeds_source_refs
              for r in prov_rows if r.proceeds_usd == 0))
    check("source references are not repeated within a row",
          all(len(r.proceeds_source_refs) == len(set(r.proceeds_source_refs))
              and len(r.dividend_source_refs) == len(set(r.dividend_source_refs))
              for r in prov_rows))

    audit_path = os.path.join("/tmp", "itrprep_provenance_audit.csv")
    cli._write_audit(audit_path, prov_rows, 2025)
    with open(audit_path, newline="", encoding="utf-8") as fh:
        audit = list(csv.DictReader(fh))
    check("the audit CSV carries the provenance columns",
          all(c in (audit[0] if audit else {})
              for c in ("acquisition_source", "proceeds_sources",
                        "dividend_sources")),
          str(list(audit[0]) if audit else []))
    check("every audit row states where its acquisition was read from",
          bool(audit) and all(r["acquisition_source"] for r in audit))
    audit_by_lot = {(r["ticker"], r["acquire_date"]): r for r in audit}
    check("the audit CSV's sale sources match the computed row's",
          all(
              audit_by_lot[(r.ticker, r.acquire_date.isoformat())]["proceeds_sources"]
              == "; ".join(r.proceeds_source_refs)
              for r in prov_rows
          ))
    os.remove(audit_path)

    # -- adapters must reproduce the hand-written intermediate file --
    print("\n[stage 1 adapters]")
    et, _ = adapters.normalize(
        os.path.join(SYNTH, "broker_exports", "etrade_benefit_history.csv"),
        "etrade", "etrade_stockplan",
    )
    check("etrade adapter skips preamble and totals rows", len(et) == 7,
          f"got {len(et)}")
    check("etrade adapter classified two sales",
          sum(1 for t in et if t.txn_type == TXN_SELL) == 2)
    check("etrade adapter parsed $ and thousands separators",
          any(t.price_usd == Decimal("48.53") for t in et)          # "$48.53"
          and any(t.amount_usd == Decimal("2426.50") for t in et))  # "$2,426.50"
    check("etrade adapter read MM/DD/YYYY correctly",
          any(t.date == dt.date(2024, 8, 15) for t in et))

    im, _ = adapters.normalize(
        os.path.join(SYNTH, "broker_exports", "indmoney_transactions.csv"),
        "indmoney", "indmoney_us",
    )
    check("indmoney adapter read all 9 rows", len(im) == 9, f"got {len(im)}")
    check("indmoney adapter found 4 dividends",
          sum(1 for t in im if t.txn_type == TXN_DIVIDEND) == 4)
    check("indmoney adapter captured withholding tax",
          any(t.tax_withheld_usd == Decimal("17.01") for t in im))

    # -- same-day multi-sell must not inflate cost basis --
    # Real bug, found via a live filing: two SELL transactions sharing one
    # (account, ticker, date) each re-matched the SAME day's lot.disposals (which
    # carry no link back to which transaction caused them), so cost got summed once
    # per transaction sharing the key instead of once total. Proceeds happened to
    # still look plausible (prorated per-transaction), which is what let it hide.
    # Two lots (cost 100 and 200), two same-day sells of 5 shares each (10 total,
    # exactly draining both lots): true cost is 5*100 + 5*200 = 1500, not 3000.
    multi_sell_txns = [
        Transaction("acct", "ZZZ", TXN_BUY, dt.date(2024, 1, 1),
                    quantity=Decimal(5), price_usd=Decimal(100)),
        Transaction("acct", "ZZZ", TXN_BUY, dt.date(2024, 2, 1),
                    quantity=Decimal(5), price_usd=Decimal(200)),
        Transaction("acct", "ZZZ", TXN_SELL, dt.date(2025, 6, 1),
                    quantity=Decimal(5), price_usd=Decimal(300)),
        Transaction("acct", "ZZZ", TXN_SELL, dt.date(2025, 6, 1),
                    quantity=Decimal(5), price_usd=Decimal(300)),
    ]
    multi_sell_lots = positions.build_lots(multi_sell_txns)
    multi_sell_totals = positions.compute_year_totals(
        multi_sell_lots, multi_sell_txns, 2025, fx
    )
    rate1, _ = fx.rate_on(positions._rule115_specified_date(dt.date(2024, 1, 1)))
    rate2, _ = fx.rate_on(positions._rule115_specified_date(dt.date(2024, 2, 1)))
    expected_cost_inr = (
        positions.to_inr_int(Decimal(5) * Decimal(100) * rate1)
        + positions.to_inr_int(Decimal(5) * Decimal(200) * rate2)
    )
    got_cost_inr = multi_sell_totals.stcg_cost_inr
    check("same-day multi-sell cost basis is not multiplied by sell count",
          got_cost_inr == expected_cost_inr,
          f"expected {expected_cost_inr}, got {got_cost_inr} "
          f"(2x would be {expected_cost_inr * 2})")

    # -- Schedule CG FX uses the specified date, not per-date rates --
    # Rule 115(2) of the Income-tax Rules, 1962 specifies "the last day of the month
    # immediately preceding" as the conversion date for both capital gains (sub-clause
    # (f)) and dividend income (sub-clause (e)); rule 206 of the Income-tax Rules, 2026
    # restates the same convention as a table (Sl. Nos. 6 and 5) from tax year 2026-27,
    # so the function is right for both Acts. Confirmed against a real broker's own
    # tax report, whose displayed per-leg exchange rate matched this specified date, not
    # the transaction's own date. Schedule FA is NOT affected -- it is separately, and
    # differently, pinned to per-date rates by the ITD's own step-by-step guide.
    check("the specified date is the last day of the PRECEDING month",
          positions._rule115_specified_date(dt.date(2024, 8, 2)) == dt.date(2024, 7, 31))
    check("the specified date handles a January acquisition (year rollback)",
          positions._rule115_specified_date(dt.date(2024, 1, 15)) == dt.date(2023, 12, 31))

    rule115_txns = [
        Transaction("acct", "YYY", TXN_BUY, dt.date(2024, 8, 2),
                    quantity=Decimal(1), price_usd=Decimal(100)),
        Transaction("acct", "YYY", TXN_SELL, dt.date(2025, 6, 15),
                    quantity=Decimal(1), price_usd=Decimal(150)),
    ]
    rule115_lots = positions.build_lots(rule115_txns)
    rule115_totals = positions.compute_year_totals(rule115_lots, rule115_txns, 2025, fx)
    expected_cost_rate, _ = fx.rate_on(dt.date(2024, 7, 31))
    expected_sale_rate, _ = fx.rate_on(dt.date(2025, 5, 31))
    check("Schedule CG cost uses the specified date, not the acquisition date",
          rule115_totals.stcg_cost_inr
          == positions.to_inr_int(Decimal(100) * expected_cost_rate),
          f"got {rule115_totals.stcg_cost_inr}")
    check("Schedule CG proceeds use the specified date, not the sale date",
          rule115_totals.stcg_proceeds_inr
          == positions.to_inr_int(Decimal(150) * expected_sale_rate),
          f"got {rule115_totals.stcg_proceeds_inr}")

    # -- error paths must be loud, not silent --
    print("\n[error handling]")
    for label, rows_csv in (
        ("oversold position is rejected",
         "account_id,ticker,txn_type,date,quantity,price_usd,amount_usd,"
         "tax_withheld_usd,acq_kind,lot_id,notes\n"
         "a,CSCO,BUY,2025-01-02,10,100,1000,,,,\n"
         "a,CSCO,SELL,2025-06-02,20,150,3000,,,,\n"),
        ("sale with no matching acquisition is rejected",
         "account_id,ticker,txn_type,date,quantity,price_usd,amount_usd,"
         "tax_withheld_usd,acq_kind,lot_id,notes\n"
         "a,CSCO,SELL,2025-06-02,20,150,3000,,,,\n"),
    ):
        path = os.path.join("/tmp", "itrprep_err.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(rows_csv)
        try:
            positions.build_lots(intermediate.read_transactions(path))
            check(label, False, "no error raised")
        except Exception:
            check(label, True)

    for label, rows_csv in (
        ("bad txn_type is rejected",
         "account_id,ticker,txn_type,date,quantity,price_usd,amount_usd,"
         "tax_withheld_usd,acq_kind,lot_id,notes\n"
         "a,CSCO,TRANSFER,2025-01-02,10,100,1000,,,,\n"),
        ("negative quantity is rejected",
         "account_id,ticker,txn_type,date,quantity,price_usd,amount_usd,"
         "tax_withheld_usd,acq_kind,lot_id,notes\n"
         "a,CSCO,BUY,2025-01-02,-10,100,1000,,,,\n"),
        ("unparseable date is rejected",
         "account_id,ticker,txn_type,date,quantity,price_usd,amount_usd,"
         "tax_withheld_usd,acq_kind,lot_id,notes\n"
         "a,CSCO,BUY,not-a-date,10,100,1000,,,,\n"),
        ("missing column is rejected",
         "account_id,ticker,txn_type,date\na,CSCO,BUY,2025-01-02\n"),
    ):
        path = os.path.join("/tmp", "itrprep_err2.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(rows_csv)
        try:
            intermediate.read_transactions(path)
            check(label, False, "no error raised")
        except Exception:
            check(label, True)

    print()
    if failures:
        print(f"FAILED -- {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All pipeline checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
