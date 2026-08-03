"""Stage 1: broker exports -> the intermediate transactions CSV.

None of these three export formats could be confirmed against a real file, so each adapter
is written as a column-alias profile rather than fixed column positions. The adapter sniffs
the header, maps whatever it recognises, and if a required concept is missing it says which
column it could not find and lists the headers it did see. That failure mode is the point:
the user can then either rename one column or fall back to hand-filling the intermediate
CSV, and either way gets correct output.

Add an alias to the relevant profile when a real export turns out to use a new name.

A stock-plan export is also **multi-section**: an E*TRADE / StockPlan Connect "Benefit
History" carries one block per plan type or per grant, each with its own header row and
its own column order and width. So the column mapping is resolved per section, never once
for the file, and every row that does not become a transaction is counted and named. A
row read against another section's columns is the worst kind of wrong -- it either
disappears or arrives with the tax-withholding share count sitting in the price field --
and both failures used to be silent.

A workbook is **multi-sheet** for the same reason: a "By Benefit Type" export puts ESPP
purchases on one worksheet and restricted stock on another, each with its own header and
its own width. Sheets are therefore read like sections -- every one of them, each mapped
on its own header -- and the census names every worksheet with its row count, including
the ones nothing was read from. Reading only the first sheet is what dropped a whole RSU
vest from a real Schedule FA, and it did so without a single warning.

Per-share value is **three concepts, not one**. What an acquisition cost for Indian tax
purposes is the fair market value the perquisite was charged on under s.17(1)(d) of the
Income-tax Act, 2025, which s.73(1) then makes the cost of acquisition -- s.17(2)(vi) and
s.49(2AA) of the 1961 Act -- not the discounted price the
employee paid, which Form 16 has already taxed as salary. What a disposal realised is the
execution price. And the paid price is neither: it is the evidence of the ESPP discount,
so it is carried alongside rather than thrown away.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .models import (
    ACQ_ESPP,
    ACQ_RSU_VEST,
    DISPOSAL_TAX_WITHHOLDING,
    TXN_BUY,
    TXN_DIVIDEND,
    TXN_SELL,
    DataError,
    Transaction,
)


class Profile:
    """Column aliases and row-classification rules for one broker's export."""

    def __init__(
        self,
        name: str,
        date_aliases,
        ticker_aliases,
        quantity_aliases,
        price_aliases,
        amount_aliases,
        type_aliases,
        buy_markers,
        sell_markers,
        dividend_markers,
        tax_aliases=(),
        acq_kind_default="",
        lot_aliases=(),
        withheld_aliases=(),
        net_quantity_aliases=(),
        sold_quantity_aliases=(),
        acquire_and_dispose_markers=(),
        acq_kind_markers=(),
        sale_price_aliases=(),
        paid_price_aliases=(),
        period_aliases=(),
        snapshot_markers=(),
        notes=("",),
    ):
        self.name = name
        self.date_aliases = date_aliases
        self.ticker_aliases = ticker_aliases
        self.quantity_aliases = quantity_aliases
        # What an acquisition is worth: the FMV charged as a perquisite. See
        # `sale_price_aliases` and `paid_price_aliases` for the other two.
        self.price_aliases = price_aliases
        self.amount_aliases = amount_aliases
        self.type_aliases = type_aliases
        self.buy_markers = buy_markers
        self.sell_markers = sell_markers
        self.dividend_markers = dividend_markers
        self.tax_aliases = tax_aliases
        self.acq_kind_default = acq_kind_default
        self.lot_aliases = lot_aliases
        # Gross, withheld and net are three different share counts and must stay
        # separate. Section 17(1)(d) of the Act of 2025 charges the perquisite on GROSS
        # shares and
        # Schedule FA reports the gross acquisition with the withheld portion as a
        # disposal, so folding them into one "quantity" understates both that schedule
        # and Schedule CG.
        self.withheld_aliases = withheld_aliases
        self.net_quantity_aliases = net_quantity_aliases
        self.sold_quantity_aliases = sold_quantity_aliases
        self.acquire_and_dispose_markers = acquire_and_dispose_markers
        # (acq_kind, markers) in priority order. Only stock-plan profiles set this: a
        # retail app's "Purchase" is an open-market buy, not an ESPP one, so inferring
        # from the word alone would mislabel every INDmoney row.
        self.acq_kind_markers = acq_kind_markers
        # What a disposal realised. A sale is measured at what it executed at, never at a
        # fair market value, so a section carrying both columns must not use one list.
        self.sale_price_aliases = sale_price_aliases
        # What the employee actually paid. NOT the cost of acquisition -- s.73(1) of the
        # Income-tax Act, 2025 (s.49(2AA) of the 1961 Act) makes that the FMV the
        # perquisite was charged on -- but it is the only evidence
        # of the ESPP discount in the export, so it is kept for the audit trail.
        self.paid_price_aliases = paid_price_aliases
        # Which tranche of an award a row belongs to. In a nested stock-plan export the
        # vest row and the sellable-shares row for one tranche are separate rows tied by
        # grant number and period, and only the second states the per-share basis.
        self.period_aliases = period_aliases
        # Record types that state a position or a plan rather than an event: a grant, a
        # withholding-tax breakdown, a sellable-shares balance. They are not transactions
        # and must not be read as any -- "Sellable Shares" contains "sell", so without
        # this it classifies as a disposal and invents a sale of the whole balance.
        self.snapshot_markers = snapshot_markers


