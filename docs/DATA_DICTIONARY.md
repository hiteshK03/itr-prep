# Data dictionary

*Part of [itr-prep](../README.md) — every column of the input CSVs.*

### `transactions.csv`

One row per acquisition, disposal or dividend. All amounts in **USD**.

| Column | Required | Meaning |
|---|---|---|
| `account_id` | yes | Free-form key that must match an `account_id` in `accounts.csv` |
| `ticker` | yes | Trading symbol, e.g. `CSCO`. Must have a row in `issuers.csv` |
| `txn_type` | yes | `BUY`, `SELL` or `DIVIDEND` |
| `date` | yes | `YYYY-MM-DD` preferred. Slashed dates are read as **MM/DD/YYYY** (US brokers) |
| `quantity` | BUY/SELL | Shares, always **positive**. A sale is a `SELL`, never a negative `BUY` |
| `price_usd` | BUY/SELL | Per-share USD cost of acquisition. For a vest this is the **vest-date FMV**. **For ESPP, this is also the FMV at purchase, NOT the discounted price you paid** — see the ESPP note below, this is a common and consequential mistake |
| `amount_usd` | DIVIDEND | Gross USD. Optional for BUY/SELL — derived from quantity x price if blank |
| `tax_withheld_usd` | no | US tax withheld on a dividend. Feeds Form 67 / Schedule TR |
| `expense_usd` | no | Brokerage/commission on a BUY or SELL. Deductible from capital gains under s.72(1)(a) of the Income-tax Act, 2025 (s.48 of the 1961 Act) -- added to cost of acquisition on a BUY, subtracted from sale consideration on a SELL. Omitting this when your broker actually charged commission silently overstates your taxable gain |
| `paid_price_usd` | no | What you actually paid per share on a discounted ESPP purchase, where the export states it separately from FMV. **Never a cost of acquisition** — `price_usd` is, under s.73(1) of the Income-tax Act, 2025 (s.49(2AA) of the 1961 Act). This is audit trail: FMV minus this, times quantity, is the perquisite already taxed through Form 16, so it is what reconciles Schedule FA against Form 12BA item 17. No computation reads it |
| `acq_kind` | no | `RSU_VEST`, `ESPP`, `OPEN_MARKET`, `DRIP`, `OTHER`. Informational for Schedule FA, but `doctor` uses it to recognise an employer stock-plan account and check its row count is plausible |
| `disposal_kind` | no | `SELL` rows only. `TAX_WITHHOLDING` marks shares the employer kept at vest to pay withholding tax (a "sell to cover"). Such a disposal is matched to the lot created by the vest on that **same date**, never FIFO — E\*TRADE stamps one grant number on every vest of an award, so `lot_id` alone would let an older vest absorb it and put both lots' quantity and cost basis wrong |
| `lot_id` | no | Groups an acquisition. On a `SELL`, names which lot was sold. Blank means FIFO |
| `notes` | no | Free text, carried to the audit CSV |
| `isin` | no | The security's ISIN, if you have it. Nothing computes from it; it is read only by the scope guard, which refuses an `IN`-prefixed one. See [Indian securities are refused](COMPUTATION.md#indian-securities-are-refused) |
| `currency` | no | The currency the row is denominated in. Every money column here is USD by definition, so this exists only so that an `INR` row can be caught rather than valued |

Include **every acquisition ever made** that you still held during any year you report,
even from years before the one you are filing. Table A3 needs the original acquisition date
and cost regardless of age, and a `SELL` with no matching `BUY` is rejected.

