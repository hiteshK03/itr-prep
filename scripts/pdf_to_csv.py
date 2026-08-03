#!/usr/bin/env python3
"""Best-effort converter: broker trade-confirmation PDFs -> a CSV the normalize adapters
can read.

This is NOT a general PDF table extractor. Statement and 1042-S PDFs do not carry
per-lot data at all -- no CSV conversion of them will produce a transaction history,
because the transaction history isn't in the document. This script only handles PDFs
that already contain individual trade confirmations (one buy/sell per block), which
is a real, narrow, regex-matchable layout -- not a general table-in-PDF problem.

Requires the `pdftotext` binary (poppler-utils / `brew install poppler` /
`apt install poppler-utils`). Not a new Python dependency -- shelling out to a
system tool keeps requirements.txt at two entries.

Currently supports:
  - E*TRADE / Morgan Stanley "Trade Confirmation" PDFs (one confirmation per PDF,
    sometimes with a routing/disclosure page attached).
  - Fidelity "Stock Plan Services Report" / "Year-End Investment Report" PDFs that
    contain an "Employee Stock Purchase Summary" table (Offering Period, Purchase
    Date, Purchase Price, Fair Market Value, Shares Purchased). This is real
    per-lot ESPP data, unlike the account-value/holdings pages the rest of the
    statement carries.
  - DriveWealth / INDmoney monthly "Account Statement" PDFs, from the ACTIVITY
    table (trade date, settle date, currency, activity type, symbol, quantity,
    price, amount). Dividend tax withholding (DIVFT) and cash-sweep rows are
    dropped -- only BUY/SELL/DIV rows for actual securities are kept. Rows are
    deduplicated across files (a purchase near a statement boundary can appear
    on two consecutive monthly statements).

Output columns match the `etrade` adapter's aliases directly: Trade Date, Quantity,
Price, Transaction Type, Symbol.

Usage:
    python3 scripts/pdf_to_csv.py --broker etrade FILE.pdf [FILE.pdf ...] --out work/drop/etrade_confirmations.csv

The output is a normal CSV -- open it and check every row against the source PDF
before trusting it in a build. This script has been verified against exactly one
real trade confirmation; treat new layouts (multi-trade statements, other brokers)
as unverified until you have checked their output by hand.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys

TRADE_CONFIRMATION_RE = re.compile(
    r"Trade Date\s+Settlement Date\s+Quantity\s+Price\s+Settlement Amount\s*\n"
    r"(?P<trade_date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<settlement_date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<quantity>[\d,]+)\s+"
    r"(?P<price>[\d,.]+)\s+.*?\n"
    r".*?\n?"
    r"Transaction Type:\s*(?P<txn_type>\w+)\s*\n\s*\n?"
    r"Description:\s*(?P<description>.+?)\s*\n"
    r"Symbol\s*/\s*CUSIP\s*/\s*ISIN:\s*(?P<symbol>[A-Z.]+)\s*/",
    re.MULTILINE,
)


def _pdftotext(path: str) -> str:
    if shutil.which("pdftotext") is None:
        raise SystemExit(
            "pdftotext not found. Install poppler-utils (brew install poppler / "
            "apt install poppler-utils) or export the CSV/XLSX transaction history "
            "directly from your broker instead -- that is the supported path."
        )
    result = subprocess.run(
        ["pdftotext", "-layout", path, "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def extract_etrade_confirmations(path: str) -> list[dict]:
    text = _pdftotext(path)
    rows = []
    for match in TRADE_CONFIRMATION_RE.finditer(text):
        rows.append({
            "Trade Date": match.group("trade_date"),
            "Symbol": match.group("symbol"),
            "Quantity": match.group("quantity").replace(",", ""),
            "Price": match.group("price").replace(",", ""),
            "Transaction Type": match.group("txn_type"),
        })
    return rows


INDMONEY_ACTIVITY_RE = re.compile(
    r"^(?P<trade_date>\d{2}/\d{2}/\d{4})\s+(?P<settle_date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<currency>[A-Z]{3})\s+(?P<type>[A-Z]+)\s+(?P<symbol>[A-Z]{1,6})\s*-\s*.*?"
    r"(?P<qty>-?\d+(?:\.\d+)?)\s+(?P<price>\d+\.\d+)\s+\(?(?P<amount>-?[0-9,]+\.\d+)\)?\s*$",
    re.MULTILINE,
)

# Activity Types seen on DriveWealth/INDmoney statements that are actual security
# transactions. Excluded deliberately: DIVFT (dividend tax withholding -- a debit paired
# with the DIV row, not a separate transaction), and cash-sweep codes (CDEP, JNLC, INTBD,
# and BUY/SELL of the DWBDS money-market symbol) which are cash movement, not equity.
#
# XTRF (in-kind transfer from another account) is treated as an acquisition: Amount is
# $0.00 because no cash changed hands, but Price carries a real per-share value -- this
# was confirmed against a Dec-2025 holdings snapshot, where the post-transfer running
# quantity for two tickers only reconciled once the XTRF row's quantity was included
# (one of them exactly, the other only after accounting for a stock split between the
# transfer date and the snapshot date -- the split is not this script's job to adjust;
# the itrprep pipeline's own split detection handles that from the acquisition date onward).
_INDMONEY_KEEP_TYPES = {"BUY", "SELL", "DIV", "XTRF"}


def extract_indmoney_activity(path: str) -> list[dict]:
    text = _pdftotext(path)
    rows = []
    for match in INDMONEY_ACTIVITY_RE.finditer(text):
        if match.group("type") not in _INDMONEY_KEEP_TYPES:
            continue
        if match.group("symbol") == "DWBDS":
            continue
        qty = match.group("qty")
        rows.append({
            "Date": match.group("trade_date"),
            "Symbol": match.group("symbol"),
            "Quantity": qty.lstrip("-"),
            "Price": match.group("price"),
            "Type": match.group("type"),
            "Amount": match.group("amount").replace(",", ""),
        })
    return rows


FIDELITY_ESPP_RE = re.compile(
    r"(?P<offering>\d{2}/\d{2}/\d{4}-\d{2}/\d{2}/\d{4})\s+Employee Purchase\s+"
    r"(?P<purchase_date>\d{2}/\d{2}/\d{4})\s+"
    r"\$(?P<price>[\d,]+\.\d+)\s+"
    r"\$(?P<fmv>[\d,]+\.\d+)\s+"
    r"(?P<qty>[\d,]+\.\d+)\s+"
    r"\$?(?P<gain>-?[\d,]+\.\d+)"
)


def extract_fidelity_espp(path: str, symbol: str = "") -> list[dict]:
    text = _pdftotext(path)
    rows = []
    for match in FIDELITY_ESPP_RE.finditer(text):
        rows.append({
            "Purchase Date": match.group("purchase_date"),
            "Symbol": symbol,
            "Shares Purchased": match.group("qty").replace(",", ""),
            "Purchase Price": match.group("price").replace(",", ""),
            "Purchase Date FMV": match.group("fmv").replace(",", ""),
            "Offering Period": match.group("offering"),
        })
    return rows


EXTRACTORS = {
    "etrade": extract_etrade_confirmations,
    "fidelity-espp": extract_fidelity_espp,
    "indmoney-activity": extract_indmoney_activity,
}

FIDELITY_FIELDNAMES = ["Purchase Date", "Symbol", "Shares Purchased",
                        "Purchase Price", "Purchase Date FMV", "Offering Period"]
ETRADE_FIELDNAMES = ["Trade Date", "Symbol", "Quantity", "Price", "Transaction Type"]
INDMONEY_FIELDNAMES = ["Date", "Symbol", "Quantity", "Price", "Type", "Amount"]
FIELDNAMES = {"etrade": ETRADE_FIELDNAMES, "fidelity-espp": FIDELITY_FIELDNAMES,
              "indmoney-activity": INDMONEY_FIELDNAMES}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--broker", required=True, choices=sorted(EXTRACTORS))
    parser.add_argument("pdfs", nargs="+", help="trade-confirmation PDF(s)")
    parser.add_argument("--out", required=True, help="output CSV path")
    parser.add_argument("--symbol", default="",
                         help="ticker to stamp on every row (fidelity-espp has no "
                              "per-row symbol column; required for that broker)")
    args = parser.parse_args()

    if args.broker == "fidelity-espp" and not args.symbol:
        parser.error("--symbol is required for --broker fidelity-espp")

    all_rows: list[dict] = []
    misses: list[str] = []
    seen: set[tuple] = set()
    for pdf in args.pdfs:
        if args.broker == "fidelity-espp":
            rows = extract_fidelity_espp(pdf, symbol=args.symbol)
        else:
            rows = EXTRACTORS[args.broker](pdf)
        rows = [r for r in rows if tuple(r.values()) not in seen
                and not seen.add(tuple(r.values()))]
        if not rows:
            misses.append(pdf)
        all_rows.extend(rows)

    if misses:
        print(
            "No trade confirmation matched in:\n  " + "\n  ".join(misses) +
            "\nThese may be statements or tax forms rather than trade confirmations "
            "-- no per-lot data to extract from them regardless of format.",
            file=sys.stderr,
        )

    if not all_rows:
        print("No rows extracted; nothing written.", file=sys.stderr)
        return 1

    with open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES[args.broker])
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Wrote {len(all_rows)} row(s) to {args.out}. "
          f"Check every row against the source PDF before using it in a build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