ETRADE = Profile(
    name="etrade",
    # E*TRADE / Morgan Stanley StockPlan Connect "Benefit History" and
    # "Gains & Losses" exports have used all of these over the years.
    # Event date first, acquisition date LAST. A Gains & Losses section carries both
    # "Date Sold" and "Date Acquired"; the row's own date is the sale, and dating it at
    # acquisition instead would move a disposal into the wrong reporting year.
    date_aliases=("Date", "Transaction Date", "Trade Date", "Sale Date", "Date Sold",
                  "Vest Date", "Release Date", "Distribution Date", "Purchase Date",
                  "Event Date", "Issue Date", "Payable Date", "Settlement Date",
                  "Acquired Date", "Date Acquired", "Acquisition Date"),
    ticker_aliases=("Symbol", "Ticker", "Security", "Stock Symbol", "Security Symbol"),
    # Gross acquired quantity, most specific name first. Generic "Quantity"/"Shares"
    # come last so a section that names the concept exactly wins over one that does not.
    #
    # "Sellable Quantity" is deliberately NOT here. It describes how much of a holding
    # may be sold today, not how much was acquired: it reads 0 for a vest already sold
    # to cover, which used to make the whole row fail the `qty <= 0` guard and vanish.
    # It stays in SIGNATURE_HEADERS -- it is still good evidence the file is E*TRADE's.
    quantity_aliases=("Shares Issued", "Gross Shares", "Shares Vested",
                      "Quantity Vested", "Released Qty.", "Released Qty",
                      "Shares Released", "Purchased Qty.", "Purchased Qty",
                      "Shares Purchased", "Quantity", "Shares", "Qty",
                      "Number of Shares"),
    # Per-share value of an ACQUISITION, most defensible name first.
    #
    # The event-date FMV leads, because s.17(1)(d) of the Act of 2025 charges the
    # perquisite on the FMV on the date of acquisition and s.73(1) then makes it the
    # cost of acquisition. The broker's own per-share cost basis comes next -- it is that
    # FMV, stated as a number. A paid or purchase price comes near the end: it is what the
    # employee handed over after the ESPP discount, the discount has already been taxed as
    # salary through Form 16, and pricing the lot at it double counts the discount as a
    # capital gain. It stays in the list only so an export that carries nothing better
    # still parses, and _read_section warns loudly when a row is priced from it.
    #
    # "Grant Date FMV" sits at the very end deliberately. An ESPP sheet carries it beside
    # "Purchase Date FMV" and the two differ by the whole offering period, sometimes by a
    # multiple: the grant-date figure is the lookback reference the discount is computed
    # from, not the value the perquisite is charged on. Same for "Market Value", which real
    # exports use for the vest-date FMV but which also names a row total; that case is
    # caught by _price_is_a_total.
    price_aliases=("Market Value Per Share", "Vest Date FMV", "Vest Date Market Value",
                   "Release Date FMV", "Release Date Market Value", "Purchase Date FMV",
                   "Fair Market Value", "FMV Per Share", "FMV",
                   "Est. Cost Basis (per share):", "Est. Cost Basis (per share)",
                   "Est. Cost Basis Per Share", "Estimated Cost Basis Per Share",
                   "Cost Basis (per share):", "Cost Basis (per share)",
                   "Cost Basis Per Share", "Cost Basis/Share",
                   "Price Per Share At Vest", "Price Per Share", "Value Per Share",
                   "Price", "Purchase Price", "Acquisition Price", "Grant Date FMV",
                   "Market Value"),
    amount_aliases=("Amount", "Total Value", "Proceeds", "Net Proceeds",
                    "Total Price", "Gross Proceeds", "Total Market Value"),
    # "Record Type" outranks a bare "Type": a nested restricted-stock sheet carries both,
    # where "Record Type" holds the event ("Vest Schedule", "Tax Withholding") and "Type"
    # holds the instrument ("RSU") and is blank on every row but the grant. Binding the
    # generic name leaves every event row with no type at all.
    type_aliases=("Transaction Type", "Record Type", "Activity", "Event Type", "Type",
                  "Plan Type", "Description", "Plan Name"),
    buy_markers=("vest", "release", "purchase", "espp", "buy", "acquired",
                 "shares issued", "rs", "restricted stock", "lapse", "distribution",
                 "share deposit", "shares deposited", "stock deposit"),
    sell_markers=("sale", "sell", "sold", "disposition"),
    dividend_markers=("dividend", "div reinvest", "cash dividend",
                      "cash distribution"),
    # One row that is BOTH an acquisition and a disposal: the shares vest (or the option
    # is exercised) and part or all of them is sold in the same event. Checked before the
    # plain sell markers, which used to swallow these rows whole -- classifying a
    # sell-to-cover vest as a pure SELL loses the acquisition AND invents a disposal of
    # shares that were never separately held.
    acquire_and_dispose_markers=("sell to cover", "sell-to-cover", "sold to cover",
                                 "shares withheld", "withhold to cover",
                                 "traded to cover", "net share settlement",
                                 "exercise and sell", "vest and sell",
                                 "release and sell"),
    # A disposal is measured at what it executed at. "Sale Price" is here and NOT in
    # price_aliases: a Gains & Losses block carries it next to an acquisition FMV, and
    # using it to value an acquisition would put the wrong cost basis in Schedule FA.
    # A section that names no sale price falls back to price_aliases, which is what a
    # Benefit History sale row (priced from its own FMV column) relies on.
    sale_price_aliases=("Sale Price", "Sales Price", "Execution Price", "Executed Price",
                        "Price Sold", "Proceeds Per Share", "Net Proceeds Per Share",
                        "Market Value Per Share", "Price Per Share", "Price"),
    # Captured for the audit trail only; never used as a cost basis. "Purchase Price" on
    # an E*TRADE ESPP row is the discounted price, 15% off the lower of the grant-date and
    # purchase-date FMV.
    paid_price_aliases=("Purchase Price", "Price Paid", "Purchase Price Per Share",
                        "Price Paid Per Share", "Subscription Price", "Offering Price",
                        "Discounted Purchase Price", "Discount Price"),
    period_aliases=("Vest Period", "Vest Tranche", "Tranche", "Vest Number",
                    "Vest No.", "Period"),
    # Exact record-type labels, matched whole rather than as substrings: "grant" as a
    # substring would swallow a "Grant Release", which is a real vest.
    snapshot_markers=("grant", "grants", "grant summary", "award", "award summary",
                      "tax withholding", "tax withholding detail", "tax withholdings",
                      "sellable shares", "sellable qty", "holdings", "holding",
                      "holding summary", "position", "positions", "summary"),
    tax_aliases=("Tax Withheld", "Taxes", "Withholding", "Federal Tax Withheld"),
    lot_aliases=("Lot", "Lot Id", "Grant Number", "Grant Id", "Award Id",
                 "Award Number", "Original Grant Number"),
    # Shares that never reached the employee. "Shares Traded For Taxes" and
    # "Withheld Qty." are different events -- a market sell-to-cover against a net share
    # settlement -- and a real vest row carries both, one of them zero. Neither order
    # would be right on its own, so _resolve_columns prefers whichever column actually
    # holds a non-zero count.
    withheld_aliases=("Tax Collection Shares", "Shares Withheld",
                      "Shares Withheld For Taxes", "Withheld Shares",
                      "Tax Withholding Shares", "Shares Sold For Taxes",
                      "Sell To Cover Shares", "Shares Traded For Taxes",
                      "Withholding Shares", "Shares For Tax", "Withheld Qty.",
                      "Withheld Qty"),
    net_quantity_aliases=("Net Shares", "Net Shares Issued", "Net Quantity",
                          "Shares Deposited", "Net Shares Deposited",
                          "Shares To Employee"),
    sold_quantity_aliases=("Shares Sold", "Quantity Sold", "Sold Qty.", "Sold Qty",
                           "Sale Quantity", "Shares Disposed"),
    acq_kind_markers=(
        (ACQ_ESPP, ("espp", "employee stock purchase", "stock purchase plan")),
        (ACQ_RSU_VEST, ("rsu", "restricted stock", "release", "vest", "lapse",
                        "distribution", "share deposit", "shares deposited", "psu",
                        "performance share")),
        (ACQ_ESPP, ("purchase",)),
    ),
)

FIDELITY = Profile(
    name="fidelity",
    # Fidelity NetBenefits stock-plan history / "View Details" CSV exports.
    date_aliases=("Date", "Transaction Date", "Purchase Date", "Acquired Date",
                  "Offering Period End Date", "Run Date", "Settlement Date"),
    ticker_aliases=("Symbol", "Ticker", "Security Description", "Investment"),
    quantity_aliases=("Shares Purchased", "Gross Shares", "Shares Issued",
                      "Quantity", "Shares", "Qty", "Number of Shares"),
    # FMV first, for the s.73(1) (Act of 2025) reason set out on the E*TRADE profile.
    # "Purchase Value per Share" is Fidelity's own name for the figure the perquisite was
    # charged on, so it ranks with the FMV names and above any paid price.
    price_aliases=("Purchase Date FMV", "Subscription Date FMV", "Fair Market Value",
                   "FMV Per Share", "FMV", "Purchase Value per Share",
                   "Est. Cost Basis (per share):", "Est. Cost Basis (per share)",
                   "Cost Basis Per Share", "Price Per Share", "Price", "Market Price",
                   "Purchase Price", "Market Value"),
    sale_price_aliases=("Sale Price", "Execution Price", "Price Sold",
                        "Proceeds Per Share", "Price Per Share", "Price"),
    paid_price_aliases=("Purchase Price", "Price Paid", "Subscription Price",
                        "Offering Price", "Discounted Purchase Price"),
    amount_aliases=("Amount", "Total Cost", "Total Value", "Proceeds",
                    "Principal Amount"),
    type_aliases=("Transaction Type", "Type", "Action", "Description",
                  "Transaction Description"),
    buy_markers=("purchase", "espp", "buy", "bought", "acquired", "vest",
                 "shares purchased", "you bought", "lapse", "distribution",
                 "share deposit", "shares deposited"),
    sell_markers=("sale", "sell", "sold", "you sold", "disposition"),
    dividend_markers=("dividend", "div", "reinvestment", "cash distribution"),
    acquire_and_dispose_markers=("sell to cover", "sell-to-cover", "sold to cover",
                                 "shares withheld", "net share settlement",
                                 "exercise and sell"),
    tax_aliases=("Tax Withheld", "Withholding", "Federal Tax"),
    acq_kind_default="ESPP",
    lot_aliases=("Lot", "Lot Id", "Offering Period"),
    withheld_aliases=("Shares Withheld", "Shares Withheld For Taxes",
                      "Tax Withholding Shares", "Withheld Shares"),
    net_quantity_aliases=("Net Shares", "Net Quantity", "Shares Deposited"),
    sold_quantity_aliases=("Shares Sold", "Quantity Sold", "Sale Quantity"),
    acq_kind_markers=(
        (ACQ_RSU_VEST, ("rsu", "restricted stock", "release", "vest", "lapse",
                        "distribution", "share deposit", "shares deposited")),
        (ACQ_ESPP, ("espp", "purchase", "employee stock purchase")),
    ),
)

INDMONEY = Profile(
    name="indmoney",
    # INDmoney US-stocks transaction / order history exports.
    date_aliases=("Date", "Transaction Date", "Trade Date", "Order Date",
                  "Executed At", "Timestamp"),
    ticker_aliases=("Symbol", "Ticker", "Stock", "Scrip", "Instrument",
                    "Stock Name", "Security"),
    quantity_aliases=("Quantity", "Qty", "Shares", "Units", "No. of Shares"),
    price_aliases=("Price", "Price Per Share", "Avg Price", "Average Price",
                   "Executed Price", "Rate", "Price (USD)"),
    amount_aliases=("Amount", "Total Amount", "Net Amount", "Value",
                    "Amount (USD)", "Total (USD)", "Gross Amount"),
    type_aliases=("Type", "Transaction Type", "Side", "Order Type",
                  "Action", "Description", "Narration"),
    # "xtrf" is DriveWealth/INDmoney's in-kind transfer-in code -- no cash changes hands,
    # but it is a real acquisition (a cost basis and date exist even though Amount is 0).
    buy_markers=("buy", "bought", "purchase", "b", "xtrf"),
    sell_markers=("sell", "sold", "sale", "s"),
    dividend_markers=("dividend", "div"),
    tax_aliases=("Tax Withheld", "Withholding Tax", "TDS", "US Tax", "Tax"),
    acq_kind_default="OPEN_MARKET",
    lot_aliases=("Lot", "Lot Id", "Order Id"),
    # A retail app has no employer withholding, so there is no gross/net split to make.
    sold_quantity_aliases=("Quantity Sold", "Shares Sold"),
)

