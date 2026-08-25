"""Transcribe an Indian mutual fund Consolidated Account Statement (CAS) PDF.

Layout reference: the CDSL-issued CAS (the monthly "Consolidated Account Statement
(CAS) for securities held in demat form and investments in mutual funds"), verified
against a real statement on 25 August 2026. The statement is password-protected; the
password is the investor's PAN.

What this module does, and what it deliberately does NOT do:

- It transcribes every folio block and every transaction row into the intermediate
  CSVs this pipeline reads (``mf_schemes.csv`` and ``mf_transactions.csv``), so the
  capital-gains engine never has to see a PDF.
- It infers a fund's classification (equity-oriented or not) from the scheme name,
  and says so loudly -- the engine itself classifies nothing, and a name-based guess
  is exactly that. The transcribed CSV is a draft to review, not an answer.
- It never touches the numbers beyond copying them. No rounding, no FX, no tax math.

Dependency: PyMuPDF (``pymupdf``), a dev dependency of this repo -- verification
tooling, also used for the PDF schedules. Not a runtime requirement of the pipeline
itself, so the import is lazy and the error message tells you how to install it.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from . import capgain

ISIN_RE = re.compile(r"INF[0-9A-Z]{9}")
DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
NUM_RE = re.compile(
    r"^-?\d{1,3}(?:,\d\d,\d\d\d)+(?:\.\d+)?$|^-?\d+(?:\.\d+)?$|^-?\.\d+$"
)

# Words that identify the numeric columns. Rows containing these are headers.
NUMERIC_HEADER_WORDS = frozenset({"Amount", "NAV", "Price", "Units", "(`)", "Duty", "(`)"})

# Page furniture that must never be mistaken for a transaction row.
BANNER_MARKERS = (
    "CONSOLIDATED ACCOUNT STATEMENT", "HELD IN DEMAT", "HOLDING STATEMENT",
    "PORTFOLIO VALUATION", "DEMAT ACCOUNTS", "Summary of", "Account Details",
    "STATEMENT OF TRANSACTIONS", "AS ON", "MUTUAL FUND UNITS HELD",
    "MF Details", "Notes", "About CDSL", "Load", "IDCW",
)

# The statement lists every scheme twice: once in the folio summary near the front
# ("Scheme Name : ..." then "ISIN : ..."), once above its transaction table
# ("916GZ - <name>" then "ISIN : ..."). Names arrive from either; dedupe by ISIN.
SUMMARY_NAME_RE = re.compile(r"^Scheme\s+Name\s*:?\s*(.*)$", re.IGNORECASE)

# Folio block markers
OPENING = "Opening"
CLOSING = "Closing"


# Folio header: "<scheme code GZ/Y/Z> - <scheme name>", e.g. "110GZ - Aditya Birla
# Sun Life Gold Fund Growth-Direct Plan". The scheme code is the registrar's internal
# code; the ISIN follows on the next line.
FOLIO_HEADER_RE = re.compile(r"^(\d{2,4}(?:GZ|Y|Z))\s+-\s+(.+)$")
ISIN_LINE_RE = re.compile(r"^ISIN\s*:")


class CasError(Exception):
    """A CAS the transcriber cannot safely read. The message says why and what to do."""


@dataclass
class SchemeInfo:
    isin: str
    name: str
    classification: str  # 'equity_oriented', 'debt', or '' (unknown)
    basis: str  # why the classification was inferred
    folio: str = ""


@dataclass
class TxnRow:
    isin: str
    date: dt.date
    kind: str  # purchase | switch_in | switch_out | redemption | other
    amount: Decimal | None
    nav: Decimal | None
    units: Decimal | None
    description: str = ""
    ref: str = ""
    page: int = 0
    transfer_expense: Decimal = Decimal(0)  # STT on a sale, attached from its own row


@dataclass
class CasTranscript:
    schemes: list[SchemeInfo] = field(default_factory=list)
    transactions: list[TxnRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    period_from: dt.date | None = None
    period_to: dt.date | None = None


def _dec(text: str) -> Decimal | None:
    text = (text or "").strip()
    if not text:
        return None
    text = text.replace(",", "").replace("`", "").replace("\u20b9", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _is_numeric(text: str) -> bool:
    return bool(NUM_RE.match((text or "").strip().replace(",", "").replace(",", "")))


# ---------------------------------------------------------------------------
# Layout extraction (PyMuPDF, coordinates preserved)
# ---------------------------------------------------------------------------

def _load_words(pdf_path: str, password: str | None):
    """Return a list of (pageno, words) where words is a list of
    (pageno, x0, y0, x1, y1, word), top-to-bottom, left-to-right within a line.

    pdfminer.six cannot read the body text of CDSL CAS PDFs (it only sees the page
    numbers); PyMuPDF can. The y-axis points DOWN here, which matches how the rest of
    this module reasons about rows."""
    try:
        import pymupdf
    except ImportError as exc:
        raise CasError(
            "PyMuPDF is required to read CAS PDFs. Install it into the repo's "
            "virtualenv: .venv/bin/pip install pymupdf"
        ) from exc

    doc = pymupdf.open(pdf_path)
    try:
        if doc.is_encrypted:
            if not doc.authenticate(password or ""):
                raise CasError(
                    "the CAS is password-protected and the password was rejected. "
                    "CDSL/CAMS statements use your registered PAN as the password."
                )
        pages = []
        for pageno in range(1, len(doc) + 1):
            page = doc[pageno - 1]
            words = []
            for x0, y0, x1, y1, word, _b, _l, _n in page.get_text("words"):
                words.append((pageno, x0, y0, x1, y1, word))
            words.sort(key=lambda w: (round(w[2], 1), w[1]))
            pages.append((pageno, words))
        return pages
    finally:
        doc.close()


def _group_lines(words, y_tolerance=2.5):
    """Group words into visual lines: list of (pageno, y, [(x, word), ...])."""
    lines = []
    current_y = None
    current_page = None
    bucket = []

    for pageno, x0, y0, x1, y1, word in words:
        if current_y is None or pageno != current_page or abs(y0 - current_y) > y_tolerance:
            if bucket:
                lines.append((current_page, current_y, bucket))
            bucket = []
            current_y = y0
            current_page = pageno
        bucket.append((x0, word))
    if bucket:
        lines.append((current_page, current_y, bucket))
    # sort words within each line left-to-right
    out = []
    for pageno, y, words_in in lines:
        out.append((pageno, y, sorted(words_in, key=lambda t: t[0])))
    return out


# ---------------------------------------------------------------------------
# Classification inference (name-based guess, always flagged)
# ---------------------------------------------------------------------------

_DEBT_TOKENS = (
    "LIQUID", "OVERNIGHT", "ULTRA SHORT", "ULTRA-SHORT", "SHORT TERM", "SHORT-TERM",
    "MONEY MARKET", "BOND", "GILT", "CREDIT", "BANKING", "PSU", "CORPORATE", "FLOATER",
    "INCOME", "DEBT", "DYNAMIC BOND", "TARGET MATURITY", "FIXED MATURITY",
)
_EQUITY_TOKENS = (
    "EQUITY", "ELSS", "TAX SAVER", "INDEX", "NIFTY", "SENSEX", "BSE", "LARGE CAP",
    "MID CAP", "SMALL CAP", "LARGECAP", "MIDCAP", "SMALLCAP", "LARGE & MID", "FLEXI",
    "MULTI CAP", "MULTICAP", "VALUE", "CONTRA", "FOCUSED", "DIVIDEND", "INFRA",
    "PHARMA", "BANKING & FINANCIAL", "TECHNOLOGY", "CONSUMPTION",
)
_GOLD_TOKENS = ("GOLD",)


def infer_classification(name: str) -> tuple[str, str]:
    """Guess the section-198 classification from the scheme name. Returns
    (classification, basis). Classification is '' when the guess is unsafe.

    The returned value is the ENGINE's vocabulary (capgain.EQUITY_ORIENTED /
    capgain.OTHER_FUND), so the transcribed mf_schemes.csv passes the engine's
    own classification check without translation."""
    upper = name.upper()

    if any(t in upper for t in _GOLD_TOKENS):
        return (capgain.OTHER_FUND,
                "name contains GOLD (gold funds are not equity-oriented)")

    if "ARBITRAGE" in upper:
        return (capgain.EQUITY_ORIENTED,
                "name contains ARBITRAGE (treated as equity-oriented under the "
                "equity-oriented definition)")

    debt_hit = next((t for t in _DEBT_TOKENS if t in upper), None)
    if debt_hit:
        return capgain.OTHER_FUND, f"name contains {debt_hit!r}"

    eq_hit = next((t for t in _EQUITY_TOKENS if t in upper), None)
    if eq_hit:
        return capgain.EQUITY_ORIENTED, f"name contains {eq_hit!r}"

    if "ETF" in upper:
        return ("", "name is an ETF; the underlying index determines classification "
                   "-- check the fund factsheet")

    return "", "scheme name not recognized; classify manually"


# ---------------------------------------------------------------------------
# Row parsing
# ---------------------------------------------------------------------------

def _row_values(cells: list[tuple[float, str]]) -> dict[str, Decimal | None]:
    """Pull amount/nav/units out of one row's words by x-position.

    Layout (measured from the reference statement): Amount x~200-235, NAV x~265-295,
    Price x~325-355, Units x~395-420.
    """
    vals: dict[str, Decimal | None] = {"amount": None, "nav": None, "units": None}
    for x, word in cells:
        word = word.strip()
        if not word or not _is_numeric(word):
            continue
        if 190 <= x < 250 and vals["amount"] is None:
            vals["amount"] = _dec(word)
        elif 255 <= x < 315 and vals["nav"] is None:
            vals["nav"] = _dec(word)
        elif 380 <= x < 440 and vals["units"] is None:
            vals["units"] = _dec(word)
    return vals


def _classify_txn(label: str) -> str:
    label = label.lower()
    if "purchase" in label:
        return "purchase"
    if "switch-out" in label or "switch out" in label:
        return "switch_out"
    if "switch-in" in label or "switch in" in label:
        return "switch_in"
    if "redemption" in label:
        return "redemption"
    if label.strip() == "stt":
        return "stt"
    return "other"


def transcribe_cas(pdf_path: str, password: str | None = None) -> CasTranscript:
    """Parse a CAS PDF into schemes + transactions. Raises CasError on structural
    problems; the transcript carries its own warnings list for softer issues."""
    if not os.path.exists(pdf_path):
        raise CasError(f"CAS file not found: {pdf_path}")

    tx = CasTranscript()
    try:
        pages = _load_words(pdf_path, password)
    except CasError:
        raise
    except Exception as exc:
        raise CasError(
            f"could not open the CAS (wrong password, or not a readable PDF?): {exc}"
        ) from exc

    if not pages:
        raise CasError("the CAS has no pages")

    current_isin: str | None = None
    current_scheme_name_parts: list[str] = []
    current_folio = ""
    pending_header: str | None = None  # folio header seen, ISIN not yet seen
    pending_summary_name: str | None = None  # "Scheme Name : ..." awaiting its ISIN line
    pending_label: str | None = None  # transaction label awaiting its date row
    pending_ref_parts: list[str] = []
    in_txn_table = False  # only date rows inside a real transaction table count

    def flush_scheme() -> None:
        nonlocal current_isin, current_scheme_name_parts, current_folio, in_txn_table
        if current_isin and current_scheme_name_parts:
            _flush_scheme(tx, current_isin, current_scheme_name_parts, current_folio)
        current_isin = None
        current_scheme_name_parts = []
        current_folio = ""
        in_txn_table = False

    for pageno, words in pages:
        lines = _group_lines(words)
        for _, _y, cells in lines:
            text = " ".join(w for _, w in cells)

            # Page furniture: banner, section titles, notes. Never a transaction,
            # and never a pending label -- clear the pending label so banner words
            # cannot leak into the next real transaction's description.
            if any(marker.lower() in text.lower() for marker in BANNER_MARKERS):
                if "STATEMENT OF TRANSACTIONS" in text:
                    dates = re.findall(r"(\d{2}-\d{2}-\d{4})", text)
                    if len(dates) >= 2:
                        tx.period_from = dt.datetime.strptime(dates[0], "%d-%m-%Y").date()
                        tx.period_to = dt.datetime.strptime(dates[1], "%d-%m-%Y").date()
                pending_label = None
                in_txn_table = False  # a banner closes any open transaction table
                continue

            # Folio summary entry (front of statement): "Scheme Name : <name>",
            # immediately followed by "ISIN : ...". Captures names the transaction
            # table's own header rows also carry -- whichever arrives first wins.
            m_summary = SUMMARY_NAME_RE.match(text.strip())
            if m_summary and m_summary.group(1).strip():
                pending_summary_name = m_summary.group(1).strip()
                continue

            # New folio block, line 1: "<code GZ> - <scheme name>"
            m_header = FOLIO_HEADER_RE.match(text.strip())
            if m_header and not ISIN_RE.search(text):
                flush_scheme()
                pending_label = None  # a new table cannot inherit a stale label
                pending_header = m_header.group(1)
                current_scheme_name_parts = [m_header.group(2).strip()]
                current_folio = m_header.group(1)
                pending_ref_parts = []
                pending_summary_name = None
                in_txn_table = True  # this header opens a transaction table
                continue

            # New folio block, line 2: "ISIN : INFxxxxxxxxx". This COMPLETES the
            # block started by a header or summary-name line -- the name is already
            # captured, so do NOT flush here.
            if ISIN_LINE_RE.match(text.strip()):
                m_isin = ISIN_RE.search(text)
                if m_isin:
                    if pending_header is not None:
                        # Transaction-table header seen, now the ISIN: attach.
                        if current_isin:
                            _flush_scheme(tx, current_isin, current_scheme_name_parts,
                                          current_folio)
                        current_isin = m_isin.group(0)
                        pending_header = None
                        in_txn_table = True
                    elif pending_summary_name is not None:
                        # Summary-section entry: name came from "Scheme Name :".
                        if current_isin:
                            _flush_scheme(tx, current_isin, current_scheme_name_parts,
                                          current_folio)
                        current_isin = m_isin.group(0)
                        current_scheme_name_parts = [pending_summary_name]
                        pending_summary_name = None
                        in_txn_table = False  # summary block, not a transaction table
                    else:
                        # ISIN line with no preceding name -- keep it, flag it.
                        if current_isin:
                            _flush_scheme(tx, current_isin, current_scheme_name_parts,
                                          current_folio)
                        current_isin = m_isin.group(0)
                        current_scheme_name_parts = []
                        current_folio = ""
                        in_txn_table = False
                continue

            # A bare ISIN elsewhere (e.g. scheme lists) does not change state.

            # Skip header rows
            if any(w in NUMERIC_HEADER_WORDS for _, w in cells):
                continue
            if "Opening Balance" in text or "Closing Balance" in text:
                # balance rows carry a units figure in the Units column; we do not
                # need them for the engine, but record the closing balance for a
                # later sanity check.
                vals = _row_values(cells)
                if vals["units"] is not None and "Closing" in text:
                    tx.warnings.append(
                        f"{current_isin or '?'}: closing balance {vals['units']} units "
                        f"(page {pageno}) -- use this to sanity-check your transcription."
                    )
                continue

            # Transaction row: starts with a date. In the CDSL layout the
            # transaction LABEL lives on the line ABOVE the date row, and the
            # date row itself carries the description continuation plus the
            # numbers.
            date_word = next((w for x, w in cells if DATE_RE.match(w)), None)
            if date_word and current_isin and in_txn_table:
                row_date = dt.datetime.strptime(date_word, "%d-%m-%Y").date()
                cont_words = [w for x, w in cells
                              if 60 <= x < 190 and not DATE_RE.match(w)
                              and not _is_numeric(w)]
                label = " ".join(([pending_label] if pending_label else []) + cont_words)
                kind = _classify_txn(label)
                vals = _row_values(cells)
                tx.transactions.append(TxnRow(
                    isin=current_isin, date=row_date, kind=kind,
                    amount=vals["amount"], nav=vals["nav"], units=vals["units"],
                    description=label.strip(), ref="",
                    page=pageno,
                ))
                pending_label = None
                pending_ref_parts = []
                continue

            # Reference/transaction-number line (digits only, left zone). In the
            # layout it follows the date row and belongs to that transaction.
            if re.fullmatch(r"\d{6,}", text.strip()) and cells and cells[0][0] < 130:
                if tx.transactions and not tx.transactions[-1].ref:
                    tx.transactions[-1].ref = text.strip()
                continue

            # STT annotation row: no date of its own; in the layout it sits
            # directly after the switch-out/redemption row it belongs to. STT is
            # the sale's transfer expense (the engine's Sale.transfer_expense),
            # so attach it there rather than letting it pollute the next label.
            if cells and 60 <= cells[0][0] < 130 and cells[0][1].upper() == "STT":
                vals = _row_values(cells)
                stt_amount = abs(vals["amount"]) if vals["amount"] is not None else None
                if stt_amount is None:
                    continue
                if tx.transactions and tx.transactions[-1].kind in (
                        "switch_out", "redemption"):
                    tx.transactions[-1].transfer_expense = stt_amount
                else:
                    tx.warnings.append(
                        f"STT of {stt_amount} on page {pageno} has no preceding sale "
                        "to attach to. Fold it into the right sale's transfer_expense "
                        "in mf_transactions.csv."
                    )
                continue

            # Otherwise, a non-numeric line in the label zone is a pending
            # transaction label waiting for its date row.
            if cells and 60 <= cells[0][0] < 130 and not _is_numeric(text):
                pending_label = (pending_label + " " + text) if pending_label else text
                continue

    flush_scheme()

    # The same scheme appears multiple times (summary section + one block per
    # transaction-table page). Dedupe by ISIN, keeping the first complete name
    # and merging warnings.
    deduped: dict[str, SchemeInfo] = {}
    for s in tx.schemes:
        existing = deduped.get(s.isin)
        if existing is None:
            deduped[s.isin] = s
        elif (not existing.name or existing.name.startswith("(scheme name")) and s.name:
            existing.name = s.name
            if existing.classification != s.classification:
                existing.classification, existing.basis = s.classification, s.basis
    tx.schemes = list(deduped.values())

    _validate(tx)
    return tx


def _flush_scheme(tx: CasTranscript, isin: str, name_parts: list[str], folio: str) -> None:
    name = " ".join(name_parts).strip()
    classification, basis = infer_classification(name)
    tx.schemes.append(SchemeInfo(isin=isin, name=name, classification=classification,
                                 basis=basis, folio=folio))


def _validate(tx: CasTranscript) -> None:
    if not tx.schemes:
        raise CasError("no mutual fund folio blocks found -- is this a CAS?")

    seen_isins = {s.isin for s in tx.schemes}
    for row in tx.transactions:
        if row.isin not in seen_isins:
            tx.warnings.append(
                f"transaction {row.date} {row.kind} references {row.isin}, which has "
                "no folio block -- the folio header may have been missed."
            )

    # Warn about out-of-period holdings: any folio whose first activity is a
    # redemption/switch-out (no purchase in the statement) likely had units before
    # the period -- those earlier purchases are NOT in this statement.
    for isin in seen_isins:
        rows = [r for r in tx.transactions if r.isin == isin]
        if rows and rows[0].kind in ("switch_out", "redemption"):
            tx.warnings.append(
                f"{isin}: the first transaction in the statement is a "
                f"{rows[0].kind.replace('_', ' ')}. Units were held before this "
                "statement's period -- their purchase cost is NOT in this file."
            )


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

SCHEME_CSV_COLUMNS = ["isin", "name", "classification", "listed", "fmv_2018_01_31"]
TXN_CSV_COLUMNS = ["isin", "txn_type", "date", "units", "price_per_unit",
                   "transfer_expense", "source_ref"]


def write_csvs(tx: CasTranscript, work_dir: str,
               schemes_name: str = "mf_schemes.csv",
               transactions_name: str = "mf_transactions.csv") -> tuple[str, str]:
    """Write the transcript into the pipeline's intermediate CSVs inside work_dir.

    Existing files are backed up with a .bak suffix rather than overwritten.
    """
    os.makedirs(work_dir, exist_ok=True)
    schemes_path = os.path.join(work_dir, schemes_name)
    txns_path = os.path.join(work_dir, transactions_name)

    for path in (schemes_path, txns_path):
        if os.path.exists(path):
            backup = path + ".bak"
            os.replace(path, backup)

    with open(schemes_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(SCHEME_CSV_COLUMNS)
        for s in tx.schemes:
            writer.writerow([s.isin, s.name, s.classification, "yes", ""])

    with open(txns_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(TXN_CSV_COLUMNS)
        for r in tx.transactions:
            expense = Decimal(0)
            if r.kind in ("purchase", "switch_in"):
                txn_type, units, price = "purchase", r.units, r.nav
            elif r.kind in ("switch_out", "redemption"):
                txn_type = "sale"
                units = abs(r.units) if r.units is not None else None
                price = abs(r.nav) if r.nav is not None else None
                expense = r.transfer_expense  # STT, attached during transcription
            else:
                tx.warnings.append(
                    f"{r.isin}: unrecognized transaction '{r.description}' on {r.date} "
                    "was skipped. Review it manually."
                )
                continue

            if units is None or price is None:
                tx.warnings.append(
                    f"{r.isin}: {txn_type} on {r.date} has no units/NAV in the row -- "
                    "skipped. Review the statement page."
                )
                continue
            writer.writerow([r.isin, txn_type, r.date.isoformat(),
                             str(units), str(price), str(expense),
                             r.ref or r.description])

    return schemes_path, txns_path


def summarize(tx: CasTranscript) -> str:
    """A human-readable summary of what was transcribed, with every inference flagged."""
    lines = []
    if tx.period_from and tx.period_to:
        lines.append(f"Statement period: {tx.period_from} to {tx.period_to}")
    lines.append(f"Folios found: {len(tx.schemes)}")
    for s in tx.schemes:
        flag = s.classification or "UNKNOWN"
        lines.append(f"  {s.isin}  {s.name[:60]}")
        lines.append(f"      classification: {flag}  ({s.basis})")
    lines.append(f"Transactions transcribed: {len(tx.transactions)}")
    by_kind: dict[str, int] = {}
    for r in tx.transactions:
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
    for kind in sorted(by_kind):
        lines.append(f"  {kind}: {by_kind[kind]}")
    if tx.warnings:
        lines.append("")
        lines.append("WARNINGS -- review these before running the build:")
        for w in tx.warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines)
