# Synthetic split / cash fixtures — none of this is anyone's data

**Every figure here is invented**, on the same terms as [`../synthetic/`](../synthetic/README.md)
— read that file for what is real in these fixtures (the broker names, the public corporate
addresses) and what is not (everything about the holding). The account numbers are again
`SYNTH-ET-0001`, `SYNTH-FD-0002` and `SYNTH-IM-0003`.

This is the second dataset, built around one real, datable corporate action: **Broadcom's
10-for-1 stock split of 15 July 2024.** The split is real; the 10 AVGO shares held across it are
not, and neither is the cash sitting beside them.

It exists to cover three things the first dataset does not:

- **Splits.** `transactions.csv` buys 10 AVGO on 2023-11-15 at a pre-split price and holds it
  through the split, so the same holding is worth ₹21,22,463 on one basis and ₹2,12,246 on the
  other. `build` refuses to run against it without `--split-basis`, and the refusal names the
  ticker, the date and the ratio. That refusal is the point: getting the basis wrong is a
  factor-of-ten misstatement, so the tool stops rather than guess.
- **Cash.** `cash_balances.csv` carries three years of uninvested balances, including one row
  with `peak_date` deliberately left blank so the 31 December rate is used instead.
- **The ₹20 lakh threshold report.** On `--split-basis historical`, which is the basis these
  rows are actually on, the dataset is sized so that 2024 lands **over** the Black Money Act
  section 43 threshold on the peak basis (₹21,52,150) and **under** it at 31 December
  (₹19,85,395). That is what makes the straddle warning fire.

`tests/test_splits_cash_threshold.py` is the suite that reads it. Try it directly with:

```bash
.venv/bin/python -m itrprep.cli threshold --work tests/synthetic_split --years 2022-2025 \
    --split-basis historical
```

The same command with `--split-basis current` reports every year **under** the threshold, on the
same rows. That is the factor-of-ten error, in the one place where it changes a statutory
verdict rather than just a figure.

If you are adding a fixture here, invent every figure and keep the `notes` column saying what
the row is for. [`CONTRIBUTING.md`](../../CONTRIBUTING.md) has the rule.