PROFILES = {p.name: p for p in (ETRADE, FIDELITY, INDMONEY)}

# Detection signatures. Every profile shares the generic headers -- Date, Quantity, Symbol
# -- so those cannot discriminate. These are the headers and brand strings that only one
# provider actually emits, which is what makes header sniffing possible at all.
SIGNATURE_HEADERS = {
    "etrade": ("vest date fmv", "grant date fmv", "grant number", "grant id",
               "award id", "sellable quantity", "record type", "plan type",
               "market value per share", "acquisition price"),
    "fidelity": ("offering period", "offering period end date",
                 "subscription date fmv", "purchase date fmv", "shares purchased",
                 "run date", "principal amount", "security description"),
    "indmoney": ("price (usd)", "amount (usd)", "total (usd)", "scrip", "stock name",
                 "narration", "instrument", "executed price", "executed at",
                 "no. of shares", "units"),
}

# Brand strings that show up in a preamble, a title row or a footer. Weaker evidence than a
# signature header but often the only evidence a plain export gives.
SIGNATURE_TEXT = {
    "etrade": ("e*trade", "etrade", "morgan stanley", "stockplan connect",
               "shareworks", "benefit history"),
    "fidelity": ("fidelity", "netbenefits"),
    "indmoney": ("indmoney", "ind money", "drivewealth", "indmoney private"),
}

_HEADER_WEIGHT = 3
_TEXT_WEIGHT = 2


@dataclass
class Detection:
    """What a single dropped file was matched to, and why."""

    path: str
    broker: str | None
    score: int
    runner_up: str | None
    runner_up_score: int
    evidence: list[str]
    reason: str = ""

    @property
    def confident(self) -> bool:
        return self.broker is not None


@dataclass
class Sheet:
    """One worksheet of a workbook, or the whole file for a CSV.

    `name` is empty for a CSV, which is what keeps every message about a flat file
    reading the way it did before workbooks were read sheet by sheet.
    """

    name: str
    rows: list[list[str]] = field(default_factory=list)
    index: int = 1
    hidden: bool = False

    @property
    def label(self) -> str:
        return f"worksheet {self.index} {self.name!r}" if self.name else "the file"

    @property
    def populated_rows(self) -> int:
        return sum(1 for r in self.rows if any((c or "").strip() for c in r))


def read_sheets(path: str) -> list[Sheet]:
    """Read a broker export into one Sheet per worksheet, from CSV/TSV or XLSX/XLSM.

    Every worksheet, in workbook order, hidden ones included. A workbook's sheets are
    semantically what its sections are -- an ESPP sheet and a restricted-stock sheet each
    carry their own header and their own width -- so they are kept apart here and mapped
    separately, rather than concatenated into one stream where sheet 2's rows could be
    read against sheet 1's columns.

    Spreadsheet exports are common and re-saving them as CSV is a step users forget, so
    both are read directly. Nothing here interprets the data; that stays in `normalize`.
    """
    lower = path.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        return _read_xlsx_sheets(path)
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return [Sheet(name="", rows=list(csv.reader(fh, dialect)))]


def read_table(path: str) -> list[list[str]]:
    """Every row of every sheet, flat, for detection and for eyeballing a file.

    `normalize` deliberately does not use this: sheet boundaries carry the column layout,
    and flattening them away is how a whole worksheet used to disappear.
    """
    return [row for sheet in read_sheets(path) for row in sheet.rows]


def detect(path: str) -> Detection:
    """Classify one export by its content, never by its filename.

    Filenames are unpredictable -- `Download (3).csv` is the norm -- so the decision is made
    from signature header names and brand strings in the file. The evidence is carried back
    so a misdetection is visible rather than silent.
    """
    try:
        sheets = read_sheets(path)
    except Exception as exc:  # noqa: BLE001 -- report, do not crash the whole run
        return Detection(path, None, 0, None, 0, [], f"could not read the file: {exc}")
    if not any(sheet.rows for sheet in sheets):
        return Detection(path, None, 0, None, 0, [], "file is empty")

    # Headers can sit under a preamble, so consider every early row a header candidate --
    # and do it per worksheet, so a workbook that opens on a disclaimer sheet is still
    # classified by the sheets that hold the data.
    early = [row for sheet in sheets for row in sheet.rows[:40]]
    header_cells = {_norm(cell) for row in early for cell in row if _norm(cell)}
    blob = " ".join(" ".join(cell for cell in row) for row in early).lower()

    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    for broker in PROFILES:
        score = 0
        why: list[str] = []
        for marker in SIGNATURE_HEADERS[broker]:
            if marker in header_cells:
                score += _HEADER_WEIGHT
                why.append(f"header {marker!r}")
        for marker in SIGNATURE_TEXT[broker]:
            if marker in blob:
                score += _TEXT_WEIGHT
                why.append(f"text {marker!r}")
        scores[broker] = score
        evidence[broker] = why

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, best_score = ranked[0]
    second, second_score = ranked[1] if len(ranked) > 1 else (None, 0)

    if best_score == 0:
        return Detection(
            path, None, 0, second, second_score, [],
            "no signature header or brand string matched any known broker",
        )
    if best_score == second_score:
        return Detection(
            path, None, best_score, second, second_score,
            evidence[best] + evidence[second or ""],
            f"ambiguous: {best} and {second} score equally ({best_score})",
        )
    return Detection(path, best, best_score, second, second_score, evidence[best])


def _read_xlsx(path: str) -> list[list[str]]:
    """Backwards-compatible flat read. Prefer `read_sheets`."""
    return [row for sheet in _read_xlsx_sheets(path) for row in sheet.rows]


def _read_xlsx_sheets(path: str) -> list[Sheet]:
    """Minimal XLSX reader: every worksheet, values as strings, dates as ISO.

    Written against the stdlib so the two-dependency rule holds. It handles the parts that
    matter for a broker export -- shared strings, inline strings, and numeric cells whose
    number format makes them dates. Excel stores a date as a day count, so without the
    format lookup every date would arrive as `45678` and be silently unparseable.

    Hidden sheets are read like any other. A sheet nobody looks at is exactly where a
    broker parks the block that matters, and skipping one is not a decision this reader
    gets to make silently -- it is reported in the census instead.
    """
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())

        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in root:
                shared.append("".join(node.text or "" for node in si.iter()
                                      if node.tag.endswith("}t")))

        date_styles = _xlsx_date_styles(archive, names)

        sheets: list[Sheet] = []
        for order, (part, name, hidden) in enumerate(
            _xlsx_sheets(archive, names), start=1
        ):
            root = ET.fromstring(archive.read(part))
            rows: list[list[str]] = []
            for row_node in root.iter():
                if not row_node.tag.endswith("}row"):
                    continue
                cells: dict[int, str] = {}
                for cell in row_node:
                    if not cell.tag.endswith("}c"):
                        continue
                    ref = cell.get("r") or ""
                    index = _xlsx_column_index(ref)
                    cells[index] = _xlsx_cell_value(cell, shared, date_styles)
                if not cells:
                    rows.append([])
                    continue
                width = max(cells) + 1
                rows.append([cells.get(i, "") for i in range(width)])
            sheets.append(Sheet(name=name, rows=rows, index=order, hidden=hidden))
        return sheets


def _xlsx_sheets(archive, names) -> list[tuple[str, str, bool]]:
    """(part name, sheet name, hidden) for every worksheet, in workbook order.

    Workbook order matters: it is the order the user sees the tabs in, so it is the order
    the census reports and the order line numbers are quoted against.
    """
    parts = sorted(n for n in names if n.startswith("xl/worksheets/sheet"))
    if "xl/workbook.xml" not in names:
        return [(part, "", False) for part in parts]
    rels: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in names:
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        for node in rel_root:
            rid = node.get("Id")
            target = (node.get("Target") or "").lstrip("/")
            if rid and "worksheets/sheet" in target:
                rels[rid] = target if target.startswith("xl/") else f"xl/{target}"
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    out: list[tuple[str, str, bool]] = []
    for node in workbook.iter():
        if not node.tag.endswith("}sheet"):
            continue
        part = next(
            (rels[value] for key, value in node.attrib.items()
             if key.endswith("}id") and value in rels),
            None,
        )
        if part is None or part not in names:
            continue
        out.append((part, node.get("name") or "",
                    (node.get("state") or "").lower() in ("hidden", "veryhidden")))
    # A workbook whose relationships cannot be followed still has its sheets in the zip,
    # and losing one to a malformed rels part would be the very failure this fixes.
    seen = {part for part, _name, _hidden in out}
    out.extend((part, "", False) for part in parts if part not in seen)
    return out


# Built-in number format ids that Excel treats as dates or date-times.
_BUILTIN_DATE_FMTS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) \
    | set(range(50, 59))


