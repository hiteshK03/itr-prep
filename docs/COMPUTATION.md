# How the numbers are computed

*Part of [itr-prep](../README.md) — lots, FX rates, peak values, splits, the Indian-securities refusal, Table A2 and cash.*

### Reporting period

1 January to 31 December of `--year`. A holding gets a row if it was held **at any time**
during that window, which is the ITD's own test:

> Taxpayers must furnish details of foreign assets or accounts of the following nature,
> held at any time during the relevant calendar year ending on December 31st
> — ITD step-by-step guide, "Overview of Tables A1 to G"

So a ticker bought in March and fully sold in August still gets a row, with a nil closing
balance.

### One row per lot

Each acquisition (each RSU vest, each ESPP purchase, each market buy) becomes its own
Table A3 row. Table A3 asks for an *acquisition date* and an *initial value of investment*,
both properties of a single acquisition rather than of a ticker, so aggregating lots would
force you to invent one. This is why a few years of quarterly vests produces a large
Schedule FA — that is expected and correct.

Sales are matched to lots by `lot_id` when the export identifies one, otherwise **FIFO**
within the same account and ticker.

### Exchange rates — SBI TT buying rate, per date

The ITD is specific about which date's rate applies to which field:

> Exchange Rate Conversion: All peak balances, values of investment, and amounts of
> foreign-sourced income must be converted into Indian currency using the telegraphic
> transfer buying rate of the foreign currency as on the relevant date: the date of peak
> balance in the account, the date of investment, or the closing date of the calendar year
> ending on December 31st.
> — ITD step-by-step guide, "Currency Conversion and Valuation Guidelines"

Implemented as:

| Field | Rate date |
|---|---|
| `InitialValOfInvstmnt` | the acquisition date |
| `PeakBalanceDuringPeriod` | the date the peak occurred |
| `ClosingBalance` | 31 December |
| `TotGrossAmtPaidCredited` | each dividend's date |
| `TotGrossProceeds` | each sale's date |

Rates come from [`sahilgupta/sbi-fx-ratekeeper`](https://github.com/sahilgupta/sbi-fx-ratekeeper)
(`TT BUY` column), cached to `data/sbi_ttbuy_usd.csv` by `itr-prep fx-update` so filing-time
runs need no network. Two details:

- **Non-publication days carry forward.** SBI publishes nothing at weekends, on Indian bank
  holidays, and occasionally publishes a card with no TT rate at all (54 such rows in the
  file, treated as missing). The most recent published rate on or before the date is used.
  The audit CSV records every substitution, e.g. `initial FX carried from 2024-08-14` for a
  15 August vest, 15 August being Independence Day.
- **One rate per date.** SBI occasionally revises intraday; 12 of ~1,600 dates have two
  cards. The **first** card of the day is used, so a date always maps to one reproducible
  number.

**Schedule CG and Schedule OS use a different, specified-date convention.** Rule 115(2)
of the Income-tax Rules, 1962 specifies the exchange-rate date for capital gains
(sub-clause (f)) and dividend income (sub-clause (e)) as **the last day of the month
immediately preceding** the month of transfer / dividend, not the transaction's own date;
rule 206 of the Income-tax Rules, 2026 restates the same convention as a table (Table
Sl. Nos. 6 and 5) for tax year 2026-27 onwards --
applied to *both* the cost-of-acquisition leg and the sale-proceeds leg. This is
deliberately different from the per-date convention above, which is Schedule FA's own,
separately documented rule. Confirmed against a real broker's own tax report: their
displayed exchange rate for a lot bought 2024-08-02 was the 2024-07-31 rate, not the
2024-08-02 rate. `positions._rule115_specified_date` implements this; only
`compute_year_totals` (Schedule CG/OS) uses it -- `compute_rows` (Schedule FA) does not.

### Peak value — the interpretive part

For each lot, for each day it was held during the year, the tool computes
`shares held that day x that day's closing price`, then takes the maximum. Share counts
change as lots vest and are sold, so this is driven by a genuine per-lot daily position
timeline rather than a year-end snapshot.

Three choices are worth stating plainly, because practitioners differ:

1. **Closing prices, not intraday highs.** A holding's value on a day is what it was worth
   at that day's close. Using intraday highs would report a value the taxpayer never held
   at any measurable point. Non-trading days carry the last close forward.

2. **The peak is found in USD, then converted at that date's rate** (`--peak-basis usd`,
   the default). This follows the ITD's wording literally: it says to use the rate "as on
   the date of peak balance", which presupposes the peak has already been identified —
   necessarily in the foreign currency.

   The alternative reading is to maximise the rupee value directly, since that is the
   number actually disclosed. `--peak-basis inr` does this. It is **always greater than or
   equal to** the default, so it is the more conservative disclosure. If your CA prefers it,
   use it; the difference is usually small, arising only when the peak USD date and the peak
   INR date differ.

   Where the USD value ties across several days — which happens over every weekend, since
   the position is carried at its last traded price — the tie is broken toward the higher
   rupee value. Without that, a lot acquired just before a year-end weekend could report a
   peak below its own 31 December closing value.

