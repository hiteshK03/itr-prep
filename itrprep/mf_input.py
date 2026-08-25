"""Reading the mutual fund intermediate CSVs into capgain ledgers.

Two files, both templates of ``itr-prep init``:

* ``mf_schemes.csv`` -- one row per scheme the ledger touches, declaring what no
  statement can supply: the section 198(8) classification (equity-oriented or other)
  and, for any scheme with units acquired before the grandfathering cutoff, the fair
  market value per unit as on the registry's valuation date. These are the caller's
  readings of primary sources -- the fund's stated asset mix, and the highest quoted
  price on the valuation date (or the NAV, for an unlisted scheme) -- and the engine
  refuses to guess either.

* ``mf_transactions.csv`` -- the ledger itself: purchases, bonus allotments and sales,
  one row each. This is where a CAMS or KFintech consolidated statement gets
  transcribed from. The columns are deliberately the ones a statement actually
  carries: a date, units, a NAV or price, and a transaction type. Transcribing by
  hand is auditable line by line; a statement parser may come later, but it would be
  sugar over this file, not a replacement.

Every value is read as text and handed to ``itrprep/capgain.py``, which owns the
Decimal discipline and every refusal. Nothing here invents a figure.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import capgain
from .capgain import Bonus, Engine, Ledger, Purchase, Sale, SchemeDecl

SCHEMES_COLUMNS = ["isin", "name", "classification", "listed", "fmv_2018_01_31"]
TRANSACTIONS_COLUMNS = ["isin", "type", "date", "units", "price", "transfer_expense",
                        "source_ref"]

TYPE_PURCHASE = "purchase"
TYPE_BONUS = "bonus"
TYPE_SALE = "sale"
_TYPES = {TYPE_PURCHASE, TYPE_BONUS, TYPE_SALE}

EXAMPLE_SCHEMES = [
    {
        "isin": "INF123F01000", "name": "SYNTHETIC EQUITY FUND TEST SCHEME",
        "classification": capgain.EQUITY_ORIENTED, "listed": "yes",
        "fmv_2018_01_31": "",
    },
    {
        "isin": "INF123F01001", "name": "SYNTHETIC GRANDFATHERED FUND TEST SCHEME",
        "classification": capgain.EQUITY_ORIENTED, "listed": "yes",
        "fmv_2018_01_31": "45.1200",
    },
]
EXAMPLE_TRANSACTIONS = [
    {
        "isin": "INF123F01000", "type": TYPE_PURCHASE, "date": "2025-08-01",
        "units": "200", "price": "40.0000", "transfer_expense": "",
        "source_ref": "example row - delete me. NAV from the CAMS statement",
    },
    {
        "isin": "INF123F01000", "type": TYPE_SALE, "date": "2026-09-01",
        "units": "200", "price": "52.0000", "transfer_expense": "120.50",
        "source_ref": "example row - delete me. Exit charges if the statement lists them",
    },
    {
        "isin": "INF123F01001", "type": TYPE_PURCHASE, "date": "2017-06-01",
        "units": "100", "price": "30.0000", "transfer_expense": "",
        "source_ref": "example row - delete me. Pre-cutoff scheme: declare its FMV above",
    },
    {
        "isin": "INF123F01001", "type": TYPE_SALE, "date": "2026-05-10",
        "units": "100", "price": "60.0000", "transfer_expense": "",
        "source_ref": "example row - delete me",
    },
]
_TRUE = {"yes", "y", "true", "1", "listed"}
_FALSE = {"no", "n", "false", "0", "unlisted"}


class MfInputError(Exception):
    """A malformed row, with its file, line and reason in one message."""


def _parse_date(raw: str, where: str) -> dt.date:
    try:
        return dt.date.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        raise MfInputError(f"{where}: date {raw!r} is not ISO YYYY-MM-DD")


def _parse_decimal(raw: str, where: str) -> Decimal:
    try:
        return Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        raise MfInputError(f"{where}: {raw!r} is not a number")


def _parse_bool(raw: str, where: str) -> bool:
    token = (raw or "").strip().lower()
    if token in _TRUE:
        return True
    if token in _FALSE:
        return False
    raise MfInputError(f"{where}: listed {raw!r} must be yes/no")


def load_schemes(path: str) -> dict[str, SchemeDecl]:
    """Read ``mf_schemes.csv`` into isin -> SchemeDecl.

    An empty file is fine -- a portfolio with no mutual fund activity has nothing to
    declare. A row with anything missing is not.
    """
    schemes: dict[str, SchemeDecl] = {}
    if not os.path.exists(path):
        return schemes
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for line, raw in enumerate(reader, start=2):
            where = f"{os.path.basename(path)} line {line}"
            isin = (raw.get("isin") or "").strip()
            name = (raw.get("name") or "").strip()
            classification = (raw.get("classification") or "").strip().lower()
            if not isin or not name:
                if not any((raw.get(c) or "").strip() for c in SCHEMES_COLUMNS):
                    continue  # blank line
                raise MfInputError(f"{where}: isin and name are both mandatory")
            if isin in schemes:
                raise MfInputError(f"{where}: scheme {isin} is declared twice")
            fmv_raw = (raw.get("fmv_2018_01_31") or "").strip()
            fmv = _parse_decimal(fmv_raw, where) if fmv_raw else None
            try:
                schemes[isin] = SchemeDecl(
                    isin=isin,
                    name=name,
                    classification=classification,
                    listed=_parse_bool(raw.get("listed") or "", where),
                    fmv_2018_01_31=fmv,
                )
            except capgain.MfError as exc:
                raise MfInputError(f"{where}: {exc}")
    return schemes


def load_ledgers(schemes_path: str, transactions_path: str) -> list[Ledger]:
    """Read both MF files and build one Ledger per declared scheme.

    Every transaction must name a declared scheme: a row for an undeclared ISIN is the
    same refusal the engine raises for an undeclared classification, surfaced at the
    file and line that caused it.
    """
    schemes = load_schemes(schemes_path)
    ledgers = {isin: Ledger(scheme) for isin, scheme in schemes.items()}
    if not os.path.exists(transactions_path):
        if schemes:
            raise MfInputError(
                f"{os.path.basename(schemes_path)} declares {len(schemes)} scheme(s) "
                f"but {os.path.basename(transactions_path)} does not exist"
            )
        return []
    with open(transactions_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for line, raw in enumerate(reader, start=2):
            where = f"{os.path.basename(transactions_path)} line {line}"
            isin = (raw.get("isin") or "").strip()
            if not isin and not any((raw.get(c) or "").strip()
                                    for c in TRANSACTIONS_COLUMNS):
                continue  # blank line
            if isin not in ledgers:
                raise MfInputError(
                    f"{where}: ISIN {isin!r} has no row in mf_schemes.csv -- declare "
                    "the scheme (classification, listed, and its valuation-date FMV "
                    "if it holds pre-cutoff units) before entering its transactions"
                )
            txn_type = (raw.get("type") or "").strip().lower()
            if txn_type not in _TYPES:
                raise MfInputError(
                    f"{where}: type {txn_type!r} must be one of "
                    f"{', '.join(sorted(_TYPES))}"
                )
            date = _parse_date(raw.get("date") or "", where)
            units = _parse_decimal(raw.get("units") or "", where)
            price_raw = (raw.get("price") or "").strip()
            expense_raw = (raw.get("transfer_expense") or "").strip()
            source_ref = (raw.get("source_ref") or "").strip() or where
            try:
                if txn_type == TYPE_PURCHASE:
                    if not price_raw:
                        raise MfInputError(f"{where}: a purchase needs its NAV/price")
                    ledgers[isin].add(Purchase(isin, date, units,
                                               _parse_decimal(price_raw, where),
                                               source_ref))
                elif txn_type == TYPE_BONUS:
                    ledgers[isin].add(Bonus(isin, date, units, source_ref))
                else:
                    if not price_raw:
                        raise MfInputError(f"{where}: a sale needs its NAV/price")
                    expense = (_parse_decimal(expense_raw, where) if expense_raw
                               else Decimal(0))
                    ledgers[isin].add(Sale(isin, date, units,
                                           _parse_decimal(price_raw, where),
                                           expense, source_ref))
            except capgain.MfError as exc:
                raise MfInputError(f"{where}: {exc}")
    # Only schemes with activity reach the engine; a declared scheme with no
    # transactions is nothing to compute on (and nothing to silently drop).
    active = [led for led in ledgers.values()
              if led.purchases or led.bonuses or led.sales]
    return active


def build_schedule_112a(rows_112a: list[dict]) -> dict:
    """Assemble the full Schedule 112A block: the detail rows plus the rupee
    aggregates the schema requires. Aggregates are whole-rupee sums of the per-row
    TOTAL figures (not per-unit values), so they reconcile row by row.

    The schema's per-row fields split into per-unit floats (multipleOf 0.0001) and
    total integers. The aggregates sum the totals:
      - CostAcqWithoutIndx  (total cost, integer)  -> CostAcqWithoutIndx112A
      - AcquisitionCost     (per-unit cost, float) -> AcquisitionCost112A sums the
        total cost too (same figure for non-grandfathered rows; for grandfathered
        rows the law says the cost IS the grandfathered amount).
    """
    def tot(field: str) -> int:
        return sum(r[field] for r in rows_112a)

    # The row-level transfer expense is a per-row decimal (multipleOf 0.0001), but the
    # schema's aggregate is an integer, so the total rounds to whole rupees.
    expense_total = int(
        sum((Decimal(str(r["ExpExclCnctTransfer"])) for r in rows_112a), Decimal(0))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )

    return {
        "Schedule112ADtls": rows_112a,
        "SaleValue112A": tot("TotSaleValue"),
        "CostAcqWithoutIndx112A": tot("CostAcqWithoutIndx"),
        "AcquisitionCost112A": tot("CostAcqWithoutIndx"),
        "LTCGBeforelowerB1B2112A": tot("LTCGBeforelowerB1B2"),
        "FairMktValueCapAst112A": tot("TotFairMktValueCapAst"),
        "ExpExclCnctTransfer112A": expense_total,
        "Deductions112A": tot("TotalDeductions"),
        "Balance112A": tot("Balance"),
        "TotalBalance112A": tot("Balance"),
    }


def run_engine(ledgers: list[Ledger], engine: Engine,
               window: tuple[dt.date, dt.date] | None = None):
    """Compute every ledger's matched gains and route them.

    Returns ``(rows_112a, cg_summary)`` where ``rows_112a`` is the list of
    Schedule 112A detail rows (one per scheme whose equity-oriented long-term gains
    exist) and ``cg_summary`` is a human-readable block naming every scheme's
    long- and short-term totals -- including the figures Schedule CG carries, which
    the utility computes and the JSON here does not.

    ``window`` is the filing year's financial-year span (1 April - 31 March). Every
    sale in the ledger participates in the FIFO replay -- a sale from an earlier year
    consumes its lots before a later sale matches, so removing it would misstate the
    open balance -- but only the gains of sales INSIDE the window belong to this
    return. Out-of-window gains are computed too and named in the summary, so nothing
    disappears silently; they simply belong to another year's filing.
    """
    rows_112a: list[dict] = []
    summary_lines: list[str] = []
    for ledger in ledgers:
        rows = engine.scheme_gains(ledger)
        if window is not None:
            reported = [r for r in rows if window[0] <= r.lot.sold <= window[1]]
            excluded = [r for r in rows if not (window[0] <= r.lot.sold <= window[1])]
        else:
            reported, excluded = rows, []
        ltcg, stcg = engine.sums(reported)
        long_rows = [r for r in reported if r.long_term]
        if ledger.scheme.classification == capgain.EQUITY_ORIENTED and long_rows:
            rows_112a.append(capgain.schedule_112a_row(ledger.scheme, long_rows,
                                                       engine.cutoff))
        line = (f"{ledger.scheme.name} ({ledger.scheme.isin}, "
                f"{ledger.scheme.classification}): LTCG {ltcg} INR, STCG {stcg} INR")
        if excluded:
            excluded_gain = sum((r.gain for r in excluded), Decimal(0))
            line += (f" -- {len(excluded)} lot(s) sold outside this return's financial "
                     f"year (gain {excluded_gain} INR) are excluded from these totals "
                     "and belong to another year's filing")
        summary_lines.append(line)
    return rows_112a, summary_lines