def _xlsx_date_styles(archive, names) -> set[int]:
    """Style indices whose number format renders as a date."""
    if "xl/styles.xml" not in names:
        return set()
    root = ET.fromstring(archive.read("xl/styles.xml"))
    custom_date_ids = set()
    for node in root.iter():
        if node.tag.endswith("}numFmt"):
            code = (node.get("formatCode") or "").lower()
            stripped = re.sub(r'\[[^\]]*\]|"[^"]*"', "", code)
            if any(ch in stripped for ch in ("y", "d")) and "0.00" not in stripped:
                try:
                    custom_date_ids.add(int(node.get("numFmtId")))
                except (TypeError, ValueError):
                    continue
    out: set[int] = set()
    for parent in root.iter():
        if not parent.tag.endswith("}cellXfs"):
            continue
        for index, xf in enumerate(
            [n for n in parent if n.tag.endswith("}xf")]
        ):
            try:
                fmt = int(xf.get("numFmtId") or 0)
            except ValueError:
                continue
            if fmt in _BUILTIN_DATE_FMTS or fmt in custom_date_ids:
                out.add(index)
    return out


def _xlsx_cell_value(cell, shared, date_styles) -> str:
    cell_type = cell.get("t")
    text = ""
    for node in cell:
        if node.tag.endswith("}v"):
            text = node.text or ""
        elif node.tag.endswith("}is"):
            text = "".join(sub.text or "" for sub in node.iter()
                           if sub.tag.endswith("}t"))
    if cell_type == "s":
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            return text
    if cell_type in ("inlineStr", "str"):
        return text
    if not text:
        return ""
    try:
        style = int(cell.get("s") or -1)
    except ValueError:
        style = -1
    if style in date_styles:
        try:
            # Excel's epoch is 1899-12-30: day 1 is 1900-01-01 and the phantom
            # 1900-02-29 is already absorbed by starting two days early.
            serial = float(text)
            return (
                dt.datetime(1899, 12, 30) + dt.timedelta(days=serial)
            ).date().isoformat()
        except (ValueError, OverflowError):
            return text
    return text


def _xlsx_column_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    index = 0
    for ch in letters.upper():
        index = index * 26 + (ord(ch) - 64)
    return max(index - 1, 0)


def _norm(header: str) -> str:
    return " ".join((header or "").strip().lower().replace("_", " ").split())


_PLACEHOLDER_VALUES = ("", "-", "--", "N/A", "n/a")

# Concepts a section's columns are resolved to. Order is priority order: where one header
# matches two concepts' aliases, the earlier concept claims the column and the later one
# looks elsewhere. Quantity comes after the three specific share counts so that a section
# carrying both "Net Shares" and "Quantity" cannot bind the same column twice.
C_DATE = "date"
C_TICKER = "ticker"
C_TYPE = "type"
C_LOT = "lot"
C_PERIOD = "period"
C_TAX = "tax"
C_WITHHELD = "withheld_qty"
C_NET = "net_qty"
C_SOLD = "sold_qty"
C_QTY = "quantity"
C_PRICE = "price"
C_SALE_PRICE = "sale_price"
C_PAID_PRICE = "paid_price"
C_AMOUNT = "amount"

CONCEPT_ORDER = (C_DATE, C_TICKER, C_TYPE, C_LOT, C_PERIOD, C_TAX, C_WITHHELD, C_NET,
                 C_SOLD, C_QTY, C_PRICE, C_SALE_PRICE, C_PAID_PRICE, C_AMOUNT)

# Concepts whose column must hold a number to be worth binding. A share-count or price
# column that reads 0 on every row of a section states nothing, so a later alias whose
# column actually carries a figure wins it -- which is what keeps a market sell-to-cover
# ("Shares Traded for taxes" = 18, "Withheld Qty." = 0) and a net share settlement (the
# same two columns the other way round) both readable from one alias list.
NUMERIC_CONCEPTS = (C_TAX, C_WITHHELD, C_NET, C_SOLD, C_QTY, C_PRICE, C_SALE_PRICE,
                    C_PAID_PRICE, C_AMOUNT)

# Columns that must never be bound to any concept, whatever a future alias list says.
#
# These are snapshot valuations taken at the export's own run date, not figures about the
# event on the row. "Est. Market Value" on a restricted-stock grant values the UNVESTED
# shares too, so it is neither an amount nor a price and reaching Schedule FA with it
# would report shares that do not exist yet. "Est. Taxable Gain/Loss (per share)" is an
# unrealised gain against a snapshot price -- not a tax figure, not a cost. "Dividend
# Market Value at Release" happens to equal the release-date price on a grant with no
# dividend equivalents, which makes it the most tempting wrong answer in the file.
#
# The two tax totals are here for the same reason in the other direction: C_TAX is the US
# tax withheld on a dividend, which is what Form 67 and Schedule TR relieve. A stock plan's
# withholding total is income tax on a perquisite across several jurisdictions, already
# credited through Form 16, and claiming it as foreign tax on a dividend would be a false
# credit claim.
FORBIDDEN_COLUMNS = frozenset({
    "est. market value", "est market value", "estimated market value",
    "sellable est. market value", "sellable est market value",
    "est. taxable gain/loss (per share):", "est. taxable gain/loss (per share)",
    "est taxable gain/loss (per share)", "est. taxable gain/loss",
    "est taxable gain/loss", "estimated taxable gain/loss",
    "expected gain/loss", "taxable gain", "unrealized gain/loss",
    "unrealised gain/loss", "est. gain/loss", "est gain/loss",
    "dividend market value", "dividend market value at release",
    "total estimated tax withholding", "total taxes paid",
})


def _concept_aliases(profile) -> dict[str, tuple]:
    return {
        C_DATE: profile.date_aliases,
        C_TICKER: profile.ticker_aliases,
        C_TYPE: profile.type_aliases,
        C_LOT: profile.lot_aliases,
        C_PERIOD: profile.period_aliases,
        C_TAX: profile.tax_aliases,
        C_WITHHELD: profile.withheld_aliases,
        C_NET: profile.net_quantity_aliases,
        C_SOLD: profile.sold_quantity_aliases,
        C_QTY: profile.quantity_aliases,
        C_PRICE: profile.price_aliases,
        C_SALE_PRICE: profile.sale_price_aliases,
        C_PAID_PRICE: profile.paid_price_aliases,
        C_AMOUNT: profile.amount_aliases,
    }


def _resolve_columns(profile, headers: list[str], rows: list[list[str]]) -> dict[str, int]:
    """Map each concept to a column INDEX, using only this section's own data rows.

    Indexes rather than names: a stock-plan export routinely repeats a header name inside
    one section -- a nested restricted-stock sheet carries "Sellable Qty." three times and
    "Granted Qty." twice, one copy per record type -- and a name-keyed row dict silently
    keeps only the last of them.

    An alias match whose column is entirely blank or a placeholder ("-", "--") across
    every row of the section is skipped in favour of a later alias whose column has data.
    Some exports carry two columns that both match a profile's aliases -- a generic one
    that is blank for this row type (a bare "Type" left over from a shared template)
    alongside the real one ("Record Type") -- and taking the first alias match
    unconditionally picks whichever happens to be listed first in the alias tuple. That
    silently selects the blank column and makes every row look unparseable. This applies
    to quantity and price as much as to date and type: those two are the fields whose
    absence *drops the row*, which is exactly the failure that must not be silent.

    For a numeric concept the same argument extends one step: a column present but zero
    everywhere is no more informative than a blank one, so an alias whose column carries a
    real figure outranks it. The alias order still decides between two columns that both
    carry figures, which is what keeps an FMV ahead of a purchase price.
    """
    by_alias: dict[str, list[int]] = {}
    for index, cell in enumerate(headers):
        key = _norm(cell)
        if key and key not in FORBIDDEN_COLUMNS:
            by_alias.setdefault(key, []).append(index)

    def cells(index: int):
        for raw in rows:
            if index < len(raw):
                yield (raw[index] or "").strip()

    def has_data(index: int) -> bool:
        return any(cell not in _PLACEHOLDER_VALUES for cell in cells(index))

    def has_number(index: int) -> bool:
        return any((_clean_number(cell) or 0) != 0 for cell in cells(index))

    aliases = _concept_aliases(profile)
    mapping: dict[str, int] = {}
    claimed: set[int] = set()
    for concept in CONCEPT_ORDER:
        present = None      # the header exists, but the column holds nothing at all
        populated = None    # the column holds something
        chosen = None       # the column holds what this concept is for
        wants_number = concept in NUMERIC_CONCEPTS
        for alias in aliases.get(concept, ()):
            for index in by_alias.get(_norm(alias), ()):
                if index in claimed:
                    continue
                if present is None:
                    present = index
                if has_data(index):
                    if populated is None:
                        populated = index
                    if not wants_number or has_number(index):
                        chosen = index
                        break
            if chosen is not None:
                break
        pick = next((i for i in (chosen, populated, present) if i is not None), None)
        if pick is not None:
            mapping[concept] = pick
            claimed.add(pick)
    return mapping


