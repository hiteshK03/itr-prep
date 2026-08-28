# Supported brokers, and what to export from each

*Part of [itr-prep](../README.md) — what to export from E*TRADE, Fidelity NetBenefits and INDmoney.*

Three providers have adapters, covering the usual shape of Indian-resident US equity
holdings: an employer stock-plan account, an ESPP administrator, and a retail app. Menu
paths are from each provider's UI as of the 2025 exports the adapters were built against and
may have shifted; the important thing is the **content**, listed as "must contain". Files are
classified by their header row, not their filename, so a renamed export still works.

Whichever provider you use, export **every year since the account opened**, not just the
reporting year: Table A3 needs each lot's original acquisition date and cost, and a lot
acquired in 2019 still needs its 2019 cost basis to be reported in 2025.

### 1. E\*TRADE / Morgan Stanley StockPlan Connect

The usual home of employer RSUs and ESPP purchases, and typically the account contributing
the most rows.

- **Benefit History** — StockPlan Connect: *Stock Plan → Holdings → Benefit History*, or
  E\*TRADE: *At Work → Holdings → Benefit History* → **Download / Export**
  - must contain: symbol, transaction type (release / vest / ESPP purchase), vest or
    purchase date, quantity, **vest-date fair market value per share**
- **Gains & Losses / Realized Gains** — *At Work → My Account → Gains & Losses*, filtered
  to all years with sales
  - must contain: sale date, quantity sold, sale price, and ideally the acquisition lot it
    came from
- **ESPP purchase confirmations** if the Benefit History omits the purchase price. An ESPP
  discount is typically 15% and it matters for the acquisition cost.

The **"By Benefit Type" / expanded** download of the same screen is an XLSX with one
worksheet per plan — `ESPP` and `Restricted Stock` — and it is the better export to take,
because it states each vest tranche's own cost basis and both the withheld and the
sold-to-cover share counts. All its worksheets are read; check the census names each tab you
can see in Excel.

### 2. Fidelity NetBenefits

Commonly the ESPP administrator where the stock plan is separate from the brokerage account.

- **Stock plan transaction history** — NetBenefits: *Stock Plans → [plan name] →
  View Details / Transaction History*, set the date range to cover every year with activity,
  then **Download**
  - must contain: purchase date, shares purchased, **purchase price per share**, and the
    purchase-date FMV if shown
- **Annual statements** for each year — *Documents → Statements*. Use these to confirm the
  share count still held at each 31 December.
- **Dividend history**, if dividends were paid into the account rather than swept to a bank
  account. Needed for `TotGrossAmtPaidCredited` and for Schedule OS.

### 3. INDmoney (US stocks)

A retail route into US equities, usually the cleanest exporter of the three.

- **US Stocks transaction / order history** — INDmoney app or web: *US Stocks → Portfolio →
  Reports / Transaction History* → export CSV, date range covering **all years held**
  - must contain: date, ticker, buy/sell, quantity, price per share, total amount
  - XLSX exports are read directly, including dates stored as Excel serial numbers
- **Dividend report** — same reports section
  - must contain: date, ticker, gross dividend, **US tax withheld** (usually 25%)
- **US brokerage account statements** — needed for the Table A2 row: the **US broker's legal
  name, address and the account number**. INDmoney routes US investing through a US broker
  (historically DriveWealth LLC) where the investor is the account holder, so the Table A2
  row must name that broker, not INDmoney. Confirm from the statement rather than trusting
  the example in `accounts.csv`.

### Also needed, from your own records

- Account **opening dates** for every account (Table A2).
- Form 1042-S or the equivalent US withholding summary, for Form 67 / Schedule TR.

### An unsupported broker

`normalize` is one adapter per provider and adding one is not much work: a `Profile` in
`itrprep/adapters.py` names the column aliases and the transaction-type keywords. Or skip
`normalize` entirely and write `transactions.csv` yourself — it is four required columns,
documented in the [data dictionary](DATA_DICTIONARY.md), and everything downstream works from that file alone.
