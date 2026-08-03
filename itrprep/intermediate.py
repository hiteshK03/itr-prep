"""Reading and writing the intermediate CSVs.

The error messages here are deliberately verbose. The fallback workflow for any broker
whose export format cannot be confirmed is "hand-fill the intermediate CSV", so a person
editing these files by hand is a first-class user and needs to be told exactly which file,
line and column is wrong.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
from decimal import Decimal, InvalidOperation

from .models import (
    ACCOUNT_COLUMNS,
    ACQ_KINDS,
    DISPOSAL_KINDS,
    ISSUER_COLUMNS,
    TRANSACTION_COLUMNS,
    TXN_DIVIDEND,
    TXN_SELL,
    TXN_TYPES,
    Account,
    CashBalance,
    DataError,
    Issuer,
    Transaction,
)

VALID_STATUS = ("OWNER", "BENEFICIAL_OWNER", "BENIFICIARY")


def _require_columns(path: str, got, want, what: str) -> None:
    if got is None:
        raise DataError(f"{path}: file is empty or has no header row")
    normalised = {c.strip() for c in got}
    missing = [c for c in want if c not in normalised]
    if missing:
        raise DataError(
            f"{path}: missing required column(s) for {what}: {', '.join(missing)}\n"
            f"  columns found: {', '.join(sorted(normalised))}\n"
            f"  expected header: {','.join(want)}\n"
            f"If a column was renamed, rename it back rather than guessing -- these "
            f"names are the documented intermediate schema (see README data dictionary)."
        )


def _dec(path: str, lineno: int, column: str, raw: str, default=None) -> Decimal:
    raw = (raw or "").strip().replace(",", "").replace("$", "")
    if raw in ("", "-"):
        if default is None:
            raise DataError(f"{path} line {lineno}: column '{column}' is required")
        return default
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise DataError(
            f"{path} line {lineno}: column '{column}' value {raw!r} is not a number"
        ) from exc


def _date(path: str, lineno: int, column: str, raw: str) -> dt.date:
    raw = (raw or "").strip()
    if not raw:
        raise DataError(f"{path} line {lineno}: column '{column}' is required")
    # Accept the ISO form plus the two orderings brokers commonly export, but never
    # guess between DD/MM and MM/DD -- US brokers are MM/DD, so that is what is assumed
    # for slashed dates, and the README tells the user to prefer ISO to avoid the issue.
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%b %d, %Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise DataError(
        f"{path} line {lineno}: column '{column}' value {raw!r} is not a date I can "
        f"read. Use YYYY-MM-DD."
    )


def read_transactions(path: str) -> list[Transaction]:
    if not os.path.exists(path):
        raise DataError(f"transactions file not found: {path}")
    out: list[Transaction] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        _require_columns(path, reader.fieldnames, TRANSACTION_COLUMNS, "transactions")
        for lineno, row in enumerate(reader, start=2):
            row = {(k or "").strip(): v for k, v in row.items()}
            if not any((v or "").strip() for v in row.values()):
                continue
            txn_type = (row.get("txn_type") or "").strip().upper()
            if txn_type not in TXN_TYPES:
                raise DataError(
                    f"{path} line {lineno}: txn_type {txn_type!r} invalid; "
                    f"must be one of {', '.join(TXN_TYPES)}"
                )
            acq_kind = (row.get("acq_kind") or "").strip().upper()
            if acq_kind not in ACQ_KINDS:
                raise DataError(
                    f"{path} line {lineno}: acq_kind {acq_kind!r} invalid; "
                    f"must be one of {', '.join(k for k in ACQ_KINDS if k)} or blank"
                )
            # Optional, like expense_usd: files hand-filled before the column existed
            # must keep reading.
            disposal_kind = (row.get("disposal_kind") or "").strip().upper()
            if disposal_kind not in DISPOSAL_KINDS:
                raise DataError(
                    f"{path} line {lineno}: disposal_kind {disposal_kind!r} invalid; "
                    f"must be {', '.join(k for k in DISPOSAL_KINDS if k)} or blank"
                )
            if disposal_kind and txn_type != TXN_SELL:
                raise DataError(
                    f"{path} line {lineno}: disposal_kind is only meaningful on a SELL "
                    f"row, but this row is a {txn_type}"
                )
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                raise DataError(f"{path} line {lineno}: ticker is required")
            account_id = (row.get("account_id") or "").strip()
            if not account_id:
                raise DataError(f"{path} line {lineno}: account_id is required")

            if txn_type == TXN_DIVIDEND:
                quantity = Decimal(0)
                price = Decimal(0)
                amount = _dec(path, lineno, "amount_usd", row.get("amount_usd", ""))
                if amount < 0:
                    raise DataError(
                        f"{path} line {lineno}: dividend amount_usd cannot be negative"
                    )
            else:
                quantity = _dec(path, lineno, "quantity", row.get("quantity", ""))
                if quantity <= 0:
                    raise DataError(
                        f"{path} line {lineno}: quantity must be positive for "
                        f"{txn_type} (sales are recorded as SELL with a positive "
                        f"quantity, not as a negative BUY)"
                    )
                price = _dec(path, lineno, "price_usd", row.get("price_usd", ""))
                raw_amount = (row.get("amount_usd") or "").strip()
                amount = (
                    _dec(path, lineno, "amount_usd", raw_amount) if raw_amount else None
                )

            out.append(
                Transaction(
                    account_id=account_id,
                    ticker=ticker,
                    txn_type=txn_type,
                    date=_date(path, lineno, "date", row.get("date", "")),
                    quantity=quantity,
                    price_usd=price,
                    amount_usd=amount,
                    tax_withheld_usd=_dec(
                        path, lineno, "tax_withheld_usd",
                        row.get("tax_withheld_usd", ""), Decimal(0),
                    ),
                    expense_usd=_dec(
                        path, lineno, "expense_usd",
                        row.get("expense_usd", ""), Decimal(0),
                    ),
                    paid_price_usd=_dec(
                        path, lineno, "paid_price_usd",
                        row.get("paid_price_usd", ""), Decimal(0),
                    ),
                    acq_kind=acq_kind,
                    disposal_kind=disposal_kind,
                    lot_id=(row.get("lot_id") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                    source_row=lineno,
                    source_file=path,
                )
            )
    if not out:
        raise DataError(f"{path}: no transaction rows found (only a header?)")
    return out


def read_issuers(path: str) -> dict[str, Issuer]:
    if not os.path.exists(path):
        raise DataError(f"issuers file not found: {path}")
    out: dict[str, Issuer] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        _require_columns(path, reader.fieldnames, ISSUER_COLUMNS, "issuers")
        for lineno, row in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            ticker = row.get("ticker", "").upper()
            if not ticker:
                continue
            for required in ("entity_name", "entity_address", "entity_zip",
                             "entity_nature"):
                if not row.get(required):
                    raise DataError(
                        f"{path} line {lineno}: '{required}' is required and blank. "
                        f"Every Table A3 row must carry the issuer's name, address, zip "
                        f"and nature -- the ITD schema marks all four mandatory."
                    )
            # Length ceilings straight from ITR-2_2026_Main_V1.1.json. Truncating
            # silently would produce a file that imports but does not match the source,
            # so this is an error rather than a trim.
            for column, limit in (("entity_name", 125), ("entity_address", 200),
                                  ("entity_zip", 8), ("entity_nature", 34)):
                if len(row[column]) > limit:
                    raise DataError(
                        f"{path} line {lineno}: '{column}' is {len(row[column])} chars, "
                        f"but the ITD schema allows at most {limit}. Shorten it."
                    )
            out[ticker] = Issuer(
                ticker=ticker,
                entity_name=row["entity_name"],
                entity_address=row["entity_address"],
                entity_zip=row["entity_zip"].upper(),
                entity_nature=row["entity_nature"],
                country_code=row.get("country_code") or "2",
                country_name=row.get("country_name") or "UNITED STATES OF AMERICA",
            )
    if not out:
        raise DataError(f"{path}: no issuer rows found")
    return out


def read_accounts(path: str) -> dict[str, Account]:
    if not os.path.exists(path):
        raise DataError(f"accounts file not found: {path}")
    out: dict[str, Account] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        _require_columns(path, reader.fieldnames, ACCOUNT_COLUMNS, "accounts")
        for lineno, row in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            account_id = row.get("account_id", "")
            if not account_id:
                continue
            for required in ("institution_name", "institution_address",
                             "institution_zip", "account_number"):
                if not row.get(required):
                    raise DataError(
                        f"{path} line {lineno}: '{required}' is required and blank. "
                        f"Table A2 marks it mandatory."
                    )
            status = (row.get("status") or "OWNER").upper()
            if status not in VALID_STATUS:
                raise DataError(
                    f"{path} line {lineno}: status {status!r} invalid; must be one of "
                    f"{', '.join(VALID_STATUS)}.\n"
                    f"Note BENIFICIARY is spelled that way on purpose -- the ITD schema "
                    f"and the utility's VBA both misspell it, and the correct spelling "
                    f"is rejected."
                )
            open_date = row.get("account_open_date", "")
            if open_date:
                # Normalise now so the emitter can trust the ISO form.
                open_date = _date(path, lineno, "account_open_date", open_date).isoformat()
            for column, limit in (("institution_name", 125),
                                  ("institution_address", 200),
                                  ("institution_zip", 8), ("account_number", 34)):
                if len(row[column]) > limit:
                    raise DataError(
                        f"{path} line {lineno}: '{column}' is {len(row[column])} chars, "
                        f"but the ITD schema allows at most {limit}. Shorten it."
                    )
            out[account_id] = Account(
                account_id=account_id,
                institution_name=row["institution_name"],
                institution_address=row["institution_address"],
                institution_zip=row["institution_zip"].upper(),
                account_number=row["account_number"],
                status=status,
                account_open_date=open_date,
                country_code=row.get("country_code") or "2",
                country_name=row.get("country_name") or "UNITED STATES OF AMERICA",
            )
    if not out:
        raise DataError(f"{path}: no account rows found")
    return out


def read_cash_balances(path: str) -> dict[tuple[str, int], CashBalance]:
    """Optional file. A missing file means "no cash reported", not an error.

    Returns an empty dict when the file is absent so the caller can warn rather than fail:
    omitting cash understates Table A2 but does not make the rest of the return wrong.
    """
    out: dict[tuple[str, int], CashBalance] = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        _require_columns(path, reader.fieldnames, ["account_id", "year"], "cash balances")
        for lineno, row in enumerate(reader, start=2):
            row = {(k or "").strip(): v for k, v in row.items()}
            if not any((v or "").strip() for v in row.values()):
                continue
            account_id = (row.get("account_id") or "").strip()
            if not account_id:
                continue
            raw_year = (row.get("year") or "").strip()
            try:
                year = int(raw_year)
            except ValueError as exc:
                raise DataError(
                    f"{path} line {lineno}: year {raw_year!r} is not a 4-digit calendar "
                    f"year"
                ) from exc
            key = (account_id, year)
            if key in out:
                raise DataError(
                    f"{path} line {lineno}: a second row for account {account_id} in "
                    f"{year}. One row per account per calendar year -- combine them."
                )
            peak = _dec(path, lineno, "peak_usd", row.get("peak_usd", ""), Decimal(0))
            closing = _dec(
                path, lineno, "closing_usd", row.get("closing_usd", ""), Decimal(0)
            )
            if peak < 0 or closing < 0:
                raise DataError(
                    f"{path} line {lineno}: cash balances cannot be negative. A margin "
                    f"debit is a liability, not a negative asset; report it as zero cash."
                )
            if closing > peak:
                raise DataError(
                    f"{path} line {lineno}: closing_usd {closing} exceeds peak_usd "
                    f"{peak}. The 31 December balance is one of the days the peak is "
                    f"taken over, so the peak can never be the smaller number."
                )
            raw_peak_date = (row.get("peak_date") or "").strip()
            peak_date = (
                _date(path, lineno, "peak_date", raw_peak_date)
                if raw_peak_date else None
            )
            if peak_date and peak_date.year != year:
                raise DataError(
                    f"{path} line {lineno}: peak_date {peak_date} is not in {year}."
                )
            out[key] = CashBalance(
                account_id=account_id,
                year=year,
                peak_usd=peak,
                closing_usd=closing,
                peak_date=peak_date,
                notes=(row.get("notes") or "").strip(),
                source_ref=f"{os.path.basename(path)}:{lineno}",
            )
    return out


def cross_check(transactions, issuers, accounts) -> None:
    """Catch dangling references before any expensive price fetching happens."""
    missing_issuers = sorted({t.ticker for t in transactions} - set(issuers))
    if missing_issuers:
        raise DataError(
            "These tickers appear in transactions.csv but have no row in issuers.csv: "
            + ", ".join(missing_issuers)
            + "\nEvery ticker needs issuer name/address/zip/nature for its Table A3 row. "
            "Remember Table A3 describes the COMPANY (e.g. Cisco Systems, Inc.), "
            "not the broker."
        )
    missing_accounts = sorted({t.account_id for t in transactions} - set(accounts))
    if missing_accounts:
        raise DataError(
            "These account_ids appear in transactions.csv but have no row in "
            "accounts.csv: " + ", ".join(missing_accounts)
        )


def write_template(path: str, columns: list[str], example_rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in example_rows:
            writer.writerow({c: row.get(c, "") for c in columns})


def write_transactions(path: str, transactions: list[Transaction]) -> None:
    """Emit normalised transactions, so adapter output can be reviewed and hand-edited.

    Writes `expense_usd` (brokerage/commission), `paid_price_usd` (the discounted ESPP
    price, where the cost basis is the FMV instead) and `disposal_kind` (a sell-to-cover at
    vest) alongside the required columns even though all three are optional on read -- new
    output should carry them when a broker export has them, without breaking older
    hand-filled files that predate any of them.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fieldnames = (TRANSACTION_COLUMNS[:6] + ["paid_price_usd"]
                  + TRANSACTION_COLUMNS[6:8] + ["expense_usd"]
                  + TRANSACTION_COLUMNS[8:9] + ["disposal_kind"]
                  + TRANSACTION_COLUMNS[9:])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for t in sorted(transactions, key=lambda x: (x.date, x.ticker, x.txn_type)):
            writer.writerow({
                "account_id": t.account_id,
                "ticker": t.ticker,
                "txn_type": t.txn_type,
                "date": t.date.isoformat(),
                "quantity": _plain(t.quantity) if t.quantity else "",
                "price_usd": _plain(t.price_usd) if t.price_usd else "",
                "paid_price_usd": (
                    _plain(t.paid_price_usd) if t.paid_price_usd else ""
                ),
                "amount_usd": _plain(t.amount_usd) if t.amount_usd is not None else "",
                "tax_withheld_usd": (
                    _plain(t.tax_withheld_usd) if t.tax_withheld_usd else ""
                ),
                "expense_usd": _plain(t.expense_usd) if t.expense_usd else "",
                "acq_kind": t.acq_kind,
                "disposal_kind": t.disposal_kind,
                "lot_id": t.lot_id,
                "notes": t.notes,
            })


def _plain(value: Decimal) -> str:
    """Decimal -> string without scientific notation or trailing zero noise."""
    text = format(value.normalize(), "f")
    return text