3. **Table A2's account peak is the sum of its holdings' peaks.** Those holdings do not all
   peak on the same day, so this slightly overstates the true account peak. It errs toward
   over-disclosure, and Table A2 asks for a peak balance rather than a same-day snapshot.

All amounts are rounded to whole rupees, because the schema types every Schedule FA money
field as `integer`.

### Stock splits: the build stops rather than guess

A split changes your share count with no transaction to record. Worse, **Yahoo's historical
closes are retroactively split-adjusted and your broker statement is not**, so for a holding
that spans a split the two are on different footings and the value comes out wrong by the
split ratio — for AVGO's 10-for-1 split of 15 July 2024, by a factor of ten.

The tool reads split events from the same Yahoo chart endpoint it already uses for prices
(`events=div,split`), so detection needs no new dependency. If any transaction pre-dates a
split, **the build stops**:

```
STOCK SPLIT DETECTED -- refusing to compute values that could be wrong by the split factor.

Splits affecting your holdings:
  AVGO: 10-for-1 split effective 2024-07-15
...
  2023-11-15 AVGO BUY qty=10 @ 975.40 [work/transactions.csv line 2] factor 10
      evidence: recorded 975.40 vs unadjusted close 975.400010
                (adjusted 97.540001 x 10):
                looks like the price of the day -> looks historical
```

It stops rather than adjusting automatically because **the data cannot tell it which basis
you are on**. A CSV re-downloaded from the broker today usually shows historical lots
already restated to post-split share counts; a statement saved in 2023 does not. Both are
legitimate, and they differ by exactly the factor at issue. So the tool guesses for you and
shows its working — comparing your recorded price against the adjusted and unadjusted
closes for that date — then makes you confirm:

| Flag | Meaning |
|---|---|
| `--split-basis current` | Quantities are **already restated** post-split. Nothing is changed: on a pre-split day, post-split shares × adjusted close is already right. |
| `--split-basis historical` | Quantities are **as printed at the time**. Each affected row is restated (quantity × factor, price ÷ factor) before anything is valued. |

To check which you are on, compare the share count on a broker statement dated *after* the
split with the one in your CSV. If they match, you are on `current`.

The choice is echoed on every successful run and every restated row is marked in the audit
CSV, so an adjustment is never silent either. CSCO, JNJ and IVV had no splits in 2022-2025;
AVGO is the live one.

### Indian securities are refused

The scope note at the top of this README has always said Indian mutual funds are not covered,
and for twenty commits nothing enforced it. Put one in `transactions.csv` and the pipeline
treated it as a foreign equity in a foreign custodial account and disclosed it in Schedule FA:
no error, no warning, a complete and plausible-looking return asserting a foreign asset the
filer does not hold. The author of this tool believed for a while that mutual funds were
supported, which is the clearest evidence available that somebody else will make the same
mistake.

So an Indian security is now refused. `doctor`, `build`, `threshold` and `run` all stop:

```
1 holding in this ledger looks like an INDIAN security,
which Schedule FA cannot disclose.

  SYNTHMF
      ISIN INF999Z01ZZ9 is issued under India's ISIN prefix IN, and INF is an Indian mutual fund scheme
        read from transactions.csv:26
...
If one of these is genuinely a FOREIGN security that trips the check,
re-run with --allow-indian-securities.
```

This generalises past mutual funds. An Indian *equity* in Schedule FA is equally wrong, and
ISINs separate the two cleanly: `INE` is an Indian company's share, `INF` an Indian mutual fund
scheme. Both are Indian assets wherever they are held, so neither belongs in Table A2 or
Table A3 — and the department's own field is named `CountryCodeExcludingIndia`, whose enum has
no code for India at all.

**What it keys on.** Structural signals only, because foreign-domiciled funds and ETFs
legitimately belong in Schedule FA and must keep working — `IVV` is an iShares ETF and is in
the synthetic fixtures:

| Signal | Read from |
|---|---|
| An ISIN whose ISO-3166 country prefix is `IN`, twelve alphanumeric characters | the optional `isin` column of `transactions.csv`, or of `issuers.csv` |
| An INR-denominated row | the optional `currency` column of `transactions.csv` |
| An NSE or BSE venue suffix — `.NS`, `.NSE`, `.BO`, `.BSE` | the ticker |
| An issuer whose country is `INDIA` | `issuers.csv` |

It deliberately does **not** read scheme names. "Fund", "Growth", "Direct Plan" and "IDCW" all
appear in the names of legitimate foreign holdings, and matching on them would break the demo
while catching nothing structural.

**What it cannot see.** ISIN is absent from many broker exports, and neither `isin` nor
`currency` is a column anything in this tool produces — both are optional and hand-entered. An
Indian holding entered as a bare ticker with no ISIN and no currency **will not be caught.**
The refusal says so itself rather than only saying it here, because the person who needs to
know is the person being refused — or, worse, the person who is not. This lowers the chance of
the mistake; it does not move the responsibility for what you file.

**The escape hatch**, following the `--allow-dropped-rows` idiom, is
`--allow-indian-securities`. It is accepted by `doctor`, `build`, `threshold` and `run`, and it
turns the check off for every flagged row rather than for the one you had in mind. With it,
`doctor` downgrades the refusal to a warning that names what is being let through.

### Dividends across lots

Dividends are paid per share, not per lot, so with one row per lot they are apportioned by
shares held on the payment date. The apportioned amounts always sum back to the dividend
actually received — `tests/test_pipeline.py` asserts this. A lot that was partly sold
before a later dividend correctly receives a smaller share of it.


# Table A2: do you need the custodial-account rows?

**Recommendation: yes, include them — and the tool does so by default.** Use `--no-a2` to
omit them.

The reasoning, separating what is established from what is judgement:

**Established.** Table A2 is "Details of Foreign Custodial Accounts", and the ITD describes
it as covering *"accounts maintained with foreign custodians, including peak balance,
closing balance, and gross amounts paid or credited (specified by type: interest, dividend,
proceeds from sale, or other income)"*. A US brokerage account holding your shares is a
custodial account on its plain meaning, and the fields it asks for — an account number, an
account-opening date, a nature-of-amount code — only make sense for an account, not for a
shareholding. Table A3 has no account number field at all. So the two tables are asking
about different things, and the schema expects both to be populable.

**Judgement.** Neither the schema nor the validation rules say "if you report equities in
A3 you must also report the account in A2", so an argument exists that A3 alone covers the
economic interest and A2 would double-count. The common practitioner view is the opposite:
report the account in A2 *and* the underlying holdings in A3, because they answer different
questions and the ITD has never treated the sum of Schedule FA tables as a portfolio total.

**Why default to including them.** The penalty asymmetry is stark. Under the Black Money
Act, failure to disclose a foreign asset can attract a penalty of ₹10 lakh per year plus
prosecution exposure, whereas disclosing an account that arguably did not need a row costs
nothing — Schedule FA is informational and its totals do not enter the tax computation.
There is no penalty for over-disclosure and a severe one for under-disclosure.

One caveat worth raising with a professional: the A2 peak is a sum of holding peaks (see
above), so it is deliberately conservative.

### Cash balances — `cash_balances.csv`

Uninvested cash sitting in a brokerage account is part of that account, so leaving it out
understates Table A2. It **cannot be derived** from a trade export: wire transfers in and
out never appear there, so the transaction rows alone can never reconstruct a balance. Give
it directly, read off the broker's own statements:

| Column | Required | Meaning |
|---|---|---|
| `account_id` | yes | Matches `accounts.csv` |
| `year` | yes | Calendar year, e.g. `2024`. One row per account per year |
| `peak_usd` | yes | Highest cash balance during that year |
| `peak_date` | no | Date of that peak. Blank converts the peak at the 31 December rate, noted in the audit CSV |
| `closing_usd` | yes | Cash balance at 31 December |
| `notes` | no | Carried into the audit trail |

The amounts are added to that account's Table A2 peak and closing balances, and are counted
in the threshold report. An account with cash but no securities still gets its A2 row. A
negative balance is rejected — a margin debit is a liability, not a negative asset — as is a
closing balance above the peak, since 31 December is one of the days the peak is taken over.

The file is optional. Leave it out and every run tells you which accounts were counted on
securities alone.