> #### ⚠️ ESPP cost basis is the FMV at purchase, not the discounted price paid
>
> This is a real, discovered-the-hard-way mistake, not a hypothetical one: an ESPP export's
> `Purchase Price` column (e.g. E\*TRADE's, or Fidelity NetBenefits') is the **discounted**
> price you paid, often 10–15% below market. Under Indian tax law the discount itself is
> taxed separately as **perquisite/salary income** at the time of purchase (s.17(1)(d) of
> the Income-tax Act, 2025, s.17(2)(vi) of the 1961 Act) — so the cost of acquisition
> carried forward for capital gains is the **FMV at
> purchase date**, not the discounted price. Using the discounted price as `price_usd`
> silently understates the cost basis, which **overstates every subsequent capital gain (or
> understates a loss)** — the exact wrong direction for a filer.
>
> This holds regardless of the US broker's own "qualifying" vs "disqualifying disposition"
> distinction (a US-specific concept for whether the *discount* gets ordinary-income or
> capital-gains treatment on the *US* return) — India has no equivalent distinction; the
> FMV-at-purchase basis applies uniformly. A US 1099-B or G&L export sometimes surfaces this
> as two different cost-basis columns (e.g. E\*TRADE's `Purchase Price` vs `Purchase Date
> Fair Mkt. Value` / Adjusted Cost Basis) — always use the FMV column for `price_usd`, never
> the discounted purchase price, whichever export you're reading.
>
> Broker exports commonly carry both a `Purchase Price` and a `Purchase Date FMV` (or
> `Est. Cost Basis (per share)`, or `Grant Date FMV`) column. The `etrade` and `fidelity`
> profiles check every event-date FMV and cost-basis name **before** any paid-price name,
> so an export carrying both is priced at FMV without your intervention, and the discounted
> figure is kept alongside it in `paid_price_usd` as evidence of the perquisite. Read the
> census line: it names the column each concept bound to. If an export carries **only** a
> paid price, the row is still imported — but the run warns that the basis is the discount,
> names the column, and you should replace it with the Form 12BA / Form 16 FMV by hand.
>
> **Separately:** if a sold ESPP lot's US broker export names a specific `Date Acquired` for
> the shares that were sold (common with a disqualifying disposition, since the specific lot
> matters for the ordinary-income calculation), set matching `lot_id` values on that `BUY`
> and its `SELL` row. Without a `lot_id`, disposals are matched **FIFO against your own
> `transactions.csv` file order** — which silently picks the wrong lot (and therefore the
> wrong cost basis and gain/loss) whenever the broker's actual matched lot isn't your
> oldest one.

### `issuers.csv`

One row per ticker, describing the **issuing company** — Table A3 asks about the company,
not your broker.

| Column | Required | Meaning | Max |
|---|---|---|---|
| `ticker` | yes | Matches `transactions.csv` | |
| `entity_name` | yes | Legal name, e.g. `Cisco Systems, Inc.` | 125 |
| `entity_address` | yes | Registered/HQ address | 200 |
| `entity_zip` | yes | Postal code, e.g. `95134` | 8 |
| `entity_nature` | yes | e.g. `Listed Company`, `Exchange Traded Fund` | 34 |
| `country_code` | no | Defaults `2` (USA). Must be a code from the ITD list | |
| `country_name` | no | Defaults `UNITED STATES OF AMERICA` | 55 |
| `isin` | no | The issuer's ISIN, if you have it. Read only by the scope guard | |

Over-length values are an error, not silently truncated, so the filed data always matches
your source.

`country_name` of `INDIA` is refused rather than filed: Schedule FA has no country code for
India, so an issuer row saying so is either an Indian security or a wrong country, and both
are worth stopping.

### `accounts.csv`

One row per foreign brokerage account — this is what Table A2 reports.

| Column | Required | Meaning | Max |
|---|---|---|---|
| `account_id` | yes | Matches `transactions.csv` | |
| `institution_name` | yes | The **broker's** legal name | 125 |
| `institution_address` | yes | Broker's address | 200 |
| `institution_zip` | yes | Broker's postal code | 8 |
| `account_number` | yes | Your account number at that broker | 34 |
| `status` | no | `OWNER` (default), `BENEFICIAL_OWNER`, or `BENIFICIARY` — **that spelling** | |
| `account_open_date` | no | `YYYY-MM-DD`. Defaults to 1 Jan of the reporting year | |
| `country_code` / `country_name` | no | Default USA | |

### `prices_override.csv`

`ticker,date,close_usd`. Overrides or supplies a daily close. Use when a symbol has been
renamed or delisted, when a fetch fails, or when you want to pin a value to a broker
statement. Overrides always win over fetched prices.
