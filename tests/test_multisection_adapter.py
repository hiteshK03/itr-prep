"""Checks for multi-section broker exports, and for the row that must never vanish.

The bug these cover cost a real filing. `normalize` located ONE header row and zipped it
against every later row, but an E*TRADE / StockPlan Connect "Benefit History" is
multi-section: one block per plan type or grant, each with its own header, column order and
width. So every row after the first block was either

  - silently discarded, because the cell under "Vest Date" held a plan name, or
  - silently mis-columned, because `dict(zip(headers, row))` truncated a wider row -- a
    vest of 42 shares issued / 13 withheld / 29 net at $124.12 arrived as 42 shares at
    $13, with the tax-withholding share count read as the price.

Against `tests/synthetic/broker_exports/etrade_benefit_history_multisection.csv`, the
pre-fix adapter produced 2 transactions out of 8 and warned about neither drop. That is the
shape that understated a real Schedule FA: 2 rows out of 173, with a Rs 10,00,000 per
assessment year exposure under Black Money Act s.43 behind it.

So the properties asserted here are:

  - every section's columns are resolved separately, and every row is imported
  - a wider later section is read against its OWN header
  - a quantity column that is present but zero ("Sellable Quantity" for a vest already
    sold to cover) cannot beat a populated one
  - gross, withheld and net stay three different numbers
  - a sell-to-cover vest is an acquisition AND a disposal, and the disposal comes out of
    the lot that vest created
  - a row that cannot be read is counted, named and loud

Run:  .venv/bin/python tests/test_multisection_adapter.py
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import adapters, doctor, intermediate, positions  # noqa: E402
from itrprep.fx import FxRates  # noqa: E402
from itrprep.models import (  # noqa: E402
    DISPOSAL_TAX_WITHHOLDING,
    TXN_BUY,
    TXN_DIVIDEND,
    TXN_SELL,
    Transaction,
)
from itrprep.prices import PriceStore  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNTH = os.path.join(ROOT, "tests", "synthetic")
EXPORTS = os.path.join(SYNTH, "broker_exports")
MULTI = os.path.join(EXPORTS, "etrade_benefit_history_multisection.csv")
UNREADABLE = os.path.join(EXPORTS, "etrade_benefit_history_unreadable.csv")
FX_CACHE = os.path.join(ROOT, "data", "sbi_ttbuy_usd.csv")
PRICE_CACHE = os.path.join(ROOT, "data", "prices")
# The interpreter running this suite, not a guessed one. `.venv/bin/python` is a
# POSIX venv layout that does not exist on Windows and does not exist at all on a
# fresh clone, which is what CI is.
PYTHON = sys.executable

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def work_paths(work: str) -> dict:
    return {
        "transactions": os.path.join(work, "transactions.csv"),
        "issuers": os.path.join(work, "issuers.csv"),
        "accounts": os.path.join(work, "accounts.csv"),
        "cash": os.path.join(work, "cash_balances.csv"),
        "overrides": os.path.join(work, "prices_override.csv"),
    }


def acquisitions(txns):
    return [t for t in txns if t.txn_type == TXN_BUY]


def disposals(txns):
    return [t for t in txns if t.txn_type == TXN_SELL]


def one(txns, day: dt.date, txn_type: str):
    hits = [t for t in txns if t.date == day and t.txn_type == txn_type]
    return hits[0] if len(hits) == 1 else None


# -- per-section headers -----------------------------------------------------

def test_every_section_is_read() -> None:
    print("\nmulti-section: every block is mapped on its own header")
    result = adapters.normalize_report(MULTI, "etrade", "etrade_stockplan")
    check("all four sections are found", len(result.sections) == 4,
          f"got {len(result.sections)}")
    check("no row is dropped", not result.dropped,
          "; ".join(w for _s, _l, w in result.dropped))
    check("every data row is imported, ignored as boilerplate, or reported dropped",
          all(s.accounted_for for s in result.sections),
          str([(s.header_line, len(s.rows), s.consumed, len(s.ignored),
                len(s.dropped)) for s in result.sections]))
    check("each section resolved its own date column",
          [s.column(adapters.C_DATE) for s in result.sections]
          == ["Vest Date", "Vest Date", "Purchase Date", "Settlement Date"],
          str([s.column(adapters.C_DATE) for s in result.sections]))
    check("the section titles are carried, so a warning can name the block",
          [s.title for s in result.sections][1:3]
          == ["Restricted Stock Units - Net Share Settlement",
              "Employee Stock Purchase Plan"],
          str([s.title for s in result.sections]))

    txns = result.transactions
    check("all six acquisitions are imported", len(acquisitions(txns)) == 6,
          f"got {len(acquisitions(txns))}: "
          + ", ".join(f"{t.date} {t.quantity}" for t in acquisitions(txns)))
    check("the gross share count across the file is 139",
          sum((t.quantity for t in acquisitions(txns)), Decimal(0)) == Decimal(139),
          str(sum((t.quantity for t in acquisitions(txns)), Decimal(0))))
    check("both tax-withholding disposals are imported",
          [t.quantity for t in disposals(txns)] == [Decimal(13), Decimal(8)],
          str([t.quantity for t in disposals(txns)]))
    check("the net-settlement block reads 2 rows as 4 transactions",
          result.sections[1].consumed == 2 and result.sections[1].imported == 4,
          f"{result.sections[1].consumed} rows, {result.sections[1].imported} txns")


def test_wider_section_is_not_misread() -> None:
    """The 42-shares-at-$13 case: a wider later block read against the first block."""
    print("\nmulti-section: a wider later section keeps its own column positions")
    txns, _ = adapters.normalize(MULTI, "etrade", "etrade_stockplan")
    vest = one(txns, dt.date(2025, 6, 16), TXN_BUY)
    check("the vest survives as an acquisition at all", vest is not None)
    check("its quantity is the gross 42 shares",
          vest is not None and vest.quantity == Decimal(42),
          str(vest.quantity) if vest else "missing")
    check("its price is the $124.12 FMV, not the 13 withheld shares",
          vest is not None and vest.price_usd == Decimal("124.12"),
          str(vest.price_usd) if vest else "missing")
    sale = one(txns, dt.date(2025, 6, 16), TXN_SELL)
    check("the same row's disposal is the 13 withheld shares, not all 42",
          sale is not None and sale.quantity == Decimal(13),
          str(sale.quantity) if sale else "missing")


def test_reordered_section_headers() -> None:
    print("\nmulti-section: a later section may reorder its columns")
    txns, _ = adapters.normalize(MULTI, "etrade", "etrade_stockplan")
    # Sections 3 and 4 put the date first, where sections 1 and 2 put the symbol first.
    espp = one(txns, dt.date(2025, 6, 30), TXN_BUY)
    deposit = one(txns, dt.date(2025, 8, 15), TXN_BUY)
    check("the date-first ESPP section parses its date", espp is not None)
    check("and its ticker, from a different column position",
          espp is not None and espp.ticker == "CSCO")
    check("the date-first share-deposit section parses too", deposit is not None)
    check("and reads its own price column ('Market Value')",
          deposit is not None and deposit.price_usd == Decimal("66.20"),
          str(deposit.price_usd) if deposit else "missing")


def test_sellable_quantity_cannot_win() -> None:
    print("\naliases: a present-but-zero quantity column cannot beat a populated one")
    check("'Sellable Quantity' is not an acquisition-quantity alias",
          not any(adapters._norm(a) == "sellable quantity"
                  for a in adapters.ETRADE.quantity_aliases))
    check("but it is still detection evidence for E*TRADE",
          "sellable quantity" in adapters.SIGNATURE_HEADERS["etrade"])
    result = adapters.normalize_report(MULTI, "etrade", "etrade_stockplan")
    espp_section = result.sections[2]
    check("the ESPP section binds no column to gross quantity",
          adapters.C_QTY not in espp_section.mapping,
          str(espp_section.mapping))
    check("it uses 'Net Shares' instead",
          espp_section.column(adapters.C_NET) == "Net Shares")
    espp = one(result.transactions, dt.date(2025, 6, 30), TXN_BUY)
    check("so the vest sold to cover is imported at 22 shares, not skipped at 0",
          espp is not None and espp.quantity == Decimal(22),
          str(espp.quantity) if espp else "missing")
    check("and the run says the figure is a floor, because gross was assumed to be net",
          any("gross was taken to equal net" in w for w in result.warnings),
          "; ".join(result.warnings))


def test_new_row_types_are_classified() -> None:
    print("\nclassification: row types that used to return None")
    for text, expected in (
        ("Lapse", TXN_BUY),
        ("Distribution", TXN_BUY),
        ("Share Deposit", TXN_BUY),
        ("Shares Deposited", TXN_BUY),
        ("Restricted Stock Release", TXN_BUY),
        ("ESPP Purchase", TXN_BUY),
        ("Sale", TXN_SELL),
        ("ESPP Sale", TXN_SELL),
        ("Cash Dividend", TXN_DIVIDEND),
        ("Cash Distribution", TXN_DIVIDEND),
        ("Vest and Sell to Cover", adapters.KIND_ACQUIRE_AND_DISPOSE),
        ("Exercise and Sell", adapters.KIND_ACQUIRE_AND_DISPOSE),
        ("Net Share Settlement", adapters.KIND_ACQUIRE_AND_DISPOSE),
    ):
        got = adapters._classify(adapters._norm(text), adapters.ETRADE)
        check(f"{text!r} classifies as {expected}", got == expected, f"got {got}")
    check("an unknown type still returns None, for the caller to report loudly",
          adapters._classify("corporate action adjustment", adapters.ETRADE) is None)

    txns, _ = adapters.normalize(MULTI, "etrade", "etrade_stockplan")
    for label, day, qty in (
        ("Lapse", dt.date(2025, 5, 15), Decimal(18)),
        ("Distribution", dt.date(2025, 7, 15), Decimal(25)),
        ("Share Deposit", dt.date(2025, 8, 15), Decimal(12)),
    ):
        txn = one(txns, day, TXN_BUY)
        check(f"a {label} row is imported as an acquisition of {qty}",
              txn is not None and txn.quantity == qty,
              str(txn.quantity) if txn else "missing")
    check("acq_kind is inferred per row, which is what doctor recognises a plan by",
          {t.acq_kind for t in acquisitions(txns)} == {"RSU_VEST", "ESPP"},
          str({t.acq_kind for t in acquisitions(txns)}))


# -- gross / withheld / net --------------------------------------------------

def test_sell_to_cover_is_both_legs() -> None:
    print("\nsell to cover: one row, one acquisition and one disposal")
    txns, _ = adapters.normalize(MULTI, "etrade", "etrade_stockplan")
    vest = one(txns, dt.date(2025, 6, 16), TXN_BUY)
    sale = one(txns, dt.date(2025, 6, 16), TXN_SELL)
    check("the acquisition is the GROSS count, which s.17(2)(vi) charges on",
          vest is not None and vest.quantity == Decimal(42))
    check("the disposal is the withheld count",
          sale is not None and sale.quantity == Decimal(13))
    check("net shares are what remains, and are not double counted",
          vest is not None and sale is not None
          and vest.quantity - sale.quantity == Decimal(29))
    check("the disposal is marked as withholding, so it binds to its own vest",
          sale is not None and sale.disposal_kind == DISPOSAL_TAX_WITHHOLDING)
    check("both legs carry the same lot label",
          vest is not None and sale is not None and vest.lot_id == sale.lot_id
          == "GRANT-2024-08")
    check("the disposal's proceeds are valued at the vest FMV",
          sale is not None and sale.amount_usd == Decimal("124.12") * Decimal(13),
          str(sale.amount_usd) if sale else "missing")

    lots = positions.build_lots(txns)
    vest_lot = [l for l in lots if l.acquire_date == dt.date(2025, 6, 16)]
    check("build_lots creates one lot for the gross acquisition", len(vest_lot) == 1)
    check("and it holds 29 shares after the withholding",
          bool(vest_lot) and vest_lot[0].qty_on(dt.date(2025, 12, 31)) == Decimal(29),
          str(vest_lot[0].qty_on(dt.date(2025, 12, 31))) if vest_lot else "no lot")
    check("its initial cost is the gross 42 shares at the vest FMV",
          bool(vest_lot) and vest_lot[0].cost_usd == Decimal(42) * Decimal("124.12"))


def test_withholding_comes_out_of_its_own_vest() -> None:
    """E*TRADE stamps one grant number on every vest of an award, so lot_id is ambiguous."""
    print("\nsell to cover: the withheld shares leave the lot that vest created")
    txns = [
        Transaction("et", "CSCO", TXN_BUY, dt.date(2025, 2, 15), quantity=Decimal(40),
                    price_usd=Decimal(60), lot_id="GRANT-2023-08"),
        Transaction("et", "CSCO", TXN_BUY, dt.date(2025, 5, 15), quantity=Decimal(42),
                    price_usd=Decimal(124), lot_id="GRANT-2023-08"),
        Transaction("et", "CSCO", TXN_SELL, dt.date(2025, 5, 15), quantity=Decimal(13),
                    price_usd=Decimal(124), lot_id="GRANT-2023-08",
                    disposal_kind=DISPOSAL_TAX_WITHHOLDING),
    ]
    lots = positions.build_lots(txns)
    older = [l for l in lots if l.acquire_date == dt.date(2025, 2, 15)][0]
    newer = [l for l in lots if l.acquire_date == dt.date(2025, 5, 15)][0]
    check("the earlier vest of the same grant is untouched",
          older.qty_on(dt.date(2025, 12, 31)) == Decimal(40),
          str(older.qty_on(dt.date(2025, 12, 31))))
    check("the vesting lot loses exactly the withheld shares",
          newer.qty_on(dt.date(2025, 12, 31)) == Decimal(29),
          str(newer.qty_on(dt.date(2025, 12, 31))))

    orphan = [
        txns[0],
        Transaction("et", "CSCO", TXN_SELL, dt.date(2025, 6, 20), quantity=Decimal(5),
                    price_usd=Decimal(124), disposal_kind=DISPOSAL_TAX_WITHHOLDING),
    ]
    try:
        positions.build_lots(orphan)
        check("a withholding disposal with no vest on its date is refused", False,
              "no error raised")
    except Exception as exc:
        check("a withholding disposal with no vest on its date is refused",
              "TAX_WITHHOLDING" in str(exc), str(exc)[:120])


def test_disposal_kind_survives_the_csv() -> None:
    print("\nintermediate CSV: disposal_kind round-trips")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "transactions.csv")
        txns, _ = adapters.normalize(MULTI, "etrade", "etrade_stockplan")
        intermediate.write_transactions(path, txns)
        back = intermediate.read_transactions(path)
        check("the withholding disposals are still marked after a write/read",
              sorted(t.quantity for t in back if t.disposal_kind ==
                     DISPOSAL_TAX_WITHHOLDING) == [Decimal(8), Decimal(13)],
              str([str(t.quantity) for t in back if t.disposal_kind]))
        check("acq_kind survives too",
              {t.acq_kind for t in back if t.txn_type == TXN_BUY}
              == {"RSU_VEST", "ESPP"})
        check("and the file still reads with the documented required columns",
              len(back) == len(txns))

        # A file hand-filled before either optional column existed must keep loading.
        legacy = os.path.join(tmp, "legacy.csv")
        with open(path, newline="", encoding="utf-8") as src, \
                open(legacy, "w", newline="", encoding="utf-8") as dst:
            reader = csv.DictReader(src)
            fields = [c for c in reader.fieldnames
                      if c not in ("disposal_kind", "expense_usd")]
            writer = csv.DictWriter(dst, fieldnames=fields)
            writer.writeheader()
            for row in reader:
                writer.writerow({c: row[c] for c in fields})
        older = intermediate.read_transactions(legacy)
        check("a transactions.csv predating disposal_kind still reads",
              len(older) == len(txns))
        check("and its sells carry no disposal_kind",
              not any(t.disposal_kind for t in older))


def test_fully_withheld_vest_still_reports() -> None:
    """A lot acquired and fully disposed of on one day was still held during the year."""
    print("\nSchedule FA: a same-day full exit is reported, not dropped")
    txns = [
        Transaction("et", "CSCO", TXN_BUY, dt.date(2025, 5, 15), quantity=Decimal(10),
                    price_usd=Decimal(64), lot_id="GRANT-X"),
        Transaction("et", "CSCO", TXN_SELL, dt.date(2025, 5, 15), quantity=Decimal(10),
                    price_usd=Decimal(64), lot_id="GRANT-X",
                    disposal_kind=DISPOSAL_TAX_WITHHOLDING),
    ]
    lots = positions.build_lots(txns)
    rows = positions.compute_rows(
        lots, txns, 2025, PriceStore(PRICE_CACHE, offline=True), FxRates.load(FX_CACHE)
    )
    check("the lot still produces a Schedule FA row", len(rows) == 1,
          f"got {len(rows)}")
    check("its initial value is the acquisition, not nil",
          bool(rows) and rows[0].initial_value_inr > 0)
    check("its closing balance is nil", bool(rows) and rows[0].closing_value_inr == 0)
    check("the peak is taken at the acquisition quantity",
          bool(rows) and rows[0].peak_qty == Decimal(10),
          str(rows[0].peak_qty) if rows else "no row")
    check("and the substitution is stated in the audit trail",
          bool(rows) and any("same day" in n for n in rows[0].notes),
          str(rows[0].notes) if rows else "no row")


# -- loudness ----------------------------------------------------------------

def test_unreadable_rows_are_loud() -> None:
    print("\nloudness: a row that cannot be read is counted, named and blocking")
    result = adapters.normalize_report(UNREADABLE, "etrade", "etrade_stockplan")
    check("the two unreadable rows are counted", len(result.dropped) == 2,
          str([(l, w) for _s, l, w in result.dropped]))
    check("the totals line is NOT counted as a drop",
          sum(len(s.ignored) for s in result.sections) == 1)
    check("the first warning is the census, so a truncated view still shows it",
          bool(result.warnings) and "were NOT imported" in result.warnings[0],
          result.warnings[0] if result.warnings else "no warnings")
    check("the census names the penalty that makes this matter",
          bool(result.warnings) and "s.43" in result.warnings[0])
    rendered = adapters.render_report(result)
    check("the report names the line of every dropped row",
          "DROPPED line 6" in rendered and "DROPPED line 7" in rendered, rendered)
    check("and says why each one was dropped",
          "Corporate Action Adjustment" in rendered and "Unvested" in rendered)
    check("the unreadable-date reason points at the section layout",
          "laid out differently" in rendered)

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "transactions.csv")
        proc = subprocess.run(
            [PYTHON, "-m", "itrprep.cli", "normalize", "--broker", "etrade",
             "--input", UNREADABLE, "--account-id", "etrade_stockplan", "--out", out],
            capture_output=True, text=True, cwd=ROOT,
        )
        check("normalize exits non-zero when rows were dropped", proc.returncode == 1,
              f"rc={proc.returncode}")
        check("with a banner, not one quiet line", "!" * 78 in proc.stdout)
        check("that names the count", "2 ROW(S) COULD NOT BE IMPORTED" in proc.stdout,
              proc.stdout[-500:])
        check("and offers the explicit override rather than hiding it",
              "--allow-dropped-rows" in proc.stdout)
        check("the partial file is still written, so the rows can be hand-added",
              os.path.exists(out))
        allowed = subprocess.run(
            [PYTHON, "-m", "itrprep.cli", "normalize", "--broker", "etrade",
             "--input", UNREADABLE, "--account-id", "etrade_stockplan", "--out", out,
             "--allow-dropped-rows"],
            capture_output=True, text=True, cwd=ROOT,
        )
        check("--allow-dropped-rows is the only way past it",
              allowed.returncode == 0, f"rc={allowed.returncode}")

    clean = adapters.normalize_report(MULTI, "etrade", "etrade_stockplan")
    check("a complete parse raises no census warning at all",
          not any("were NOT imported" in w for w in clean.warnings))


def test_rows_above_the_first_header_are_reported() -> None:
    """A row no header governs cannot be read, but it must not vanish either."""
    print("\nloudness: a data row above the first header row")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "stray.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("CSCO,Release,06/16/2025,42,124.12\n"
                     "Symbol,Transaction Type,Vest Date,Quantity,Vest Date FMV\n"
                     "CSCO,Release,07/15/2025,25,130.05\n")
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        check("the governed row is imported", len(result.transactions) == 1)
        check("the stray row is reported as dropped, not swallowed",
              len(result.dropped) == 1, str(result.dropped))
        check("and the reason says where it sits",
              bool(result.dropped) and "above the first header row" in result.dropped[0][2],
              result.dropped[0][2] if result.dropped else "")


def test_row_type_beats_the_file_level_acq_kind() -> None:
    """--acq-kind is per file; a multi-section export mixes plan types within one."""
    print("\nacq_kind: the row's own type wins over the file-level flag")
    txns, _ = adapters.normalize(MULTI, "etrade", "etrade_stockplan",
                                 acq_kind="RSU_VEST")
    espp = one(txns, dt.date(2025, 6, 30), TXN_BUY)
    check("the ESPP section's row is still ESPP, not the flag's RSU_VEST",
          espp is not None and espp.acq_kind == "ESPP",
          espp.acq_kind if espp else "missing")
    vest = one(txns, dt.date(2025, 4, 15), TXN_BUY)
    check("a row that states a vest is RSU_VEST",
          vest is not None and vest.acq_kind == "RSU_VEST")
    check("and the flag still governs rows that say nothing",
          adapters._acq_kind("", adapters.ETRADE, "OPEN_MARKET") == "OPEN_MARKET")


def test_a_sale_section_is_dated_at_the_sale() -> None:
    """A block with both dates must date the row at the disposal, not the acquisition."""
    print("\naliases: 'Date Sold' outranks 'Date Acquired' in one section")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "gl.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Symbol,Transaction Type,Date Acquired,Date Sold,"
                     "Shares Sold,Sale Price,Grant Number\n"
                     "CSCO,Sale,06/16/2025,11/20/2025,10,75.44,GRANT-2024-08\n")
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        check("the section binds the sale date", result.sections[0].column("date")
              == "Date Sold", result.sections[0].column("date"))
        check("no row is dropped", not result.dropped, str(result.dropped))
        sale = result.transactions[0]
        check("the disposal falls in the year it was sold",
              sale.date == dt.date(2025, 11, 20), sale.date.isoformat())
        check("at the quantity sold", sale.quantity == Decimal(10))


def test_single_section_exports_are_unchanged() -> None:
    """The three working paths must not regress: same rows, same numbers."""
    print("\nregression: single-section exports parse exactly as before")
    et, _ = adapters.normalize(
        os.path.join(EXPORTS, "etrade_benefit_history.csv"), "etrade", "etrade_stockplan"
    )
    check("etrade: still 7 transactions", len(et) == 7, f"got {len(et)}")
    check("etrade: still two sales",
          sum(1 for t in et if t.txn_type == TXN_SELL) == 2)
    check("etrade: no phantom withholding disposals appear",
          not any(t.disposal_kind for t in et))
    check("etrade: prices and amounts unchanged",
          any(t.price_usd == Decimal("48.53") for t in et)
          and any(t.amount_usd == Decimal("2426.50") for t in et))
    check("etrade: quantities unchanged",
          sorted(t.quantity for t in et) == sorted(
              Decimal(q) for q in (50, 40, 35, 22, 30, 40, 25)))

    fid, _ = adapters.normalize(
        os.path.join(EXPORTS, "fidelity_espp.csv"), "fidelity", "fidelity_espp"
    )
    check("fidelity: 8 transactions", len(fid) == 8, f"got {len(fid)}")
    check("fidelity: four dividends",
          sum(1 for t in fid if t.txn_type == TXN_DIVIDEND) == 4)
    check("fidelity: four ESPP purchases at their own prices",
          sorted(t.quantity for t in fid if t.txn_type == TXN_BUY)
          == sorted(Decimal(q) for q in (18, 15, 14, 12)))

    ind, _ = adapters.normalize(
        os.path.join(EXPORTS, "indmoney_transactions.csv"), "indmoney", "indmoney_us"
    )
    check("indmoney: still 9 transactions", len(ind) == 9, f"got {len(ind)}")
    check("indmoney: still 4 dividends",
          sum(1 for t in ind if t.txn_type == TXN_DIVIDEND) == 4)
    check("indmoney: withholding still captured",
          any(t.tax_withheld_usd == Decimal("17.01") for t in ind))
    check("indmoney: a retail buy is not mislabelled as an ESPP purchase",
          {t.acq_kind for t in ind if t.txn_type == TXN_BUY} == {"OPEN_MARKET"},
          str({t.acq_kind for t in ind if t.txn_type == TXN_BUY}))
    check("all three exports are still detected by content",
          [adapters.detect(os.path.join(EXPORTS, n)).broker for n in (
              "etrade_benefit_history.csv", "fidelity_espp.csv",
              "indmoney_transactions.csv", "etrade_benefit_history_multisection.csv")]
          == ["etrade", "fidelity", "indmoney", "etrade"])


# -- doctor ------------------------------------------------------------------

def _write_transactions(path: str, rows: list[str]) -> None:
    header = ("account_id,ticker,txn_type,date,quantity,price_usd,amount_usd,"
              "tax_withheld_usd,acq_kind,lot_id,notes\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        fh.writelines(r if r.endswith("\n") else r + "\n" for r in rows)


def _activity_warnings(work):
    report = doctor.run_checks(work_paths(work), years=[2025], prices=None,
                              fx_cache=FX_CACHE, offline=True)
    return report, [f for f in report.warnings if f.category == "account activity"]


def test_doctor_catches_a_starved_stock_plan_account() -> None:
    print("\ndoctor: a stock-plan account contributing almost nothing")
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        shutil.copytree(SYNTH, work)
        # The real shape: the employer plan account keeps 2 of the file's rows because
        # every later section of its export was dropped, while the retail account is
        # untouched. Both accounts still resolve, so the reference presence check is silent.
        rows = [
            "etrade_stockplan,CSCO,BUY,2025-02-15,40,64.87,2594.80,,RSU_VEST,"
            "CSCO-V-2025Q1,one of the two vests that survived the parser",
            "etrade_stockplan,CSCO,BUY,2025-11-20,30,75.44,2263.20,,RSU_VEST,"
            "CSCO-V-2025Q4,the other one",
        ]
        rows += [
            f"indmoney_us,IVV,BUY,2025-{month:02d}-{day:02d},2,600,1200,,OPEN_MARKET,"
            f"IVV-{month:02d}{day:02d},monthly SIP"
            for month in range(1, 13) for day in (5, 15, 25)
        ]
        _write_transactions(os.path.join(work, "transactions.csv"), rows)
        report, warned = _activity_warnings(work)
        check("the starved stock-plan account is warned about", bool(warned),
              "; ".join(f.message for f in report.warnings))
        check("only that one account is flagged", len(warned) == 1,
              "; ".join(f.message for f in warned))
        check("the account is named by id",
              bool(warned) and "etrade_stockplan" in warned[0].message)
        check("the acquisition count and the row share are both quantified",
              bool(warned) and "2 acquisition(s)" in warned[0].message
              and "%" in warned[0].message, warned[0].message if warned else "")
        check("the window with no acquisitions is named, which is where rows went",
              bool(warned) and "2025-02-15 to 2025-11-20" in warned[0].message,
              warned[0].message if warned else "")
        check("the hint points back at the per-section census",
              bool(warned) and "census" in warned[0].hint)
        check("and at the figure to reconcile against",
              bool(warned) and "12BA" in warned[0].hint)
        check("it is a warning, not a build-blocking error",
              not any(f.category == "account activity" for f in report.errors))

        # The reference check this replaces stays silent on the same file, which is why
        # the original failure went unnoticed: both accounts do have transactions.
        unused = [f for f in report.warnings
                  if f.category == "accounts.csv" and "no transactions" in f.message]
        check("the pre-existing presence check does NOT fire on this shape",
              not any("etrade_stockplan" in f.message for f in unused))


def test_doctor_is_quiet_on_legitimately_small_accounts() -> None:
    print("\ndoctor: a legitimately small account does not trip the check")
    _report, warned = _activity_warnings(SYNTH)
    check("the synthetic dataset produces no activity warning", not warned,
          "; ".join(f.message for f in warned))

    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        shutil.copytree(SYNTH, work)
        # A semi-annual ESPP account alongside a busy retail account: 4 purchases in two
        # years is 2 a year, which is a real cadence, and it holds no RSU vests. A share
        # test alone would have fired on it; this must not.
        rows = [
            "fidelity_espp,JNJ,BUY,2024-06-28,14,124.24,1739.36,,ESPP,J1,",
            "fidelity_espp,JNJ,BUY,2024-12-31,12,122.93,1475.16,,ESPP,J2,",
            "fidelity_espp,JNJ,BUY,2025-06-30,13,150.00,1950.00,,ESPP,J3,",
            "fidelity_espp,JNJ,BUY,2025-12-31,11,160.00,1760.00,,ESPP,J4,",
        ]
        rows += [
            f"indmoney_us,IVV,BUY,2025-{month:02d}-{day:02d},2,600,1200,,OPEN_MARKET,"
            f"IVV-{month:02d}{day:02d},monthly SIP"
            for month in range(1, 13) for day in (5, 20)
        ]
        _write_transactions(os.path.join(work, "transactions.csv"), rows)
        _report2, warned2 = _activity_warnings(work)
        check("an ESPP-only account with a real cadence is not warned about",
              not warned2, "; ".join(f.message for f in warned2))


def main() -> int:
    test_every_section_is_read()
    test_wider_section_is_not_misread()
    test_reordered_section_headers()
    test_sellable_quantity_cannot_win()
    test_new_row_types_are_classified()
    test_sell_to_cover_is_both_legs()
    test_withholding_comes_out_of_its_own_vest()
    test_disposal_kind_survives_the_csv()
    test_fully_withheld_vest_still_reports()
    test_unreadable_rows_are_loud()
    test_rows_above_the_first_header_are_reported()
    test_row_type_beats_the_file_level_acq_kind()
    test_a_sale_section_is_dated_at_the_sale()
    test_single_section_exports_are_unchanged()
    test_doctor_catches_a_starved_stock_plan_account()
    test_doctor_is_quiet_on_legitimately_small_accounts()

    print()
    if failures:
        print(f"FAILED -- {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All multi-section adapter / gross-net / loudness checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
