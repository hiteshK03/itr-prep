# Synthetic fixtures — none of this is anyone's data

**Every figure in this directory is invented.** No quantity, price, date, lot, account number
or dividend here came from a real filing, a real brokerage account or a real person. Nothing in
it should be read as a holding, and nothing in it discloses one.

That has to be said out loud, because the fixtures are *shaped* like real exports on purpose —
which is the only way they can prove the readers work — and three things in them are genuinely
real:

- **The broker names are real.** Morgan Stanley Smith Barney LLC (E\*TRADE), Fidelity Brokerage
  Services LLC and DriveWealth LLC are the institutions whose export formats
  `itrprep/adapters.py` supports. A fixture that renamed them would stop testing the
  content-based detection that decides which adapter reads a file.
- **The institution and issuer addresses are real, and public.** Schedule FA Table A3 asks for
  the issuer's name, address and zip code, and Table A2 asks the same of the custodian, so a
  fixture has to carry them or it does not exercise the emitter. These are published corporate
  head-office addresses — the sort of thing on the back of an annual report — and they say
  nothing about who holds what.
- **The AVGO 10-for-1 split of 15 July 2024 is a real corporate action**, used by
  `../synthetic_split/`. The point of that dataset is that the split is real and datable while
  the holding across it is not.

What is invented, and how you can tell:

- **Account numbers** are `SYNTH-ET-0001`, `SYNTH-FD-0002`, `SYNTH-IM-0003`. No real broker
  issues an account number in that shape.
- **Lot IDs** are readable descriptions of their own purpose — `CSCO-V-2025Q1`,
  `JNJ-ESPP-2023H1`, `AVGO-2025-A` — rather than anything a broker would assign.
- **Grant numbers** in `broker_exports/` are `RU100001` and `RU100002`.
- **Quantities, prices, dividends and withholding** were chosen to be plausible against the
  tickers' actual trading ranges and then to exercise a specific case. The `notes` column on
  every row of `transactions.csv` says which case: a mid-year sale of an identified lot, a sale
  with no `lot_id` that must go FIFO, a ticker bought and fully exited inside the year, four
  quarterly dividends across four lots, an ESPP purchase priced legitimately below the close.

## What is here

| File | What it is for |
|---|---|
| `transactions.csv` | The intermediate schema — 24 rows across four tickers and three accounts, covering the cases listed above. This is what `build`, `doctor` and `threshold` read. |
| `issuers.csv` | Table A3's per-issuer details: name, address, zip, nature of entity, country. |
| `accounts.csv` | Table A2's per-custodian details, plus the `account_id` values the transactions refer to. |
| `broker_exports/` | Raw exports in each broker's own shape, for the stage-1 adapters: three E\*TRADE benefit-history files — plain, multi-section, and one deliberately unreadable — plus a Fidelity ESPP export and an INDmoney transaction list. |

There is deliberately no `cash_balances.csv` here — this dataset is the securities-only case, and
the build says so when it finds none. `../synthetic_split/` has one, and covers cash, splits and
the ₹20 lakh threshold report.

`etrade_benefit_history_unreadable.csv` is *meant* to fail. It exists so
`tests/test_multisection_adapter.py` can assert that a row which cannot be read is counted,
named and blocking rather than silently dropped.

## Using this dataset yourself

It needs no broker export, no `work/` directory and no PAN:

```bash
.venv/bin/python -m itrprep.cli build --year 2025 --work tests/synthetic --out /tmp/demo.json
```

The README's [Try it without your own data](../../README.md#try-it-without-your-own-data)
section shows what that prints.

## If you are adding a fixture

Invent every figure, and follow the conventions above rather than starting a new one — `SYNTH-`
for account numbers, a descriptive lot ID, a `notes` column saying what the row is testing.
Never derive a fixture from your own export by editing it down: a redaction that misses one
field is worse than an invention, because nobody re-reads an invented file looking for a leak.
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) has the rule and what to do if real data does get
committed.
