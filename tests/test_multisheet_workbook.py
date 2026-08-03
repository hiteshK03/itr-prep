"""Checks for multi-SHEET workbooks, and for what an acquisition is actually worth.

Two defects, both of which understated a real Schedule FA, both silent.

`_xlsx_first_sheet` resolved the first worksheet and stopped, so `read_table` returned
sheet 1 and every other sheet was discarded with no warning at all. A real E*TRADE
"By Benefit Type" export has an `ESPP` sheet and a `Restricted Stock` sheet; the whole
second sheet went missing, and with it an entire RSU vest -- both the shares acquired and
the shares sold to cover the withholding tax on them. A sheet is semantically what a
section is: its own header, its own column order, its own width. So every sheet is read,
mapped on its own header, and named in the census with its row count, whether or not
anything came out of it.

`price_aliases` then ranked "Purchase Price" above "Purchase Date FMV", so an ESPP lot was
priced at what was PAID rather than at fair market value. Where a perquisite has been
charged -- s.73(1) with s.17(1)(d) of the Income-tax Act, 2025, s.49(2AA) with
s.17(2)(vi) of the 1961 Act -- the cost of acquisition is the FMV
that perquisite was computed on. The ESPP discount is already taxed as salary through
Form 16, so pricing the lot at the discounted figure taxes the same discount a second time
as a capital gain.

The fixture built here mirrors the real export's shape -- two sheets, the trailing-colon
column names, the nested Grant / Vest Schedule / Tax Withholding / Sellable Shares records,
the repeated column names ("Sellable Qty." three times, "Granted Qty." twice), the unvested
tranches -- with neutral tickers and its own figures.

Run:  .venv/bin/python tests/test_multisheet_workbook.py
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import make_xlsx_fixture  # noqa: E402

from itrprep import adapters, intermediate, positions  # noqa: E402
from itrprep.models import (  # noqa: E402
    DISPOSAL_TAX_WITHHOLDING,
    TXN_BUY,
    TXN_SELL,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS = os.path.join(ROOT, "tests", "synthetic", "broker_exports")
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


def acquisitions(txns):
    return [t for t in txns if t.txn_type == TXN_BUY]


def disposals(txns):
    return [t for t in txns if t.txn_type == TXN_SELL]


def one(txns, day: dt.date, txn_type: str):
    hits = [t for t in txns if t.date == day and t.txn_type == txn_type]
    return hits[0] if len(hits) == 1 else None


def rows_of(txns):
    return [(t.txn_type, t.date.isoformat(), t.quantity, t.price_usd,
             t.acq_kind or t.disposal_kind)
            for t in sorted(txns, key=lambda x: (x.date, x.txn_type))]


# -- the real export's shape, with neutral tickers ---------------------------
#
# Both header rows are the real ones, trailing colons and duplicate names included: the
# duplicates are the reason columns must be resolved by index, and the trailing colon is
# the reason "Est. Cost Basis (per share)" alone would not have matched.

ESPP_HEADER = [
    "Record Type", "Symbol", "Purchase Date", "Purchase Price", "Purchased Qty.",
    "Tax Collection Shares", "Net Shares", "Sellable Qty.", "Expected Gain/Loss",
    "Est. Market Value", "Grant Date", "Pending Sale Qty.", "Blocked Qty.",
    "Transferable Date", "First Sellable Date", "Discount Percent", "Grant Date FMV",
    "Purchase Date FMV", "Est. Cost Basis (per share):",
    "Est. Taxable Gain/Loss (per share):", "Tax Status", "Blocked", "Blocked Type",
    "Contribution Source", "Original Grant Number",
]


def _espp_row(purchase_date, paid, qty, withheld, net, sellable, grant_date,
              transferable, grant_fmv, purchase_fmv, market_value):
    return ["Purchase", "CSCO", purchase_date, paid, qty, withheld, net, sellable,
            "150.00", market_value, grant_date, "0", "", transferable, "NA", "15%",
            f"${grant_fmv}", f"${purchase_fmv}", purchase_fmv, "7.28", "", "No", "",
            "Employee Contribution", ""]


# Paid is 15% off the lower of the two FMVs, as an ESPP with a lookback works. The
# grant-date FMV on the first row is ABOVE the purchase-date FMV on purpose: it is the
# wrong answer that sits one column to the left of the right one.
ESPP_ROWS = [
    ESPP_HEADER,
    _espp_row("09-MAY-2025", "41.225", "24", "3", "21", "21", "11-NOV-2024",
              "09-NOV-2026", "52.10", "48.50", "1018.50"),
    _espp_row("07-NOV-2025", "53.89", "19", "2", "17", "5", "12-MAY-2025",
              "07-MAY-2027", "64.96", "63.40", "317.00"),
    _espp_row("08-MAY-2026", "60.01", "11", "1", "10", "10", "10-NOV-2025",
              "08-NOV-2027", "70.60", "71.20", "712.00"),
    ["Totals", "", "", "", "", "", "", "36", "", "2047.50"],
]

RSU_HEADER = [
    "Record Type", "Symbol", "Grant Date", "Settlement Type", "Granted Qty.",
    "Withheld Qty.", "Vested Qty.", "Unvested Qty.", "Deferred / Pending Release Qty.",
    "Sellable Qty.", "Est. Market Value", "Grant Number", "Cancelled Qty.",
    "Pending Sale Qty.", "Blocked Qty.", "Type", "Class", "Status", "Vest Period",
    "Vest Date", "Deferred Until", "Granted Qty.", "Other Reason for cancelled qty",
    "Cancelled Qty.", "Date Cancelled", "Vested Qty.", "Released Qty", "Released Amount",
    "Sellable Qty.", "Blocked Qty.", "Blocked Share Qty.", "Total Taxes Paid",
    "Sellable Qty.", "Pending Sale Qty.", "Sellable Est. Market Value",
    "Est. Cost Basis (per share):", "Est. Taxable Gain/Loss (per share):", "Tax Status",
    "Shares Traded for taxes", "Tax Status", "Tax Description", "Taxable Gain",
    "Effective Tax Rate", "Withholding Amount", "Total Estimated Tax Withholding",
    "Dividend", "Dividend Record Date", "Dividend Payable Date", "Dividend Cancel Date",
    "Dividend Release Date", "Dividend Type", "Dividend Per Share",
    "Dividend Market Value", "Dividend Cash", "Dividend Share",
    "Release Dividend Shares", "Dividend Fractional Shares Remaining",
    "Dividend Market Value at Release", "Cash-in-Lieu", "Blocked", "Blocked Type",
    "Release Date", "Original Grant Number",
]


def _rsu_row(**cells):
    row = [""] * len(RSU_HEADER)
    for index, value in cells.items():
        row[int(index[1:])] = value
    return row


def _grant(symbol, grant_date, granted, vested, unvested, sellable, market, number,
           status=""):
    return _rsu_row(c0="Grant", c1=symbol, c2=grant_date, c3="Stock", c4=granted,
                    c6=vested, c7=unvested, c9=sellable, c10=market, c11=number,
                    c12="0", c13="0", c15="RSU", c16="A", c17=status)


def _vest(number, period, vest_date, granted, vested, released, sellable, taxes,
          traded, status):
    # "Withheld Qty." (c5) reads 0 while "Shares Traded for taxes" (c38) reads the real
    # count: this was a market sell-to-cover, not a net settlement. Both columns exist and
    # mean different things, and only one of them is populated on any given row.
    return _rsu_row(c0="Vest Schedule", c5="0", c11=number, c18=period, c19=vest_date,
                    c21=granted, c23="0", c25=vested, c26=released, c27="0",
                    c28=sellable, c29="0", c31=taxes, c38=traded, c39=status,
                    c55="0", c56="0", c57="0", c58="0")


def _withholding(number, period, description, gain, rate, amount):
    return _rsu_row(c0="Tax Withholding", c11=number, c18=period, c40=description,
                    c41=gain, c42=rate, c43=amount)


RSU_ROWS = [
    RSU_HEADER,
    _grant("CSCO", "15-AUG-2024", "200", "50", "150", "34", "12500.00", "RU100001"),
    _vest("RU100001", "1", "08/15/2025", "50", "50", "50", "34", "1070.40", "16",
          "Paid at Vest"),
    _withholding("RU100001", "1", "INDIA", "0", "0%", "0"),
    _withholding("RU100001", "1", "India-05.2", "0", "5.2%", "0"),
    _withholding("RU100001", "1", "India-31.2", "3345.00", "31.2%", "1070.40"),
    _vest("RU100001", "2", "08/15/2026", "50", "0", "0", "0", "0", "0", "Due at Vest"),
    _vest("RU100001", "3", "08/15/2027", "50", "0", "0", "0", "0", "0", "Due at Vest"),
    _vest("RU100001", "4", "08/15/2028", "50", "0", "0", "0", "0", "0", "Due at Vest"),
    # The tranche's per-share cost basis lives here, not on the vest row, tied to it by
    # grant number and vest period.
    _rsu_row(c0="Sellable Shares", c11="RU100001", c18="1", c31="0", c32="34", c33="0",
             c34="2274.60", c35="66.90", c36="0.00", c37="Short Term", c59="No",
             c61="15-AUG-2025"),
    _grant("CSCO", "15-AUG-2025", "80", "0", "80", "0", "5352.00", "RU100002",
           status="NO_ACTION_REQD"),
    _vest("RU100002", "1", "08/15/2026", "20", "0", "0", "0", "0", "0", "Due at Vest"),
    _vest("RU100002", "2", "11/15/2026", "20", "0", "0", "0", "0", "0", "Due at Vest"),
    _vest("RU100002", "3", "02/15/2027", "20", "0", "0", "0", "0", "0", "Due at Vest"),
    _vest("RU100002", "4", "05/15/2027", "20", "0", "0", "0", "0", "0", "Due at Vest"),
    _rsu_row(c0="Totals", c5="0", c7="230", c9="34", c10="17852.00"),
]

DISCLAIMER_ROWS = [
    ["Important information about this report"],
    ["Values shown are estimates and do not constitute tax advice."],
    ["Consult your tax adviser before relying on any figure in this report."],
    ["Term", "Meaning", "Notes"],
    ["FMV", "Fair market value", "Used to compute the taxable perquisite"],
    ["Sell to cover", "Shares sold at vest to fund withholding tax", "Reduces net shares"],
]


def benefit_workbook(directory: str, name: str = "ByBenefitType.xlsx",
                     sheets=None, hidden=()) -> str:
    path = os.path.join(directory, name)
    make_xlsx_fixture.build_workbook(
        path,
        sheets if sheets is not None
        else [("ESPP", ESPP_ROWS), ("Restricted Stock", RSU_ROWS)],
        hidden=hidden,
    )
    return path


# -- defect 1: every worksheet is read --------------------------------------

def test_every_worksheet_is_read() -> None:
    print("\nmulti-sheet: both worksheets of a By Benefit Type export are read")
    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(tmp)
        sheets = adapters.read_sheets(path)
        check("read_sheets returns both worksheets, in workbook order",
              [s.name for s in sheets] == ["ESPP", "Restricted Stock"],
              str([s.name for s in sheets]))
        check("read_table still flattens the whole workbook, not just sheet 1",
              any("Vest Schedule" in cell for row in adapters.read_table(path)
                  for cell in row))

        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        check("one section per sheet, each mapped on its own header",
              [s.sheet for s in result.sections] == ["ESPP", "Restricted Stock"],
              str([s.sheet for s in result.sections]))
        check("the ESPP sheet resolves its own date column",
              result.sections[0].column(adapters.C_DATE) == "Purchase Date",
              result.sections[0].column(adapters.C_DATE))
        check("the restricted-stock sheet resolves a different one",
              result.sections[1].column(adapters.C_DATE) == "Vest Date",
              result.sections[1].column(adapters.C_DATE))
        check("no row is dropped", not result.dropped,
              "; ".join(w for _s, _l, w in result.dropped))
        check("every row is imported, ignored as boilerplate, or reported dropped",
              all(s.accounted_for for s in result.sections),
              str([(s.sheet, len(s.rows), s.consumed, len(s.ignored),
                    len(s.dropped)) for s in result.sections]))

        census = {s.name: s for s in result.sheets}
        check("the census names both worksheets", sorted(census) ==
              ["ESPP", "Restricted Stock"], str(sorted(census)))
        check("with each one's row count, so a sheet cannot vanish unnoticed",
              (census["ESPP"].rows, census["Restricted Stock"].rows)
              == (len(ESPP_ROWS), len(RSU_ROWS)),
              str([(s.name, s.rows) for s in result.sheets]))
        rendered = adapters.render_report(result)
        check("and the rendered report names them too",
              "worksheet 1 'ESPP'" in rendered
              and "worksheet 2 'Restricted Stock'" in rendered, rendered)
        check("a dropped row would be named with its sheet, since line numbers restart",
              result.sections[1].label.startswith("sheet 'Restricted Stock' line "),
              result.sections[1].label)
        check("and so is the source of each transaction",
              all(t.source_file.endswith("[ESPP]")
                  or t.source_file.endswith("[Restricted Stock]")
                  for t in result.transactions),
              str({t.source_file for t in result.transactions}))


def test_the_whole_workbook_becomes_transactions() -> None:
    """The shape of the real file: three ESPP purchases and one vested RSU tranche."""
    print("\nmulti-sheet: every acquisition, each with its same-day withholding disposal")
    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(tmp)
        txns, warnings = adapters.normalize(path, "etrade", "etrade_stockplan")
        expected = [
            (TXN_BUY, "2025-05-09", Decimal(24), Decimal("48.50"), "ESPP"),
            (TXN_SELL, "2025-05-09", Decimal(3), Decimal("48.50"), "TAX_WITHHOLDING"),
            (TXN_BUY, "2025-08-15", Decimal(50), Decimal("66.90"), "RSU_VEST"),
            (TXN_SELL, "2025-08-15", Decimal(16), Decimal("66.90"), "TAX_WITHHOLDING"),
            (TXN_BUY, "2025-11-07", Decimal(19), Decimal("63.40"), "ESPP"),
            (TXN_SELL, "2025-11-07", Decimal(2), Decimal("63.40"), "TAX_WITHHOLDING"),
        ]
        got = rows_of(txns)
        check("the six transactions of the reporting year are exactly right",
              got[:6] == expected, str(got[:6]))
        check("the RSU vest -- the whole sheet that used to be dropped -- is among them",
              one(txns, dt.date(2025, 8, 15), TXN_BUY) is not None)
        check("the purchase dated in the next calendar year is read too, not filtered "
              "here", got[6:] == [
                  (TXN_BUY, "2026-05-08", Decimal(11), Decimal("71.20"), "ESPP"),
                  (TXN_SELL, "2026-05-08", Decimal(1), Decimal("71.20"),
                   "TAX_WITHHOLDING"),
              ], str(got[6:]))
        check("each acquisition is paired with exactly one withholding disposal",
              sorted(t.date for t in acquisitions(txns))
              == sorted(t.date for t in disposals(txns)),
              str([t.date.isoformat() for t in disposals(txns)]))
        check("every disposal is marked as withholding, so it binds to its own vest",
              all(t.disposal_kind == DISPOSAL_TAX_WITHHOLDING for t in disposals(txns)))
        check("no warning claims a row was not imported",
              not any("were NOT imported" in w for w in warnings),
              "; ".join(warnings))

        lots = positions.build_lots(txns)
        vest_lot = [l for l in lots if l.acquire_date == dt.date(2025, 8, 15)]
        check("build_lots makes one lot of 50 for the vest", len(vest_lot) == 1)
        check("holding 34 shares after the 16 sold to cover, which is what the sheet "
              "itself reports as sellable",
              bool(vest_lot)
              and vest_lot[0].qty_on(dt.date(2025, 12, 31)) == Decimal(34),
              str(vest_lot[0].qty_on(dt.date(2025, 12, 31))) if vest_lot else "no lot")


def test_the_transactions_can_be_on_the_second_sheet() -> None:
    print("\nmulti-sheet: a workbook whose data is all on sheet 2")
    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(
            tmp, sheets=[("Plan Summary", DISCLAIMER_ROWS[:3]),
                         ("Restricted Stock", RSU_ROWS)])
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        check("the vest on sheet 2 is imported", len(result.transactions) == 2,
              str(rows_of(result.transactions)))
        check("it is the gross 50 shares at the tranche's cost basis",
              rows_of(result.transactions)[0]
              == (TXN_BUY, "2025-08-15", Decimal(50), Decimal("66.90"), "RSU_VEST"),
              str(rows_of(result.transactions)))
        check("sheet 1 is reported as skipped, not left out of the census",
              [s.name for s in result.skipped_sheets] == ["Plan Summary"],
              str([(s.name, s.skipped) for s in result.sheets]))
        check("and a warning says so, with the sheet named and its rows counted",
              any("worksheet 1 'Plan Summary'" in w and "3 non-empty row(s)" in w
                  for w in result.warnings),
              "; ".join(result.warnings))
        check("a skipped boilerplate sheet is not counted as data loss",
              not result.dropped, str(result.dropped))


def test_a_non_data_sheet_between_data_sheets() -> None:
    print("\nmulti-sheet: instructions and glossary sheets are skipped, never fatal")
    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(
            tmp, sheets=[("ESPP", ESPP_ROWS), ("Disclaimer", DISCLAIMER_ROWS),
                         ("Restricted Stock", RSU_ROWS)])
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        check("both data sheets are still read",
              [s.sheet for s in result.sections] == ["ESPP", "Restricted Stock"],
              str([s.sheet for s in result.sections]))
        check("all eight transactions survive the sheet in between",
              len(result.transactions) == 8, str(len(result.transactions)))
        check("the disclaimer sheet is named and skipped",
              [s.name for s in result.skipped_sheets] == ["Disclaimer"],
              str([(s.name, s.skipped) for s in result.sheets]))
        check("a multi-column glossary row on it is not mistaken for data loss",
              not result.dropped, str(result.dropped))
        check("the census still counts its rows, so it can be checked by eye",
              [s.rows for s in result.skipped_sheets] == [len(DISCLAIMER_ROWS)],
              str([(s.name, s.rows) for s in result.sheets]))


def test_a_hidden_sheet_is_still_read() -> None:
    print("\nmulti-sheet: a hidden worksheet is data, not a decision to skip")
    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(tmp, hidden=("Restricted Stock",))
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        check("the hidden sheet's vest is imported",
              one(result.transactions, dt.date(2025, 8, 15), TXN_BUY) is not None,
              str(rows_of(result.transactions)))
        check("and it is flagged as hidden in the census",
              [s.name for s in result.sheets if s.hidden] == ["Restricted Stock"],
              str([(s.name, s.hidden) for s in result.sheets]))
        check("which the report shows", "(hidden)" in adapters.render_report(result))


def test_a_data_sheet_with_no_header_is_loud() -> None:
    """The one case that must never be quiet: transaction rows nothing governs."""
    print("\nmulti-sheet: a sheet of transactions with no header row stops the run")
    with tempfile.TemporaryDirectory() as tmp:
        naked = [
            ["CSCO", "Restricted Stock Release", "06/16/2025", "42", "124.12"],
            ["CSCO", "Restricted Stock Release", "07/15/2025", "25", "130.05"],
        ]
        path = benefit_workbook(tmp, sheets=[("ESPP", ESPP_ROWS), ("Sheet2", naked)])
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        check("both rows are reported as dropped, not skipped with the sheet",
              len(result.dropped) == 2, str(result.dropped))
        check("the reason says no column layout governs them",
              all("above the first header row" in why
                  for _s, _l, why in result.dropped), str(result.dropped))
        check("the census counts them against their own sheet",
              [section.sheet for section, _l, _w in result.dropped] == ["Sheet2"] * 2,
              str([section.sheet for section, _l, _w in result.dropped]))
        check("the file is not reported as a clean parse",
              any("were NOT imported" in w for w in result.warnings),
              "; ".join(result.warnings))

        out = os.path.join(tmp, "transactions.csv")
        proc = subprocess.run(
            [PYTHON, "-m", "itrprep.cli", "normalize", "--broker", "etrade",
             "--input", path, "--account-id", "etrade_stockplan", "--out", out],
            capture_output=True, text=True, cwd=ROOT,
        )
        check("the CLI exits non-zero", proc.returncode == 1, f"rc={proc.returncode}")
        check("names the sheet the rows came from", "Sheet2" in proc.stdout,
              proc.stdout[-800:])
        check("and reports the workbook's sheets in the census",
              "worksheet 1 'ESPP'" in proc.stdout, proc.stdout[:800])


def test_the_cli_reads_the_whole_workbook() -> None:
    print("\nmulti-sheet: end to end through the CLI")
    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(tmp)
        out = os.path.join(tmp, "transactions.csv")
        proc = subprocess.run(
            [PYTHON, "-m", "itrprep.cli", "normalize", "--broker", "etrade",
             "--input", path, "--account-id", "etrade_stockplan", "--out", out],
            capture_output=True, text=True, cwd=ROOT,
        )
        check("it exits clean", proc.returncode == 0,
              proc.stdout[-1500:] + proc.stderr[-500:])
        check("having written all eight rows", "Wrote 8 transactions" in proc.stdout,
              proc.stdout[-600:])
        back = intermediate.read_transactions(out)
        check("the file reads back with both sheets' rows", len(back) == 8)
        check("the RSU vest is in it at gross quantity",
              any(t.date == dt.date(2025, 8, 15) and t.quantity == Decimal(50)
                  for t in back))


# -- defect 2: FMV, execution price and paid price --------------------------

def test_fmv_beats_the_purchase_price() -> None:
    print("\nESPP price: fair market value, not what was paid")
    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(tmp)
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        espp = result.sections[0]
        check("the ESPP section prices acquisitions from 'Purchase Date FMV'",
              espp.column(adapters.C_PRICE) == "Purchase Date FMV",
              espp.column(adapters.C_PRICE))
        check("not from 'Purchase Price', which is bound as the paid price instead",
              espp.column(adapters.C_PAID_PRICE) == "Purchase Price",
              espp.column(adapters.C_PAID_PRICE))
        first = one(result.transactions, dt.date(2025, 5, 9), TXN_BUY)
        check("so the lot's cost basis is the FMV",
              first is not None and first.price_usd == Decimal("48.50"),
              str(first.price_usd) if first else "missing")
        check("and the discounted price is kept beside it, not thrown away",
              first is not None and first.paid_price_usd == Decimal("41.225"),
              str(first.paid_price_usd) if first else "missing")
        check("the withholding disposal is valued at the same FMV",
              (lambda s: s is not None and s.price_usd == Decimal("48.50"))(
                  one(result.transactions, dt.date(2025, 5, 9), TXN_SELL)))
        check("'Grant Date FMV' does not win, though it sits in the same row and is "
              "higher",
              all(t.price_usd != Decimal("52.10") for t in result.transactions),
              str([str(t.price_usd) for t in result.transactions]))
        check("'Est. Cost Basis (per share):' is an alias too, colon included",
              any(adapters._norm(a) == "est. cost basis (per share):"
                  for a in adapters.ETRADE.price_aliases))

        with tempfile.TemporaryDirectory() as work:
            csv_path = os.path.join(work, "transactions.csv")
            intermediate.write_transactions(csv_path, result.transactions)
            back = intermediate.read_transactions(csv_path)
            check("paid_price_usd round-trips through the intermediate CSV",
                  sorted(t.paid_price_usd for t in back if t.paid_price_usd)
                  == [Decimal("41.225"), Decimal("53.89"), Decimal("60.01")],
                  str(sorted(str(t.paid_price_usd) for t in back)))
            check("and the cost basis is still the FMV after the round trip",
                  sorted(t.price_usd for t in back if t.txn_type == TXN_BUY)
                  == [Decimal("48.50"), Decimal("63.40"), Decimal("66.90"),
                      Decimal("71.20")],
                  str(sorted(str(t.price_usd) for t in back if t.txn_type == TXN_BUY)))


def test_a_paid_price_only_section_says_so() -> None:
    """No FMV column at all: parse it, but never let the double count pass quietly."""
    print("\nESPP price: an export with only a purchase price is flagged")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "espp.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Record Type,Symbol,Purchase Date,Purchase Price,Purchased Qty.,"
                     "Tax Collection Shares,Grant Number\n"
                     "Purchase,CSCO,05/09/2025,41.225,24,3,ESPP-2025-H1\n")
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        check("the row is still imported rather than dropped",
              len(result.transactions) == 2, str(rows_of(result.transactions)))
        check("priced at what was paid, because nothing better is in the file",
              result.transactions[0].price_usd == Decimal("41.225"),
              str(result.transactions[0].price_usd))
        check("and the run says the cost basis should be the FMV instead, under both Acts",
              any("49(2AA)" in w and "17(2)(vi)" in w
                  and "73(1)" in w and "17(1)(d)" in w for w in result.warnings),
              "; ".join(result.warnings))
        check("naming the column it had to fall back to",
              any("'Purchase Price'" in w for w in result.warnings),
              "; ".join(result.warnings))


def test_a_disposal_uses_the_execution_price() -> None:
    print("\ndisposal price: what the sale executed at, not a fair market value")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "gl.csv")
        # One section carrying both: the acquisition FMV and the price the sale went off
        # at. Before the lists were split, whichever came first in one tuple won both.
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Symbol,Transaction Type,Vest Date,Quantity,Shares Sold,"
                     "Vest Date FMV,Sale Price,Grant Number\n"
                     "CSCO,Restricted Stock Release,06/16/2025,42,,124.12,,GRANT-1\n"
                     "CSCO,Sale,11/20/2025,,10,124.12,75.44,GRANT-1\n")
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        section = result.sections[0]
        check("the section binds the FMV as the acquisition price",
              section.column(adapters.C_PRICE) == "Vest Date FMV",
              section.column(adapters.C_PRICE))
        check("and the sale price separately",
              section.column(adapters.C_SALE_PRICE) == "Sale Price",
              section.column(adapters.C_SALE_PRICE))
        check("no row is dropped", not result.dropped, str(result.dropped))
        vest = one(result.transactions, dt.date(2025, 6, 16), TXN_BUY)
        sale = one(result.transactions, dt.date(2025, 11, 20), TXN_SELL)
        check("the vest is valued at the FMV",
              vest is not None and vest.price_usd == Decimal("124.12"),
              str(vest.price_usd) if vest else "missing")
        check("the sale at what it executed at",
              sale is not None and sale.price_usd == Decimal("75.44"),
              str(sale.price_usd) if sale else "missing")

        # A Benefit History sale block names no sale price at all, and must keep using the
        # only per-share column it has.
        legacy, _ = adapters.normalize(
            os.path.join(EXPORTS, "etrade_benefit_history.csv"), "etrade", "et")
        check("a sale section with no sale-price column still falls back to the FMV",
              sorted(t.price_usd for t in disposals(legacy))
              == [Decimal("68.13"), Decimal("75.44")],
              str(sorted(str(t.price_usd) for t in disposals(legacy))))


# -- the nested restricted-stock shape --------------------------------------

def test_the_nested_rsu_shape() -> None:
    print("\nnested RSU sheet: one acquisition per VESTED tranche, and nothing else")
    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(tmp)
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        rsu = result.sections[1]
        vests = [t for t in result.transactions if t.lot_id.startswith("RU")]
        check("exactly one acquisition and one disposal came off the sheet",
              [t.txn_type for t in vests] == [TXN_BUY, TXN_SELL],
              str(rows_of(vests)))
        check("the acquisition is the gross vested count, which the perquisite is charged on",
              vests[0].quantity == Decimal(50), str(vests[0].quantity))
        check("the disposal is 'Shares Traded for taxes', not 'Withheld Qty.'",
              vests[1].quantity == Decimal(16), str(vests[1].quantity))
        check("the withheld column bound is the populated one",
              rsu.column(adapters.C_WITHHELD) == "Shares Traded for taxes",
              rsu.column(adapters.C_WITHHELD))
        check("both legs carry the grant number as the lot label",
              {t.lot_id for t in vests} == {"RU100001"},
              str({t.lot_id for t in vests}))
        check("the vest inherits its symbol from the grant row above it",
              {t.ticker for t in vests} == {"CSCO"}, str({t.ticker for t in vests}))
        check("and the run says which rows took an inherited symbol",
              any("carry no symbol" in w for w in result.warnings),
              "; ".join(result.warnings))
        check("it is priced from the tranche's own cost-basis row",
              vests[0].price_usd == Decimal("66.90"), str(vests[0].price_usd))
        check("with the provenance recorded on the row",
              "66.90" in vests[0].notes and "Est. Cost Basis" in vests[0].notes,
              vests[0].notes)
        check("and stated as a warning, to be checked against Form 12BA",
              any("12BA" in w and "position row" in w for w in result.warnings),
              "; ".join(result.warnings))

        ignored = dict(adapters._group(rsu.ignored))
        unvested = sum(n for why, n in ignored.items() if "unvested" in why)
        scheduled = sum(1 for row in RSU_ROWS if row[0] == "Vest Schedule")
        check("every tranche that has not vested produces no transaction at all",
              unvested == scheduled - 1 == 7, str(ignored))
        check("and are named as unvested rather than reported as data loss",
              not rsu.dropped and any("states 0 shares" in why for why in ignored),
              str(rsu.dropped) + str(ignored))
        check("the future vest dates are nowhere in the output",
              not any(t.date.year > 2026 for t in result.transactions),
              str([t.date.isoformat() for t in result.transactions]))

        snapshots = sum(n for why, n in ignored.items() if "position or a plan" in why)
        check("the grant, withholding and sellable-shares records are ignored as "
              "positions", snapshots == 2 + 3 + 1, str(ignored))
        check("'Sellable Shares' is NOT read as a disposal of the sellable balance",
              not any(t.quantity == Decimal(34) for t in result.transactions),
              str(rows_of(result.transactions)))
        check("a grant of 200 unvested shares is not an acquisition of anything",
              not any(t.quantity == Decimal(200) for t in result.transactions))
        check("the totals row is ignored, not counted as dropped",
              ignored.get("totals/footer line") == 1, str(ignored))
        check("every row of the sheet is accounted for", rsu.accounted_for,
              f"{len(rsu.rows)} rows, {rsu.consumed} consumed, {len(rsu.ignored)} "
              f"ignored, {len(rsu.dropped)} dropped")


def test_repeated_column_names_resolve_by_index() -> None:
    print("\nnested RSU sheet: repeated header names are resolved by index")
    duplicated = [name for name in set(RSU_HEADER) if RSU_HEADER.count(name) > 1]
    check("the fixture really does repeat column names, as the export does",
          sorted(duplicated) == ["Blocked Qty.", "Cancelled Qty.", "Granted Qty.",
                                 "Pending Sale Qty.", "Sellable Qty.", "Tax Status",
                                 "Vested Qty."],
          str(sorted(duplicated)))
    check("'Sellable Qty.' appears three times", RSU_HEADER.count("Sellable Qty.") == 3)

    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(tmp)
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        rsu = result.sections[1]
        check("the quantity column is the per-tranche released count at index 26",
              rsu.mapping.get(adapters.C_QTY) == 26, str(rsu.mapping))
        check("the withheld column is the one at index 38",
              rsu.mapping.get(adapters.C_WITHHELD) == 38, str(rsu.mapping))
        check("the cost basis is read from index 35",
              rsu.mapping.get(adapters.C_PRICE) == 35, str(rsu.mapping))
        check("the vest period, which ties a tranche to its position row, from index 18",
              rsu.mapping.get(adapters.C_PERIOD) == 18, str(rsu.mapping))
        check("every mapped concept has a distinct column",
              len(set(rsu.mapping.values())) == len(rsu.mapping), str(rsu.mapping))
        check("no concept binds a repeated name whose first copy is the grant-level one",
              rsu.mapping.get(adapters.C_QTY) != 4
              and rsu.mapping.get(adapters.C_WITHHELD) != 5, str(rsu.mapping))
        check("'Record Type' wins the type column over the bare 'Type' beside it",
              rsu.column(adapters.C_TYPE) == "Record Type",
              rsu.column(adapters.C_TYPE))


def test_snapshot_valuations_can_never_be_a_price() -> None:
    print("\nguard: estimated market value and unrealised gain are not tax figures")
    for header in ("Est. Market Value", "Sellable Est. Market Value",
                   "Est. Taxable Gain/Loss (per share):", "Expected Gain/Loss",
                   "Dividend Market Value at Release", "Total Taxes Paid"):
        check(f"{header!r} is refused as a column for any concept",
              adapters._norm(header) in adapters.FORBIDDEN_COLUMNS, header)

    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(tmp)
        result = adapters.normalize_report(path, "etrade", "etrade_stockplan")
        for section in result.sections:
            bound = {section.column(c) for c in section.mapping}
            check(f"nothing forbidden is bound on the {section.sheet} sheet",
                  not bound & {"Est. Market Value", "Sellable Est. Market Value",
                               "Est. Taxable Gain/Loss (per share):",
                               "Expected Gain/Loss",
                               "Dividend Market Value at Release", "Total Taxes Paid"},
                  str(sorted(bound)))
        check("no transaction is valued at an estimated market value",
              not any(t.price_usd in (Decimal("12500.00"), Decimal("2274.60"),
                                      Decimal("1018.50"))
                      or t.amount_usd in (Decimal("12500.00"), Decimal("2274.60"))
                      for t in result.transactions),
              str(rows_of(result.transactions)))

        # An "Est. Market Value" that a future maintainer aliased in anyway still cannot
        # bind, which is the point of the guard being in _resolve_columns.
        greedy = adapters.Profile(
            name="greedy", date_aliases=("Purchase Date",), ticker_aliases=("Symbol",),
            quantity_aliases=("Purchased Qty.",), price_aliases=("Est. Market Value",),
            amount_aliases=("Est. Market Value",), type_aliases=("Record Type",),
            buy_markers=("purchase",), sell_markers=(), dividend_markers=(),
        )
        mapping = adapters._resolve_columns(greedy, ESPP_HEADER, ESPP_ROWS[1:])
        check("even an explicit alias for it resolves to nothing",
              adapters.C_PRICE not in mapping and adapters.C_AMOUNT not in mapping,
              str(mapping))


def test_a_zero_column_cannot_beat_a_populated_one() -> None:
    print("\naliases: a share count present but zero everywhere loses to a real figure")
    header = ["Symbol", "Transaction Type", "Vest Date", "Shares Issued",
              "Withheld Qty.", "Shares Traded For Taxes", "Vest Date FMV"]
    net_settled = [["CSCO", "Restricted Stock Release", "08/15/2025", "50", "16", "0",
                    "66.90"]]
    sold_to_cover = [["CSCO", "Restricted Stock Release", "08/15/2025", "50", "0", "16",
                      "66.90"]]
    for label, rows in (("a net share settlement", net_settled),
                        ("a market sell-to-cover", sold_to_cover)):
        mapping = adapters._resolve_columns(adapters.ETRADE, header, rows)
        index = mapping.get(adapters.C_WITHHELD)
        check(f"{label} binds whichever of the two columns carries the count",
              index is not None and rows[0][index] == "16",
              f"bound {header[index] if index is not None else None!r}")


# -- regression -------------------------------------------------------------

def test_single_sheet_and_single_section_exports_are_unchanged() -> None:
    """Same rows, same numbers, same warnings as before either fix."""
    print("\nregression: the fixtures that already worked parse identically")
    et, et_warnings = adapters.normalize(
        os.path.join(EXPORTS, "etrade_benefit_history.csv"), "etrade", "etrade_stockplan")
    check("etrade: still 7 transactions", len(et) == 7, f"got {len(et)}")
    check("etrade: prices and quantities unchanged",
          rows_of(et) == [
              (TXN_BUY, "2024-08-15", Decimal(50), Decimal("48.53"), "RSU_VEST"),
              (TXN_BUY, "2025-02-15", Decimal(40), Decimal("64.87"), "RSU_VEST"),
              (TXN_BUY, "2025-05-15", Decimal(35), Decimal("64.26"), "RSU_VEST"),
              (TXN_BUY, "2025-06-30", Decimal(22), Decimal("58.97"), "ESPP"),
              (TXN_BUY, "2025-08-15", Decimal(30), Decimal("66.20"), "RSU_VEST"),
              (TXN_SELL, "2025-09-10", Decimal(40), Decimal("68.13"), ""),
              (TXN_SELL, "2025-11-20", Decimal(25), Decimal("75.44"), ""),
          ], str(rows_of(et)))
    check("etrade: no new warnings", not et_warnings, "; ".join(et_warnings))
    check("etrade: no paid price is invented where the export states none",
          not any(t.paid_price_usd for t in et))

    fid, fid_warnings = adapters.normalize(
        os.path.join(EXPORTS, "fidelity_espp.csv"), "fidelity", "fidelity_espp")
    check("fidelity: 8 transactions, four of them ESPP purchases",
          len(fid) == 8 and len(acquisitions(fid)) == 4, f"got {len(fid)}")
    check("fidelity: purchases still priced from 'Purchase Value per Share'",
          sorted(t.price_usd for t in acquisitions(fid))
          == [Decimal("122.93"), Decimal("124.24"), Decimal("133.23"),
              Decimal("140.69")],
          str(sorted(str(t.price_usd) for t in acquisitions(fid))))
    check("fidelity: no new warnings", not fid_warnings, "; ".join(fid_warnings))

    ind, ind_warnings = adapters.normalize(
        os.path.join(EXPORTS, "indmoney_transactions.csv"), "indmoney", "indmoney_us")
    check("indmoney: still 9 transactions", len(ind) == 9, f"got {len(ind)}")
    check("indmoney: buys and sells keep their own prices",
          rows_of(ind)[0] == (TXN_BUY, "2023-05-22", Decimal(30), Decimal("420.56"),
                              "OPEN_MARKET")
          and rows_of(ind)[-2] == (TXN_SELL, "2025-10-15", Decimal(20),
                                   Decimal("668.28"), ""),
          str(rows_of(ind)))
    check("indmoney: no new warnings", not ind_warnings, "; ".join(ind_warnings))

    multi, _ = adapters.normalize(
        os.path.join(EXPORTS, "etrade_benefit_history_multisection.csv"), "etrade",
        "etrade_stockplan")
    check("the multi-section CSV still yields its 8 transactions", len(multi) == 8,
          f"got {len(multi)}")
    check("with the 42-share vest still at its $124.12 FMV",
          (lambda v: v is not None and v.quantity == Decimal(42)
           and v.price_usd == Decimal("124.12"))(
              one(multi, dt.date(2025, 6, 16), TXN_BUY)))
    check("a CSV's transactions still name the file alone as their source",
          all(t.source_file.endswith(".csv") for t in multi),
          str({t.source_file for t in multi}))
    check("all four exports are still detected by content",
          [adapters.detect(os.path.join(EXPORTS, n)).broker for n in (
              "etrade_benefit_history.csv", "fidelity_espp.csv",
              "indmoney_transactions.csv", "etrade_benefit_history_multisection.csv")]
          == ["etrade", "fidelity", "indmoney", "etrade"])

    with tempfile.TemporaryDirectory() as tmp:
        path = benefit_workbook(tmp)
        check("a workbook is detected as E*TRADE from its sheets' headers",
              adapters.detect(path).broker == "etrade",
              str(adapters.detect(path)))


def main() -> int:
    test_every_worksheet_is_read()
    test_the_whole_workbook_becomes_transactions()
    test_the_transactions_can_be_on_the_second_sheet()
    test_a_non_data_sheet_between_data_sheets()
    test_a_hidden_sheet_is_still_read()
    test_a_data_sheet_with_no_header_is_loud()
    test_the_cli_reads_the_whole_workbook()
    test_fmv_beats_the_purchase_price()
    test_a_paid_price_only_section_says_so()
    test_a_disposal_uses_the_execution_price()
    test_the_nested_rsu_shape()
    test_repeated_column_names_resolve_by_index()
    test_snapshot_valuations_can_never_be_a_price()
    test_a_zero_column_cannot_beat_a_populated_one()
    test_single_sheet_and_single_section_exports_are_unchanged()

    print()
    if failures:
        print(f"FAILED -- {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All multi-sheet workbook / FMV-basis / nested-RSU checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
