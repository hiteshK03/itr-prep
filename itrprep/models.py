"""The intermediate data model: what Stage 1 produces and Stage 2 consumes.

Three CSVs make up the intermediate layer:

  transactions.csv  one row per acquisition, disposal or dividend
  issuers.csv       one row per ticker: the *company* details that Table A3 asks for
  accounts.csv      one row per foreign broker account: the details Table A2 asks for

Table A3 describes the issuer (CSCO, Microsoft, each ETF), never the broker. Table A2
describes the broker account itself. Keeping issuers and accounts in separate files is
what makes that distinction impossible to get wrong downstream.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from decimal import Decimal

# transactions.csv
TXN_BUY = "BUY"
TXN_SELL = "SELL"
TXN_DIVIDEND = "DIVIDEND"
TXN_TYPES = (TXN_BUY, TXN_SELL, TXN_DIVIDEND)

# How the shares were acquired. Purely informational: it is carried into the row
# comment/audit report so a reviewer can tell an RSU vest from an ESPP purchase from an
# open-market buy, but it does not change any Schedule FA field.
ACQ_RSU_VEST = "RSU_VEST"
ACQ_ESPP = "ESPP"
ACQ_KINDS = (ACQ_RSU_VEST, ACQ_ESPP, "OPEN_MARKET", "DRIP", "OTHER", "")

# Why a disposal happened, where that changes which lot it comes out of.
#
# TAX_WITHHOLDING is a "sell to cover": at vest the employer keeps part of the gross
# shares to pay withholding tax. It is a genuine transfer of a foreign share -- the gross
# count is what s.17(1)(d) of the Income-tax Act, 2025 charges as a perquisite (s.17(2)(vi)
# of the 1961 Act) and what Schedule FA reports as acquired, and the withheld part is a
# disposal on the same date -- but it can only come
# out of the lot that same event created. Applied FIFO instead, it would draw shares from
# an older lot the employee still holds, putting both lots' quantity and cost basis wrong.
DISPOSAL_TAX_WITHHOLDING = "TAX_WITHHOLDING"
DISPOSAL_KINDS = (DISPOSAL_TAX_WITHHOLDING, "")

TRANSACTION_COLUMNS = [
    "account_id",
    "ticker",
    "txn_type",
    "date",
    "quantity",
    "price_usd",
    "amount_usd",
    "tax_withheld_usd",
    "acq_kind",
    "lot_id",
    "notes",
]

ISSUER_COLUMNS = [
    "ticker",
    "entity_name",
    "entity_address",
    "entity_zip",
    "entity_nature",
    "country_code",
    "country_name",
]

ACCOUNT_COLUMNS = [
    "account_id",
    "institution_name",
    "institution_address",
    "institution_zip",
    "account_number",
    "status",
    "account_open_date",
    "country_code",
    "country_name",
]

# cash_balances.csv -- optional, one row per account per calendar year.
#
# A custodial account's uninvested cash is part of the account, so Table A2's peak and
# closing balances understate the account without it. It cannot be derived from the
# transaction rows: dividends, sale proceeds and wire transfers move cash in and out, and
# the transfers never appear in a trade export at all. So it is supplied directly, read
# off the broker's own year-end and monthly statements.
CASH_COLUMNS = [
    "account_id",
    "year",
    "peak_usd",
    "peak_date",
    "closing_usd",
    "notes",
]


class DataError(Exception):
    """Raised for any problem in user-supplied intermediate data.

    Carries enough context to name the offending file, row and column, because the
    whole point of the fallback CSV workflow is that a human is hand-editing it.
    """


@dataclass
class Transaction:
    account_id: str
    ticker: str
    txn_type: str
    date: dt.date
    quantity: Decimal = Decimal(0)
    price_usd: Decimal = Decimal(0)
    amount_usd: Decimal | None = None
    tax_withheld_usd: Decimal = Decimal(0)
    # Brokerage/commission on this transaction. On a BUY it adds to cost of acquisition;
    # on a SELL it reduces net sale consideration. Both are deductible under s.72(1)(a) of
    # the Income-tax Act, 2025 (s.48 of the 1961 Act).
    expense_usd: Decimal = Decimal(0)
    # What was actually paid per share, where that differs from price_usd: the discounted
    # ESPP price. NOT a cost of acquisition -- s.73(1) of the Income-tax Act, 2025 makes
    # that the FMV the perquisite was charged on under s.17(1)(d) (s.49(2AA) and
    # s.17(2)(vi) of the 1961 Act), which price_usd holds, and the
    # discount has already been taxed as salary through Form 16. Kept because FMV minus
    # paid is the perquisite in Form 12BA, and it is the only evidence of the discount
    # that the export carries.
    paid_price_usd: Decimal = Decimal(0)
    acq_kind: str = ""
    # Set on a SELL only. See DISPOSAL_KINDS.
    disposal_kind: str = ""
    lot_id: str = ""
    notes: str = ""
    source_row: int = 0
    source_file: str = ""

    @property
    def source_ref(self) -> str:
        """Where this row came from, short enough to sit in an audit CSV cell.

        `source_file` is the full path, with the worksheet appended for a workbook,
        because a parse error is read next to the file being fixed. The audit trail is
        read years later next to the broker's own export, where the basename is what
        identifies it and the absolute path is noise -- and, on a published repository,
        a home directory nobody meant to disclose.
        """
        if not self.source_file:
            return ""
        return f"{os.path.basename(self.source_file)}:{self.source_row}"

    @property
    def gross_usd(self) -> Decimal:
        """Total USD changing hands.

        Falls back to quantity * price when the broker export gave one but not the
        other, which is common for vest records that state only an FMV per share.
        """
        if self.amount_usd is not None:
            return self.amount_usd
        return self.quantity * self.price_usd


@dataclass
class Issuer:
    ticker: str
    entity_name: str
    entity_address: str
    entity_zip: str
    entity_nature: str
    country_code: str = "2"
    country_name: str = "UNITED STATES OF AMERICA"


@dataclass
class Account:
    account_id: str
    institution_name: str
    institution_address: str
    institution_zip: str
    account_number: str
    status: str = "OWNER"
    account_open_date: str = ""
    country_code: str = "2"
    country_name: str = "UNITED STATES OF AMERICA"


@dataclass
class CashBalance:
    """Uninvested cash in one account for one calendar year.

    `peak_date` is optional. When absent the peak is converted at the 31 December rate,
    which is stated in the audit trail so the assumption is visible rather than buried.
    """

    account_id: str
    year: int
    peak_usd: Decimal = Decimal(0)
    closing_usd: Decimal = Decimal(0)
    peak_date: dt.date | None = None
    notes: str = ""
    # `file:line` of the row this balance was read from, as for a transaction. Cash is
    # hand-entered off a statement rather than parsed out of an export, which makes it
    # the figure most in need of a pointer back to where it was typed.
    source_ref: str = ""


@dataclass
class Lot:
    """One acquisition, tracked separately for its whole life.

    Table A3 wants an acquisition date and an initial value of investment, both of which
    are properties of a single acquisition rather than of a ticker. So a lot is the
    natural Schedule FA row for RSU/ESPP holdings, where each vest is its own event.

    `uid` is an internal unique key; `lot_id` is the broker's own label and is NOT unique.
    E*TRADE, for instance, stamps every vest from the same award with one grant number, so
    several lots legitimately share a lot_id. Anything keyed per-lot must key on uid, or
    those lots' amounts get merged and then double-counted.
    """

    uid: str
    lot_id: str
    account_id: str
    ticker: str
    acquire_date: dt.date
    original_qty: Decimal
    price_usd: Decimal
    acq_kind: str = ""
    # Brokerage/commission paid to acquire this lot. Deductible against capital gains
    # under s.72(1)(a) of the Income-tax Act, 2025 -- s.48 of the 1961 Act -- as
    # "expenditure incurred wholly and exclusively in connection with such transfer", so
    # it belongs in cost of acquisition, not just informational.
    purchase_expense_usd: Decimal = Decimal(0)
    # The acquisition row this lot was built from, as `file:line`. Carried so that the
    # acquisition date and initial value -- the two Table A3 fields with no other
    # evidence behind them -- can be traced to the export they were read out of.
    source_ref: str = ""
    # (date, qty) of each disposal applied to this lot
    disposals: list = field(default_factory=list)

    @property
    def cost_usd(self) -> Decimal:
        return self.original_qty * self.price_usd + self.purchase_expense_usd

    def qty_on(self, day: dt.date) -> Decimal:
        """Shares still held in this lot at the end of `day`."""
        if day < self.acquire_date:
            return Decimal(0)
        qty = self.original_qty
        for sold_date, sold_qty in self.disposals:
            if sold_date <= day:
                qty -= sold_qty
        return qty if qty > 0 else Decimal(0)

    def fully_exited_before(self, day: dt.date) -> bool:
        return self.qty_on(day) <= 0