def _clean_number(raw: str) -> Decimal | None:
    raw = (raw or "").strip()
    if not raw or raw in ("-", "--", "N/A", "n/a"):
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    for ch in "()$,%\u20b9 ":
        raw = raw.replace(ch, "")
    raw = raw.replace("USD", "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return -value if negative else value


def _parse_date(raw: str) -> dt.date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    raw = raw.split("T")[0].split(" ")[0] if len(raw) > 10 and (
        "T" in raw or " " in raw
    ) else raw
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%b-%Y", "%b %d, %Y",
                "%m/%d/%y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# A single export row that is both an acquisition and a disposal: shares vest (or an
# option is exercised) and part or all of them is sold in the same event.
KIND_ACQUIRE_AND_DISPOSE = "BUY_AND_SELL"

# A row that states a position or a plan rather than an event: a grant, a withholding-tax
# breakdown, a sellable-shares balance. Not a transaction and not data loss either, so it
# is named in the census as ignored rather than dropped.
KIND_SNAPSHOT = "SNAPSHOT"

# A row whose date cell does not parse is one of three things: a sub-title, a totals line,
# or a data row being read against the wrong section's columns. Only the third is data
# loss, so they are told apart instead of sharing one silent `continue`.
_FOOTER_PREFIXES = ("total", "totals", "grand total", "grand totals", "subtotal",
                    "sub total", "sum", "balance", "ending balance")


@dataclass
class Section:
    """One header row, the data rows under it, and the columns resolved for it."""

    header_line: int
    title: str
    headers: list[str]
    rows: list = field(default_factory=list)          # (line number, raw cells)
    mapping: dict = field(default_factory=dict)       # concept -> column index
    consumed: int = 0                                 # rows that became a transaction
    imported: int = 0                                 # transactions produced
    dropped: list = field(default_factory=list)       # (line, why) -- real data lost
    ignored: list = field(default_factory=list)       # (line, why) -- titles and totals
    sheet: str = ""                                   # worksheet name, "" for a CSV
    # True for the rows above a sheet's first header row: they belong to no column layout,
    # so they are censused but never read as transactions.
    ungoverned: bool = False

    @property
    def accounted_for(self) -> bool:
        """Every row is imported, ignored as boilerplate, or reported as dropped."""
        return len(self.rows) == self.consumed + len(self.ignored) + len(self.dropped)

    @property
    def label(self) -> str:
        # Line numbers restart on every worksheet, so the sheet name is part of naming a
        # row at all once a workbook has more than one.
        where = f"line {self.header_line}"
        if self.sheet:
            where = f"sheet {self.sheet!r} {where}"
        return f"{where} ({self.title})" if self.title else where

    def column(self, concept: str) -> str:
        index = self.mapping.get(concept)
        if index is None:
            return ""
        return self.headers[index] if index < len(self.headers) else ""


@dataclass
class SheetCensus:
    """One worksheet, and what became of it.

    Present for every sheet in the workbook whether or not anything was read from it. A
    sheet that produced nothing is the failure this exists to expose, so it has to appear
    in the report with its own row count rather than be left out of the list.
    """

    name: str
    index: int
    rows: int                                         # non-empty rows in the sheet
    sections: int = 0
    data_rows: int = 0                                # rows sitting under some header
    hidden: bool = False
    skipped: str = ""                                 # why nothing was read from it

    @property
    def label(self) -> str:
        return f"worksheet {self.index} {self.name!r}" if self.name else "the file"


@dataclass
class NormalizeResult:
    """Everything one export turned into, including everything it did not."""

    path: str
    broker: str
    transactions: list[Transaction] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sheets: list[SheetCensus] = field(default_factory=list)

    @property
    def dropped(self) -> list[tuple[Section, int, str]]:
        return [(s, line, why) for s in self.sections for line, why in s.dropped]

    @property
    def rows_seen(self) -> int:
        return sum(len(s.rows) for s in self.sections)

    @property
    def skipped_sheets(self) -> list[SheetCensus]:
        return [s for s in self.sheets if s.skipped]


def normalize(
    path: str,
    broker: str,
    account_id: str,
    default_ticker: str = "",
    acq_kind: str = "",
) -> tuple[list[Transaction], list[str]]:
    """Read a broker export into Transactions. Returns (transactions, warnings)."""
    result = normalize_report(path, broker, account_id, default_ticker, acq_kind)
    return result.transactions, result.warnings


def normalize_report(
    path: str,
    broker: str,
    account_id: str,
    default_ticker: str = "",
    acq_kind: str = "",
) -> NormalizeResult:
    """As `normalize`, but keeping the per-section census of what was and was not read.

    Callers that can render it should use this: the census is the only thing that makes a
    dropped row visible, and a Schedule FA missing a vest is a Black Money Act s.43
    exposure of Rs 10,00,000 per assessment year.
    """
    if broker not in PROFILES:
        raise DataError(
            f"unknown broker {broker!r}; choose from {', '.join(sorted(PROFILES))}"
        )
    profile = PROFILES[broker]
    if not os.path.exists(path):
        raise DataError(f"broker export not found: {path}")

    # Stock-plan exports carry preamble lines before the real header, and then repeat the
    # exercise for every plan type or grant, so headers are located by content throughout
    # the file rather than once at the top. A workbook repeats it again per worksheet,
    # each with its own header and its own width, so every sheet is cut up on its own.
    sheets = read_sheets(path)
    sections: list[Section] = []
    census: list[SheetCensus] = []
    for sheet in sheets:
        entry = SheetCensus(name=sheet.name, index=sheet.index,
                            rows=sheet.populated_rows, hidden=sheet.hidden)
        census.append(entry)
        found, orphans = _split_sections(sheet.rows, profile, sheet.name)
        if orphans:
            found.insert(0, _orphan_section(orphans, sheet.name))
        if not found:
            entry.skipped = (
                "the worksheet holds no data at all" if not sheet.populated_rows else
                "no header row naming any column this profile recognises, and no row "
                "that parses as a transaction"
            )
            continue
        entry.sections = len(found)
        entry.data_rows = sum(len(s.rows) for s in found)
        sections.extend(found)

    if not any(C_DATE in s.mapping for s in sections):
        raise DataError(
            f"{path}: could not find a header row containing a recognisable date column "
            f"for the '{broker}' profile.\n"
            f"Looked for any of: {', '.join(profile.date_aliases)}\n"
            + (
                "Header rows found, none with a date column:\n  "
                + "\n  ".join(f"{s.label}: {', '.join(s.headers)}"
                              for s in [s for s in sections if s.headers][:6])
                if any(s.headers for s in sections) else
                _render_sheets(sheets)
            )
            + "\n\nIf this export genuinely uses different names, either rename the "
            "columns or fill the intermediate transactions.csv by hand "
            "(see README data dictionary)."
        )

    quantity_concepts = (C_QTY, C_NET, C_WITHHELD, C_SOLD)
    if not any(c in s.mapping for s in sections for c in quantity_concepts):
        share_counts = ", ".join(
            profile.net_quantity_aliases + profile.withheld_aliases
            + profile.sold_quantity_aliases
        )
        raise DataError(
            f"{path}: the '{broker}' adapter could not find a quantity column in any "
            f"section.\n  Looked for any of: {', '.join(profile.quantity_aliases)}\n"
            f"  or a net/withheld/sold share count: "
            f"{share_counts or '(none defined)'}\n\n"
            + _render_headers(sections)
            + "\nFix by renaming the column in the export, or hand-fill "
            "transactions.csv instead (README data dictionary)."
        )
    if not default_ticker and not any(C_TICKER in s.mapping for s in sections):
        raise DataError(
            f"{path}: the '{broker}' adapter could not find a ticker column in any "
            f"section.\n  Looked for any of: {', '.join(profile.ticker_aliases)}\n"
            f"  -- or pass --default-ticker for a single-stock plan export.\n\n"
            + _render_headers(sections)
        )

    result = NormalizeResult(path=path, broker=broker, sections=sections, sheets=census)
    for section in sections:
        if section.ungoverned:
            continue
        _read_section(section, result, profile, broker, account_id,
                      default_ticker, acq_kind)

    for entry in result.skipped_sheets:
        # Named, not merely absent. A worksheet nothing was read from is either boilerplate
        # or the whole Restricted Stock block, and only the user can tell which.
        result.warnings.append(
            f"{path}: nothing was read from {entry.label} ({entry.rows} non-empty "
            f"row(s)): {entry.skipped}. If that sheet holds transactions, its header row "
            f"needs a recognisable date and quantity column, or add its rows to "
            f"transactions.csv by hand."
        )

    if not result.transactions:
        raise DataError(
            f"{path}: the '{broker}' adapter recognised {len(sections)} header row(s) "
            f"but produced no usable transactions from {result.rows_seen} data row(s).\n\n"
            + render_report(result)
            + "\n\nCheck the mapping above, or hand-fill transactions.csv."
        )
    result.warnings = _summarise(result) + result.warnings
    return result


def _orphan_section(orphans, sheet: str) -> Section:
    """Rows above the first header, which no column layout governs.

    Reported rather than dropped where nobody looks: an export that leads with data would
    otherwise lose exactly the rows this exists to keep. A row is only counted as lost if
    it looks like a transaction; prose and glossary lines in an instructions sheet are
    named as ignored instead, so boilerplate cannot block a run.
    """
    stray = Section(header_line=orphans[0][0], title="before the first header row",
                    headers=[], sheet=sheet, ungoverned=True)
    stray.rows = list(orphans)
    for line, raw in orphans:
        if _looks_like_data(raw):
            stray.dropped.append(
                (line, "row sits above the first header row, so no column layout applies "
                       "to it; if it is a transaction, move the header row above it")
            )
        else:
            stray.ignored.append(
                (line, "text above the first header row, with no date and no figure in "
                       "it, so it is not a transaction")
            )
    return stray


def _render_headers(sections) -> str:
    return "Header row(s) found:\n" + "\n".join(
        f"  {s.label}: {', '.join(s.headers)}"
        for s in [s for s in sections if s.headers][:6]
    ) + "\n"


def _render_sheets(sheets) -> str:
    lines = []
    for sheet in sheets:
        lines.append(f"  {sheet.label}, {sheet.populated_rows} non-empty row(s):")
        for raw in [r for r in sheet.rows if any((c or "").strip() for c in r)][:3]:
            lines.append("    " + ",".join(raw)[:100])
    return "What the file does hold:\n" + "\n".join(lines)


def _split_sections(rows, profile,
                    sheet: str = "") -> tuple[list[Section], list[tuple[int, list]]]:
    """Cut one sheet into sections, one per header row, and map each section's columns.

    Text above a header becomes that section's title, which is what lets a warning say
    "the ESPP block", not just "line 41". Returns the sections plus any wide row found
    before the first header, which belongs to no layout and so is reported, not dropped.

    Line numbers are counted within the sheet, so `sheet` travels with them: "line 3" in a
    two-sheet workbook names two different rows.
    """
    date_aliases = {_norm(a) for a in profile.date_aliases}
    every_alias = {
        _norm(a) for aliases in _concept_aliases(profile).values() for a in aliases
    }
    sections: list[Section] = []
    pending: list[str] = []
    orphans: list[tuple[int, list]] = []
    current: Section | None = None
    for lineno, raw in enumerate(rows, start=1):
        if not any((c or "").strip() for c in raw):
            continue
        if _looks_like_header(raw, date_aliases, every_alias):
            current = Section(
                header_line=lineno,
                title=pending[-1] if pending else "",
                headers=list(raw),
                sheet=sheet,
            )
            sections.append(current)
            pending = []
            continue
        if current is None:
            # Nothing above the first header row has a column layout. A row that looks
            # like a transaction is reported as lost; anything else is the preamble, and
            # becomes a candidate title for the section that follows.
            if _looks_like_data(raw):
                orphans.append((lineno, raw))
            else:
                pending.append(_title_text(raw))
            continue
        if _is_title_line(raw):
            pending.append(_title_text(raw))
            continue
        current.rows.append((lineno, raw))
    for section in sections:
        section.mapping = _resolve_columns(
            profile, section.headers, [raw for _, raw in section.rows]
        )
    return sections, orphans


def _title_text(raw) -> str:
    return " ".join(c.strip() for c in raw if (c or "").strip())[:60]


def _looks_like_data(raw) -> bool:
    """A row carrying both a date and a figure, wherever they sit.

    Used where no header governs the row, so nothing better than the row's own shape is
    available. A disclaimer or a glossary line has neither; a transaction has both.
    """
    cells = [c.strip() for c in raw if (c or "").strip()]
    return (any(_parse_date(c) for c in cells)
            and any(_clean_number(c) is not None for c in cells))


def _looks_like_header(raw, date_aliases, every_alias) -> bool:
    """True when a row names columns rather than holding values.

    Two populated cells minimum, at least one recognisable column name, and nothing in
    the row that parses as a date. That last test is what keeps a section splitter from
    truncating an ordinary single-section export: a data row always carries its own date.
    """
    cells = [_norm(c) for c in raw if _norm(c)]
    if len(cells) < 2:
        return False
    named = sum(1 for c in cells if c in every_alias)
    if not any(c in date_aliases for c in cells) and named < 3:
        return False
    return not any(_parse_date(c) for c in raw if (c or "").strip())


def _is_title_line(raw) -> bool:
    """The band of text a stock-plan export puts between blocks -- "ESPP Purchases".

    It names the section that follows, so it must not be counted against the section
    above. A real data row is protected by carrying a parseable date, and a short totals
    line is excluded so it still shows up in the census as the footer it is.
    """
    populated = [c.strip() for c in raw if (c or "").strip()]
    if len(populated) >= 3:
        return False
    if _norm(populated[0] if populated else "").startswith(_FOOTER_PREFIXES):
        return False
    return not any(_parse_date(c) for c in populated)


def _cell(raw, mapping, concept) -> str:
    index = mapping.get(concept)
    if index is None or index >= len(raw):
        return ""
    return raw[index] or ""


@dataclass
class _Nesting:
    """What a child row in a nested export inherits from its parent rows.

    A "By Benefit Type" restricted-stock sheet states each fact once, on the row that owns
    it: the symbol on the `Grant` row, the shares and dates on the `Vest Schedule` row, the
    per-share cost basis on the `Sellable Shares` row for that tranche. Every one of them
    is tied to the others by grant number, so the vest row is only readable together with
    its siblings. Resolving them by grant number rather than by adjacency is what keeps a
    reordered or partly-filtered export readable.
    """

    ticker_by_lot: dict = field(default_factory=dict)
    basis: dict = field(default_factory=dict)          # (lot, period) -> per-share basis
    tickers: set = field(default_factory=set)


def _index_nesting(section, profile) -> _Nesting:
    mapping = section.mapping
    out = _Nesting()
    ambiguous: set = set()
    for _lineno, raw in section.rows:
        ticker = _cell(raw, mapping, C_TICKER).strip().upper()
        lot_id = _cell(raw, mapping, C_LOT).strip()
        if ticker:
            out.tickers.add(ticker)
            if lot_id and out.ticker_by_lot.setdefault(lot_id, ticker) != ticker:
                out.ticker_by_lot.pop(lot_id, None)
        kind = _classify(_norm(_cell(raw, mapping, C_TYPE).strip()), profile)
        if kind != KIND_SNAPSHOT:
            continue
        # Only a position row donates a per-share basis. Letting one transaction row hand
        # its price to another would paper over exactly the mis-columned read that the
        # per-section mapping exists to catch.
        basis = _abs(_clean_number(_cell(raw, mapping, C_PRICE)))
        if not basis or basis <= 0 or not lot_id:
            continue
        period = _cell(raw, mapping, C_PERIOD).strip()
        for key in {(lot_id, period), (lot_id, "")}:
            if key in ambiguous:
                continue
            if out.basis.setdefault(key, basis) != basis:
                # Two positions of one tranche disagreeing is not something to average or
                # to guess between: the rows that would have used it are dropped instead.
                out.basis.pop(key, None)
                ambiguous.add(key)
    return out


def _read_section(section, result, profile, broker, account_id,
                  default_ticker, acq_kind) -> None:
    path = result.path
    mapping = section.mapping
    warn = result.warnings.append

    if C_DATE not in mapping:
        # Not fatal for the file, but every row here is lost, so say so once with the
        # count rather than once per row.
        for lineno, _raw in section.rows:
            section.dropped.append(
                (lineno, f"the section starting at {section.label} has no recognisable "
                         f"date column, so no row in it can be dated")
            )
        return
    if C_TICKER not in mapping and not default_ticker:
        for lineno, _raw in section.rows:
            section.dropped.append(
                (lineno, f"the section starting at {section.label} has no ticker column "
                         f"and no --default-ticker was given")
            )
        return

    if C_PRICE not in mapping and C_SALE_PRICE not in mapping:
        warn(f"{path} {section.label}: no per-share price column; price will be derived "
             f"from amount/quantity where an amount is present")
    if C_TYPE not in mapping:
        warn(f"{path} {section.label}: no transaction-type column, so every row here is "
             f"treated as an acquisition (BUY). Check the output for missed sales.")

    paid_price_columns = {_norm(a) for a in profile.paid_price_aliases}
    priced_from_paid = _norm(section.column(C_PRICE)) in paid_price_columns

    nesting = _index_nesting(section, profile)
    derived_gross: list[int] = []
    total_as_price: list[int] = []
    inherited_ticker: list[int] = []
    inherited_basis: list[int] = []
    paid_as_basis: list[int] = []

    for lineno, raw in section.rows:
        day = _parse_date(_cell(raw, mapping, C_DATE))
        type_raw = _cell(raw, mapping, C_TYPE).strip()
        kind = _classify(_norm(type_raw), profile)

        if kind == KIND_SNAPSHOT:
            # Checked before the date, because a position row is dated by the export at
            # whatever it is a position *as of*, which is often nowhere on the row.
            section.ignored.append((
                lineno,
                f"record type {type_raw!r} states a position or a plan, not a share "
                f"event, so it is not a transaction",
            ))
            continue

        if day is None:
            populated = [_norm(c) for c in raw if (c or "").strip()]
            is_footer = bool(populated) and populated[0].startswith(_FOOTER_PREFIXES)
            if is_footer:
                section.ignored.append((lineno, "totals/footer line"))
            elif len(populated) < 3:
                section.ignored.append((lineno, "sub-title or spacer line"))
            else:
                section.dropped.append((
                    lineno,
                    f"date column {section.column(C_DATE)!r} holds "
                    f"{_cell(raw, mapping, C_DATE).strip()!r}, which is not a date -- "
                    f"this row is laid out differently from its section's header",
                ))
            continue

        if kind is None:
            section.dropped.append((
                lineno,
                f"row type {type_raw!r} is not recognised as an acquisition, a disposal "
                f"or a dividend. Add it to the '{broker}' profile's markers, or add the "
                f"row to transactions.csv by hand.",
            ))
            continue

        lot_id = _cell(raw, mapping, C_LOT).strip()
        period = _cell(raw, mapping, C_PERIOD).strip()
        ticker = _cell(raw, mapping, C_TICKER).strip().upper()
        if not ticker:
            # A nested sheet names the symbol once, on the award row, and leaves it off
            # every vest under it. Taking it from the award the row names -- or from the
            # only symbol in the section -- beats dropping a real vest for the want of a
            # cell the export never repeats.
            inherit = nesting.ticker_by_lot.get(lot_id) or (
                next(iter(nesting.tickers)) if len(nesting.tickers) == 1 else ""
            )
            if inherit:
                ticker = inherit
                inherited_ticker.append(lineno)
        ticker = ticker or default_ticker.upper()
        if not ticker:
            section.dropped.append((lineno, "no ticker in the row"))
            continue

        gross = _abs(_clean_number(_cell(raw, mapping, C_QTY)))
        withheld = _abs(_clean_number(_cell(raw, mapping, C_WITHHELD)))
        net = _abs(_clean_number(_cell(raw, mapping, C_NET)))
        sold = _abs(_clean_number(_cell(raw, mapping, C_SOLD)))
        price = _abs(_clean_number(_cell(raw, mapping, C_PRICE)))
        sale_price = _abs(_clean_number(_cell(raw, mapping, C_SALE_PRICE)))
        paid_price = _abs(_clean_number(_cell(raw, mapping, C_PAID_PRICE)))
        amount = _abs(_clean_number(_cell(raw, mapping, C_AMOUNT)))
        tax = _abs(_clean_number(_cell(raw, mapping, C_TAX))) or Decimal(0)
        notes = f"{broker}:{type_raw}".strip(":")

        if kind == TXN_DIVIDEND:
            if amount is None:
                section.dropped.append((lineno, "dividend row carries no amount"))
                continue
            result.transactions.append(Transaction(
                account_id=account_id, ticker=ticker, txn_type=TXN_DIVIDEND, date=day,
                quantity=Decimal(0), price_usd=Decimal(0), amount_usd=amount,
                tax_withheld_usd=tax, lot_id=lot_id, notes=notes,
                source_row=lineno, source_file=path,
            ))
            section.consumed += 1
            section.imported += 1
            continue

        if kind == TXN_SELL:
            qty = sold if (sold and sold > 0) else gross
            if not qty or qty <= 0:
                where = section.column(C_SOLD) or section.column(C_QTY)
                if _states_nil_shares(raw, mapping):
                    section.ignored.append((lineno, _nil_reason(section, mapping)))
                    continue
                section.dropped.append((
                    lineno,
                    "disposal has no positive share count in "
                    + (f"column {where!r}" if where
                       else "any column this section maps to a quantity"),
                ))
                continue
            # A sale is worth what it executed at. An FMV column in the same section
            # describes the acquisition, so it is only the fallback.
            realised = sale_price if (sale_price and sale_price > 0) else price
            priced = _price_for(realised, amount, qty)
            if priced is None:
                section.dropped.append((
                    lineno, f"disposal of {qty} {ticker} has neither a price nor an "
                            f"amount, so its value cannot be established",
                ))
                continue
            result.transactions.append(Transaction(
                account_id=account_id, ticker=ticker, txn_type=TXN_SELL, date=day,
                quantity=qty, price_usd=priced, amount_usd=amount,
                tax_withheld_usd=tax, lot_id=lot_id, notes=notes,
                source_row=lineno, source_file=_source(path, section),
            ))
            section.consumed += 1
            section.imported += 1
            if _price_is_a_total(realised, amount, qty):
                total_as_price.append(lineno)
            continue

        # -- acquisition, with or without a same-event disposal --------------
        if gross is None and net is not None:
            # No gross column. Without a withheld count the export cannot state the gross
            # figure at all, and s.17(1)(d) of the Act of 2025 charges the perquisite on
            # gross, so the
            # result is a floor rather than an answer -- warned about below.
            gross = net + (withheld or Decimal(0))
            if withheld is None:
                derived_gross.append(lineno)
        if gross is None and kind == KIND_ACQUIRE_AND_DISPOSE and sold is not None:
            gross = sold
        if gross is None or gross <= 0:
            if _states_nil_shares(raw, mapping):
                # The export states, in figures, that nothing was acquired: an unvested
                # tranche of a vesting schedule, or one that was cancelled. An unvested RSU
                # is a contingent right with no shares in existence, so there is nothing
                # for Schedule FA to hold -- but it is said out loud, because reading 0
                # from the WRONG column is how a real vest went missing before.
                section.ignored.append((lineno, _nil_reason(section, mapping)))
                continue
            concept = C_QTY if C_QTY in mapping else C_NET
            where = section.column(concept)
            section.dropped.append((
                lineno,
                "acquisition row has no positive share count in "
                + (f"column {where!r}, which reads "
                   f"{_cell(raw, mapping, concept).strip()!r}" if where
                   else "any column this section maps to a quantity")
                + ". A gross, net or withheld share count is needed to size the "
                  "acquisition.",
            ))
            continue
        priced = _price_for(price, amount, gross)
        basis_note = ""
        if priced is None:
            # A nested export states the per-share basis on the tranche's position row, not
            # on the vest row, so the vest is only priceable together with its sibling.
            priced = (nesting.basis.get((lot_id, period))
                      or nesting.basis.get((lot_id, "")))
            if priced is not None:
                inherited_basis.append(lineno)
                basis_note = (f" (per-share basis {priced} from this award's "
                              f"{section.column(C_PRICE) or 'cost basis'} row)")
        if priced is None:
            section.dropped.append((
                lineno,
                f"acquisition of {gross} {ticker} has neither a price nor an amount, so "
                f"its cost basis cannot be established. Add the vest-date fair market "
                f"value to transactions.csv by hand.",
            ))
            continue
        if _price_is_a_total(price, amount, gross):
            total_as_price.append(lineno)
        if priced_from_paid:
            paid_as_basis.append(lineno)

        result.transactions.append(Transaction(
            account_id=account_id, ticker=ticker, txn_type=TXN_BUY, date=day,
            quantity=gross, price_usd=priced, amount_usd=amount,
            tax_withheld_usd=tax,
            paid_price_usd=(paid_price if paid_price and paid_price != priced
                            else Decimal(0)),
            acq_kind=_acq_kind(_norm(type_raw), profile, acq_kind),
            lot_id=lot_id, notes=notes + basis_note,
            source_row=lineno, source_file=_source(path, section),
        ))
        section.consumed += 1
        section.imported += 1

        # The withheld or same-day-sold portion is a real transfer of a foreign share:
        # gross belongs in Schedule FA as acquired, and the portion that never reached the
        # employee belongs there as disposed and in Schedule CG as a near-nil-gain sale.
        disposed = withheld
        if disposed is None and sold is not None and kind == KIND_ACQUIRE_AND_DISPOSE:
            disposed = sold
        if disposed is None and net is not None and net < gross:
            disposed = gross - net
        if disposed is not None and disposed > gross:
            warn(f"{path} line {lineno}: {disposed} shares disposed of but only {gross} "
                 f"acquired; the disposal was capped at the acquisition. Check the row.")
            disposed = gross
        if kind == KIND_ACQUIRE_AND_DISPOSE and not disposed:
            warn(f"{path} line {lineno}: {type_raw!r} says shares were sold in the same "
                 f"event, but the section has no withheld/net/sold share count, so the "
                 f"disposal could not be sized. All {gross} shares were recorded as "
                 f"acquired and none as sold -- add the sold portion to "
                 f"transactions.csv by hand or Schedule CG will miss it.")
        if disposed and disposed > 0:
            result.transactions.append(Transaction(
                account_id=account_id, ticker=ticker, txn_type=TXN_SELL, date=day,
                quantity=disposed, price_usd=priced,
                amount_usd=(priced * disposed),
                disposal_kind=DISPOSAL_TAX_WITHHOLDING,
                lot_id=lot_id,
                notes=f"{notes} (shares withheld/sold at acquisition)",
                source_row=lineno, source_file=_source(path, section),
            ))
            section.imported += 1

    # Only rows that became transactions are worth warning about: a vesting schedule's
    # unvested tranches carry no symbol either, and they are already accounted for.
    unused = ({line for line, _why in section.ignored}
              | {line for line, _why in section.dropped})
    inherited_ticker = [line for line in inherited_ticker if line not in unused]
    if inherited_ticker:
        warn(f"{path} {section.label}: {len(inherited_ticker)} row(s) carry no symbol "
             f"(first at line {inherited_ticker[0]}) and took it from the award row they "
             f"belong to. Check the ticker on those rows if this export covers more than "
             f"one security.")
    if inherited_basis:
        warn(f"{path} {section.label}: {len(inherited_basis)} row(s) state no per-share "
             f"value of their own (first at line {inherited_basis[0]}) and were priced "
             f"from the {section.column(C_PRICE)!r} figure on the same award's position "
             f"row. That column is the broker's own cost basis, which for a vest is the "
             f"FMV the perquisite is charged on -- s.17(1)(d) of the Income-tax Act, 2025, "
             f"s.17(2)(vi) of the 1961 Act. Confirm it against your Form 16 part B / 12BA "
             f"before filing.")
    if paid_as_basis:
        warn(f"{path} {section.label}: {len(paid_as_basis)} acquisition(s) were priced "
             f"from {section.column(C_PRICE)!r}, which is what was PAID, because the "
             f"section carries no fair-market-value column. The cost of acquisition is "
             f"the FMV the perquisite was charged on -- s.73(1) with s.17(1)(d) of the "
             f"Income-tax Act, 2025, s.49(2AA) with s.17(2)(vi) of the 1961 Act; the "
             f"discount has already been taxed as salary through Form 16, "
             f"so using the paid price taxes it a second time as capital gain. Re-export "
             f"with the purchase-date FMV column, or correct price_usd by hand.")
    if derived_gross:
        warn(f"{path} {section.label}: {len(derived_gross)} row(s) state only a net share "
             f"count with no withheld-share column (first at line {derived_gross[0]}), so "
             f"gross was taken to equal net. The perquisite is charged on "
             f"GROSS shares, so those rows are a floor. Re-export with the "
             f"'Tax Collection Shares'/'Shares Withheld' column to close it.")
    if total_as_price:
        # A section with no acquisition-price column at all is priced from its sale-price
        # one, and naming the column that is not there would send the reader nowhere.
        priced_by = section.column(C_PRICE) or section.column(C_SALE_PRICE)
        warn(f"{path} {section.label}: the price column {priced_by!r} equals "
             f"the row's total value on {len(total_as_price)} row(s) (first at line "
             f"{total_as_price[0]}), so it looks like a row total rather than a per-share "
             f"figure. Cost basis would be overstated by the share count. Rename the "
             f"real per-share column to 'Market Value Per Share' and re-run.")


def _abs(value):
    return None if value is None else abs(value)


_SHARE_COUNT_CONCEPTS = (C_QTY, C_NET, C_WITHHELD, C_SOLD)


def _states_nil_shares(raw, mapping) -> bool:
    """True when the row says, in figures, that no shares changed hands.

    An explicit zero is information; a blank is a failure to read. So this needs one share
    count actually written as zero and no positive count anywhere else in the row. That
    distinction is what stops this from re-hiding the old bug, where a quantity was read as
    0 out of the wrong column while the real count sat in the next one along.
    """
    saw_zero = False
    for concept in _SHARE_COUNT_CONCEPTS:
        if concept not in mapping:
            continue
        value = _clean_number(_cell(raw, mapping, concept))
        if value is None:
            continue
        if value != 0:
            return False
        saw_zero = True
    return saw_zero


def _nil_reason(section, mapping) -> str:
    columns = ", ".join(
        repr(section.column(c)) for c in _SHARE_COUNT_CONCEPTS if c in mapping
    )
    return (f"the row states 0 shares in {columns}, so nothing was acquired or disposed "
            f"of -- an unvested or cancelled tranche")


def _source(path: str, section) -> str:
    """Where a transaction came from, precise enough to find again.

    Line numbers restart per worksheet, so a workbook needs the sheet name to make
    "line 3" mean one row. Left exactly as the path for a CSV.
    """
    return f"{path}[{section.sheet}]" if section.sheet else path


def _price_for(price, amount, qty):
    if price is not None and price > 0:
        return price
    if amount and qty:
        return amount / qty
    return None


def _price_is_a_total(price, amount, qty) -> bool:
    """A per-share column that actually holds the row total.

    Real exports name the vest FMV "Market Value", and the same word names a row total.
    With a quantity above one the two are far apart, so if the "price" cell matches the
    amount cell it is the total and every cost basis from that column is wrong by the
    share count.
    """
    if price is None or amount is None or price <= 0 or amount <= 0 or qty <= 1:
        return False
    return abs(price - amount) <= amount * Decimal("0.005")


def _acq_kind(type_text: str, profile, override: str) -> str:
    """How the shares were acquired, from the row's own type text.

    Informational for Schedule FA, but `doctor` uses it to recognise an employer
    stock-plan account, which is what lets it notice one contributing too few rows.

    The row wins over the caller's `--acq-kind` where it states a plan type, because one
    stock-plan export holds RSU, ESPP and deposit sections and a per-file flag cannot be
    right for all of them. The flag still decides the rows that say nothing.
    """
    for kind, markers in profile.acq_kind_markers:
        if any(marker in type_text for marker in markers):
            return kind
    return override or profile.acq_kind_default


def _summarise(result: NormalizeResult) -> list[str]:
    """The census, first in the warning list so a truncated view still shows it."""
    dropped = result.dropped
    if not dropped:
        return []
    return [
        f"{len(dropped)} of {result.rows_seen} data row(s) in {result.path} were NOT "
        f"imported. An incomplete Schedule FA understates a foreign-asset disclosure, "
        f"which Black Money Act s.43 penalises at Rs 10,00,000 per assessment year. "
        f"Every dropped row is listed below; add it to transactions.csv by hand if it "
        f"is a real acquisition or disposal."
    ]


def render_report(result: NormalizeResult) -> str:
    """The census: every worksheet, then what each section mapped, read and could not read.

    The worksheet block is printed whenever a file has more than one, so a sheet that
    contributed nothing is visible as a named line with its row count rather than as an
    absence. That absence is what let a whole Restricted Stock sheet go missing.
    """
    multi_sheet = len(result.sheets) > 1 or bool(result.skipped_sheets)
    lines = [f"{result.path} -- '{result.broker}' profile, "
             + (f"{len(result.sheets)} worksheet(s), " if multi_sheet else "")
             + f"{len(result.sections)} section(s)"]
    if multi_sheet:
        for sheet in result.sheets:
            detail = (f"SKIPPED: {sheet.skipped}" if sheet.skipped else
                      f"{sheet.data_rows} data row(s) in {sheet.sections} section(s)")
            lines.append(
                f"  {sheet.label}{' (hidden)' if sheet.hidden else ''}: "
                f"{sheet.rows} non-empty row(s), {detail}"
            )
    for section in result.sections:
        lines.append(
            f"  {section.label}: {len(section.rows)} data row(s) -> "
            f"{section.consumed} read as {section.imported} transaction(s), "
            f"{len(section.dropped)} DROPPED, "
            f"{len(section.ignored)} ignored (titles/totals)"
        )
        mapped = ", ".join(
            f"{concept}={section.column(concept)!r}"
            for concept in CONCEPT_ORDER if concept in section.mapping
        )
        lines.append(f"    columns: {mapped or '(none recognised)'}")
        for line, why in section.dropped[:20]:
            lines.append(f"    DROPPED line {line}: {why}")
        if len(section.dropped) > 20:
            lines.append(f"    ... and {len(section.dropped) - 20} more dropped row(s)")
        # Grouped, because a vesting schedule contributes a dozen identical unvested
        # tranches and one line each would bury the sections that matter.
        for why, count in _group(section.ignored).items():
            lines.append(f"    ignored {count} row(s): {why}")
    return "\n".join(lines)


def _group(entries) -> dict[str, int]:
    out: dict[str, int] = {}
    for _line, why in entries:
        out[why] = out.get(why, 0) + 1
    return out


def _classify(type_text: str, profile) -> str | None:
    """A row's type text -> TXN_*, KIND_ACQUIRE_AND_DISPOSE, KIND_SNAPSHOT, or None.

    None means unrecognised, and every caller reports it: a row type nobody taught this
    profile about is the single most likely way for a real vest to go missing.
    """
    if not type_text:
        return TXN_BUY  # no type column: assume acquisition, warned about by caller
    # Whole-cell matches, and first: "Sellable Shares" contains "sell", so a substring
    # pass would read a position row as a disposal of the entire sellable balance, and
    # "Grant" would be lost to the unrecognised-type drop instead of being understood.
    if type_text in profile.snapshot_markers:
        return KIND_SNAPSHOT
    for marker in profile.dividend_markers:
        if marker in type_text:
            return TXN_DIVIDEND
    # A row that is both halves must be recognised before either one, or the sell markers
    # claim "vest and sell to cover" and the acquisition is lost while a phantom disposal
    # of never-separately-held shares is invented.
    for marker in profile.acquire_and_dispose_markers:
        if marker in type_text:
            return KIND_ACQUIRE_AND_DISPOSE
    for marker in profile.sell_markers:
        if marker in type_text:
            return TXN_SELL
    for marker in profile.buy_markers:
        if marker in type_text:
            return TXN_BUY
    return None
