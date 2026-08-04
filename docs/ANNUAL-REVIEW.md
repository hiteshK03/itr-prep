# Annual review — what to re-verify before filing a new assessment year

Every statutory figure this tool uses lives in `rules/AY<year>.json`, cited. Nothing is
computed from memory and nothing is hardcoded at a call site.

Each entry declares a **review class**:

- **`stable`** — fixed by statute and not expected to move: a settled convention or a
  historical date. Carries `applies_to: "all"`. Nothing to do each year.
- **`annual`** — set or revised by a Finance Act, or otherwise dependent on the assessment
  year. **Every one of these must be re-verified before the registry is used for a later
  year.** Carries the assessment year it was stated for.

This file is the checklist for the `annual` entries. It is not advisory:

- `tests/test_rules_registry.py` **fails** if an `annual` entry in **any** registry is
  missing from this file, or if its source URL is not linked here.
- `tests/test_rules_registry.py` **fails** if any `annual` entry in a registry is stated
  for an earlier assessment year than that registry's own.
- `itr-prep build --year N` **refuses to run** if there is no registry for the assessment
  year that `N` files. It does not fall back to the newest one.
- `itr-prep build --year N` for an *earlier* year than the newest registry runs, but prints
  a banner saying which assessment year the figures it used are stated for.

---

## AY 2027-28 is a change of statute, not an annual refresh

**Read this before treating AY 2027-28 as an ordinary year.** It is the first assessment
year decided under a different Act, and almost every section number in this repository
changed on 1 April 2026.

The **Income-tax Act, 2025** (No. 30 of 2025, assented 21 August 2025) came into force on
1 April 2026 by its own section 1(3), and **section 536(1) repealed the Income-tax Act,
1961**. It is a re-enactment rather than a reform: most provisions carry over in substance
under new numbers, but not all of them, and the ones that changed substantively are the
dangerous ones precisely because everything around them looks like a renumbering.

Two consequences run through this whole repository.

**1. AY 2026-27 stays a 1961-Act year, permanently.** Section 536(2)(c) keeps the repealed
Act applying to proceedings for any tax year beginning before 1 April 2026. The AY 2026-27
return was filed under the Income-tax Act, 1961, so `rules/AY2026-27.json`, the runbook,
the changelog and every memo describing that filing **must go on citing the 1961 Act**.
Renumbering them to match the new Act would falsify the record of a filed return, and the
registry suite fails if the old registry stops citing the Income-tax Act, 1961. If you find
an old-Act citation in this tree, it is deliberate; check whether the text around it is
describing AY 2026-27 before "fixing" anything.

**2. Only forward-looking content renumbers.** Guidance for AY 2027-28 onward, and any
statement written as a timeless truth that is now only historically true, cites the Act of
2025 — showing both where a reader needs the bridge.

**The registry does not get find-and-replaced either.** `rules/AY2027-28.json` is a new file
whose every entry carries an `act_transition` block recording the AY 2026-27 entry it
descends from, the old provision, the new provision, and a classification of the change:

| `change` | Meaning |
|---|---|
| `renumbered_only` | Same rule, new number. Nothing to re-decide. |
| `renumbered_and_substantive` | The rule itself moved. **Read the entry's `statute` and `check` text before relying on it.** |
| `unchanged_separate_legislation` | Not part of the Income-tax Act at all, so untouched by the repeal. |
| `new_entry` | No AY 2026-27 counterpart. The old provision is recorded anyway, for a reader coming from 1961-Act material. |

The suite checks that every AY 2026-27 entry is accounted for by name in AY 2027-28, so an
entry cannot be silently dropped on the way across.

### The old → new mapping

Generated from the `act_transition` blocks in `rules/AY2027-28.json`; that file is the
source of truth and this table is the readable form of it.

| AY 2026-27 entry | Old provision | New provision | Change |
|---|---|---|---|
| `schedule_fa_reporting_basis` | Fourth proviso to s.139(1), Act of 1961 | s.263(1)(a)(ix) and 263(1)(b), Act of 2025, with rule 164(4) of the Rules 2026 | `renumbered_only` |
| `schedule_fa_reporting_period` | Calendar year 2025, previous year 2025-26 | Calendar year 2026, tax year 2026-27 | `renumbered_only` |
| `schedule_fa_fx_convention` | TT buying rate as defined in rule 115(1), Rules 1962 | TT buying rate as defined in rule 207, Rules 2026 | `renumbered_only` |
| `income_fx_convention_rule_115` → `income_fx_convention_specified_date` | Rule 115(2), Rules 1962, sub-clauses (e) and (f) | Rule 206(2)(b)(i), Rules 2026, Table Sl. Nos. 5 and 6 | `renumbered_only` |
| `equity_perquisite_cost_of_acquisition` | ss.17(2)(vi) and 49(2AA), Act of 1961 | ss.17(1)(d) and 73(1) Table Sl. No. 4, Act of 2025 | `renumbered_only` |
| `transfer_expenditure_deductible` | s.48, Act of 1961 | s.72(1)(a), Act of 2025 | `renumbered_only` |
| `schedule_fa_disclosure_unconditional` | Fourth proviso to s.139(1), Act of 1961 | ss.263(1)(a)(ix) and 263(1)(b), Act of 2025 | `renumbered_only` |
| `foreign_share_long_term_holding` | s.2(42A), Act of 1961 | s.2(101)(a), Act of 2025, carve-outs at s.2(101)(b) | `renumbered_only` |
| `black_money_s43_penalty_inr` | Black Money Act 2015, s.43 | Black Money Act 2015, s.43 — **unchanged** | `unchanged_separate_legislation` |
| `black_money_relief_threshold_inr` | Black Money Act 2015, proviso to s.43 | Black Money Act 2015, proviso to s.43 — **unchanged** | `unchanged_separate_legislation` |
| `form_67_deadline` → `foreign_tax_credit_statement_deadline` | Form 67 under rule 128(9), Rules 1962 | **Form 44** under rule 76(10), Rules 2026 | `renumbered_and_substantive` |
| `revised_return_deadline` | s.139(5), Act of 1961 | **s.263(5)**, Act of 2025, as substituted by FA 2026 s.66(b) | `renumbered_and_substantive` |

New in AY 2027-28, with the 1961-Act provision a reader may know them by:

| Entry | Was (Act of 1961) | Now (Act of 2025) |
|---|---|---|
| `mf_grandfathering_cutoff_date`, `mf_grandfathering_valuation_date`, `mf_grandfathering_fmv_basis_unlisted`, `mf_grandfathering_fmv_basis_listed` | s.55(2)(ac) and its Explanation | s.90(7) and s.90(8)(b) |
| `specified_mf_deemed_short_term`, `specified_mf_acquisition_cutoff_date`, `specified_mf_debt_threshold_pct` | s.50AA and its Explanation | s.76(1), s.76(2)(a), s.76(5)(b) |
| `ltcg_equity_rate_pct`, `ltcg_equity_exemption_inr` | s.112A | s.198(2)(a) |
| `stcg_equity_rate_pct` | s.111A | s.196(1)(i) |
| `ltcg_other_rate_pct` | s.112 | s.197(1)(b) |
| `mf_equity_oriented_threshold_pct` | Explanation to s.112A | s.198(8), applied to short-term gains by s.196(5) |
| `mf_holding_period_months` | s.2(42A) | s.2(101)(a) and (b) |
| `mf_unit_indexation_available` | Second proviso to s.48 | s.197(3) with s.72(8) |
| `mf_lot_matching_method` | s.45(2A) | s.67(7)(c) |
| `mf_bonus_unit_cost` | s.55(2)(aa)(iiia) | s.90(6)(d) |

### The Black Money Act is untouched

The Black Money (Undisclosed Foreign Income and Assets) and Imposition of Tax Act, 2015 is
separate legislation. Section 536 of the Income-tax Act, 2025 repeals the 1961 Act and
nothing else, so **section 43 is still section 43**, the penalty is still ₹10,00,000 and the
relief threshold is still ₹20,00,000. Do not renumber Black Money Act citations anywhere in
this tree.

There is, however, an **unresolved cross-reference**, recorded in the
`black_money_s43_penalty_inr` entry's `check` text: section 43 cures the default where the
asset is disclosed in a return furnished under listed sub-sections of **section 139 of the
Income-tax Act, 1961** — an Act that no longer applies to tax year 2026-27. A tax year
2026-27 return is furnished under section 263 of the Act of 2025. Whether that reads onto
section 43's list is not settled by anything primary that could be found, and the Finance
Act, 2026 amended sections 49 and 50 of the Black Money Act while leaving section 43 alone.
Take advice before relying on a section 263 return to cure a Schedule FA omission for a
2025-Act year. See `docs/KNOWN-ISSUES.md`.

---

## How to do a review

1. Copy the newest registry to `rules/AY<next>.json`. **Do not edit an older file** —
   a filed year has to stay reproducible from the registry it was filed against, and if that
   year was filed under a different Act, its citations are historically correct as they are.
2. Update `assessment_year`, `financial_year`, `schedule_fa_calendar_year` and
   `verified_on`.
3. Work through every entry below. For each one: read the official source, confirm or
   correct the value, then set that entry's `applies_to` and `verified_on`.
4. Carry each entry's `act_transition` block across unchanged unless the provision moved
   again. It records where the rule came from, not when it was last reviewed.
5. `.venv/bin/python tests/test_rules_registry.py` — it will tell you what you missed.
6. `ITRPREP_CHECK_SOURCE_URLS=1 .venv/bin/python tests/test_rules_registry.py` to confirm
   no cited URL has 404'd since last year.
7. Run the other suites, then update this file if you added or removed an entry.

**Source discipline.** Primary sources only: the Income-tax Act or Finance Act text, a
CBDT notification or circular, or the department's own site. ClearTax, TaxGuru, Taxmann and
practitioner blogs are fine for *finding* a provision and may be quoted in prose, but must
never be the cited authority for a rate, a limit or a date. The test enforces the domain
rule, so a secondary citation will not merge.

The Gazette is the best source for the Act of 2025 and the Finance Act, 2026: the
department's consolidated "as amended" PDFs return HTTP 403 to every automated client, so
they cannot be diffed, and secondary commentary on them cannot be checked. Where that
mattered, the entry says so rather than guessing.

---

# `rules/AY2027-28.json` — the `annual` entries

Tax year 2026-27, the first year under the Income-tax Act, 2025. Verified 3 August 2026.

**Not yet notified when this registry was written:** the ITR-2 form and instructions for tax
year 2026-27. Rule 164 of the Income-tax Rules, 2026 prescribes ITR-2 for a person without
business income, but the form itself, its schedule numbering and its Schedule FA table
layout are unconfirmed. Re-verify anything form-shaped before filing.

### `schedule_fa_reporting_period`

Calendar year 2026 — 1 January to 31 December 2026.

Derived by advancing AY 2026-27 by one year, **not** confirmed against a notified form.
Confirm against the tax year 2026-27 ITR-2 instructions as soon as they are published. The
calendar-year basis is the single most consequential date in the tool and the error
practitioners make most often, and this is the first year it must be read out of a new Act's
schedule rather than a familiar one.

- [Income-tax Act, 2025 (No. 30 of 2025), Gazette of India](https://egazette.gov.in/WriteReadData/2025/265620.pdf) — s.2(109) "tax year", s.263(1)(a)(ix)
- [ITR-2 instructions and utilities](https://www.incometax.gov.in/iec/foportal/downloads/income-tax-returns)

### `foreign_share_long_term_holding`

24 months / 730 days, for the Schedule CG short-versus-long split. Never used for
Schedule FA.

Section 2(101)(a) of the Act of 2025 sets the default at "not more than twenty-four months".
The twelve-month carve-outs at section 2(101)(b) reach a security listed on a **recognised
stock exchange in India**, a unit of an equity oriented fund and a zero coupon bond — none
of which a foreign-listed share is. Confirm that this assessment year's Finance Act has not
extended the carve-outs; the Finance Act, 2026 amended section 2 only at clauses (32) and
(40). Keep `months` and `days` consistent.

- [Income-tax Act, 2025, s.2(101)](https://egazette.gov.in/WriteReadData/2025/265620.pdf)
- [Finance Act, 2026 (No. 4 of 2026), s.35](https://egazette.gov.in/WriteReadData/2026/271439.pdf)

### `black_money_s43_penalty_inr`

₹10,00,000, flat, per assessment year, for an omitted Schedule FA. **Unchanged** — separate
legislation, not renumbered by the Act of 2025.

Confirm the figure in section 43 is still ₹10,00,000. Then re-read the cross-reference
question above: section 43's cure lists sub-sections of section 139 of the **1961** Act, and
a 2025-Act return is furnished under section 263. Watch for a Finance Act, an amendment Act
or a CBDT circular resolving it — that is the single most useful thing that could change
here.

- [Acts administered by the department, including the Black Money Act, 2015](https://incometaxindia.gov.in/Pages/acts/index.aspx)
- [Finance Act, 2026, Part III, s.160](https://egazette.gov.in/WriteReadData/2026/271439.pdf) — everything it does to the Black Money Act, being provisos to ss.49 and 50 only
- [Income-tax Act, 2025, ss.536 and 263](https://egazette.gov.in/WriteReadData/2025/265620.pdf)

### `black_money_relief_threshold_inr`

₹20,00,000 — the aggregate below which the section 43 penalty is disapplied. **Unchanged.**

**This one has already moved once**, replacing an earlier ₹5,00,000 bank-balance carve-out
with effect from 1 October 2024, so treat it as live. Confirm the figure, and confirm
immovable property is still excluded from the relief. The Finance Act, 2026 inserted
matching provisos into sections 49 and 50 (prosecution) without disturbing this one, so
watch for further movement. The proviso still fixes no valuation date for shares, which is
why the threshold report shows two bases rather than choosing one.

- [Finance Act, 2026, Part III, s.160](https://egazette.gov.in/WriteReadData/2026/271439.pdf)
- [Acts administered by the department, including the Black Money Act, 2015](https://incometaxindia.gov.in/Pages/acts/index.aspx)

### `foreign_tax_credit_statement_deadline`

**Renamed from `form_67_deadline`, and substantively changed.** Form No. 44 under rule 76 of
the Income-tax Rules, 2026, due within **twelve months from the end of the tax year** —
31 March 2028 for tax year 2026-27 — conditional on the return being within the section
263(1) or 263(4) window; on or before the return itself where that return is under section
263(6)(a).

The date advances with the tax year, so re-derive it. Three things changed with the number:

1. The basis moved from the end of the *assessment* year to twelve months from the end of
   the *tax* year. For tax year 2026-27 those coincide at 31 March 2028; they will not
   always, and the rule says tax year.
2. Rule 76(16) requires an **accountant to verify** Form 44 where the assessee is a company
   or foreign tax paid for the tax year is ₹1,00,000 or more. Check whether that threshold
   has moved — it is new, and new figures move.
3. A new **Form No. 45** intimates the **settlement of a dispute** over foreign tax whose
   credit was not claimed, under rule 76(6) read with rule 76(15). There was no counterpart
   under the 1962 Rules. It is not the refund form: rule 76(14) keeps a later refund of
   foreign tax already credited on **Form No. 44**, in its Part C.

- [CBDT Notification No. 22/2026, G.S.R. 198(E) — Income-tax Rules, 2026, rule 76 and Form No. 44](https://www.incometax.gov.in/iec/foportal/sites/default/files/2026-03/En-Notified-IT-Rules-2026-20-03-2026.pdf)
- [Income-tax Act, 2025, ss.159, 160 and 263](https://egazette.gov.in/WriteReadData/2025/265620.pdf)

### `revised_return_deadline`

31 March 2028 — twelve months from the end of tax year 2026-27 — under **section 263(5)** of
the Act of 2025 as substituted by section 66(b) of the Finance Act, 2026. Fee-free until
31 December 2027.

A revised return is the only self-help cure for a Schedule FA omission in the current year,
so its deadline matters more here than it looks.

Two things to re-check for a later year:

1. The date is twelve months from the end of the tax year and moves with it, so re-derive
   rather than copy. Note the second limb too — completion of the assessment closes the
   window earlier.
2. Read **section 428(b)** as substituted by section 96 of the Finance Act, 2026 as it then
   stands. It charges ₹1,000 where total income does not exceed ₹5,00,000 and ₹5,000
   otherwise, on a return furnished after nine months from the end of the tax year.
   **Under the Act of 2025 this fee window is actually reachable**, at 31 December 2027,
   which it was not under the 1961-Act counterpart: section 234-I as enacted measured its
   nine and twelve months from the end of the *assessment* year, so it opened only after
   section 139(5) had already closed. The Act of 2025 measures both from the end of the tax
   year, and the anomaly disappears. Budget for the fee.

- [Finance Act, 2026, s.66(b) substituting s.263(5), and s.96 substituting ss.427 and 428](https://egazette.gov.in/WriteReadData/2026/271439.pdf)
- [Income-tax Act, 2025, s.263 as enacted](https://egazette.gov.in/WriteReadData/2025/265620.pdf)
- [Memorandum explaining the provisions of the Finance Bill, 2026](https://www.indiabudget.gov.in/doc/memo.pdf)

### `specified_mf_debt_threshold_pct` — **contested**

65% — a Specified Mutual Fund is one investing **more than 65%** of its total proceeds in
debt and money market instruments, or a fund investing more than 65% of its proceeds in such
a fund. Section 76(5)(b) of the Act of 2025.

**This is flagged `contested` and the flag should not be cleared without a primary source.**
The 1961-Act predecessor (section 50AA) was drafted the other way round — *not more than 35%
in domestic equity* — so the polarity flipped when the Act was re-enacted, and any
implementation carried over from a 1961-Act codebase will have the test inverted. Secondary
commentary also describes a **90-day averaging or liquidity-buffer carve-out** that does not
appear anywhere in the Gazette text of section 76. It could not be established whether the
Finance Act, 2026 introduced one: Part B of its Chapter III does not amend section 76, but
the department's consolidated as-amended PDF returns 403 to every automated client, so the
possibility of an amendment reaching it by another route could not be excluded.

Misclassification here is silent and expensive — it moves a gain between the section 196/198
rates and slab rates. See `docs/KNOWN-ISSUES.md`.

- [Income-tax Act, 2025, s.76(5)(b)](https://egazette.gov.in/WriteReadData/2025/265620.pdf)
- [Finance Act, 2026, Part B of Chapter III](https://egazette.gov.in/WriteReadData/2026/271439.pdf) — the complete list of its amendments to the Act of 2025, which does not include s.76

### `ltcg_equity_rate_pct` and `ltcg_equity_exemption_inr`

12.5% on long-term capital gains **exceeding ₹1,25,000**, on an equity share, a unit of an
equity oriented fund or a unit of a business trust where STT has been paid. Section
198(2)(a) of the Act of 2025.

Both figures are Finance Act territory and the rate moved as recently as 23 July 2024, so
re-verify both every year. The ₹1,25,000 threshold appears independently in rule 164(2)(d)
of the Income-tax Rules, 2026 — if the two ever disagree, the Act governs and the
disagreement is itself worth reporting.

- [Income-tax Act, 2025, s.198](https://egazette.gov.in/WriteReadData/2025/265620.pdf)
- [Finance Act, 2026, Part B of Chapter III](https://egazette.gov.in/WriteReadData/2026/271439.pdf) — does not amend s.198
- [CBDT Notification No. 22/2026 — Income-tax Rules, 2026, rule 164(2)(d)](https://www.incometax.gov.in/iec/foportal/sites/default/files/2026-03/En-Notified-IT-Rules-2026-20-03-2026.pdf)

### `stcg_equity_rate_pct`

20% on short-term capital gains on an equity share, a unit of an equity oriented fund or a
unit of a business trust where STT has been paid. Section 196(1)(i) of the Act of 2025.

Also moved on 23 July 2024, from 15%. Re-verify. Note that section 196(5) borrows section
198's definition of an equity oriented fund, so the 65% and 90% thresholds below govern both
rates.

- [Income-tax Act, 2025, s.196](https://egazette.gov.in/WriteReadData/2025/265620.pdf)
- [Finance Act, 2026, Part B of Chapter III](https://egazette.gov.in/WriteReadData/2026/271439.pdf) — does not amend s.196

### `ltcg_other_rate_pct`

12.5% on a long-term capital gain not caught by section 198 — a non-equity-oriented fund
whose units are not Specified Mutual Fund units, for instance. Section 197(1)(b).

Re-verify with the section 198 rate; the two moved together in 2024 and may again. There is
**no ₹1,25,000 exemption** on this limb: the threshold belongs to section 198 alone.

- [Income-tax Act, 2025, s.197](https://egazette.gov.in/WriteReadData/2025/265620.pdf)
- [Finance Act, 2026, Part B of Chapter III](https://egazette.gov.in/WriteReadData/2026/271439.pdf) — does not amend s.197

### `mf_holding_period_months`

12 months for an equity oriented fund and for a security listed on a recognised stock
exchange in India; 24 months for everything else, including an unlisted or non-equity fund.
Section 2(101).

Re-verify alongside `foreign_share_long_term_holding`, which reads the same section for a
different asset. The two must stay consistent.

**This entry does not decide a Specified Mutual Fund unit.** Section 76 overrides it —
see the trap recorded in `specified_mf_deemed_short_term` below.

- [Income-tax Act, 2025, s.2(101)](https://egazette.gov.in/WriteReadData/2025/265620.pdf)
- [Finance Act, 2026, s.35](https://egazette.gov.in/WriteReadData/2026/271439.pdf)

### `mf_unit_indexation_available`

`false`. No provision of the Act of 2025 gives an indexed cost of acquisition to a mutual
fund unit.

The Act keeps the machinery — section 72(8) defines indexed cost of acquisition, and section
197(3) preserves the resident-individual land-and-building election at 20% with indexation —
but nothing extends it to units. Re-verify by re-reading section 197(3): if a Finance Act
widens that election, this flips, and it flips silently because the arithmetic still runs.

- [Income-tax Act, 2025, ss.197(3) and 72(8)](https://egazette.gov.in/WriteReadData/2025/265620.pdf)

---

# `rules/AY2026-27.json` — the `annual` entries

**Filed year, 1961-Act citations, do not renumber.** Kept in the checklist so that its
source links stay checkable and its URLs stay monitored by
`ITRPREP_CHECK_SOURCE_URLS=1`. Nothing here needs re-verifying for a future year — the
successor entries above have already been re-verified under the Act of 2025 — but if one of
these turns out to have been *wrong*, the filed return was wrong, which is worth knowing.

| Entry | Value as filed | Provision (Act of 1961 unless stated) |
|---|---|---|
| `schedule_fa_reporting_period` | Calendar year 2025 | ITR-2 instructions, Schedule FA |
| `foreign_share_long_term_holding` | 24 months / 730 days | s.2(42A) |
| `black_money_s43_penalty_inr` | ₹10,00,000 | Black Money Act 2015, s.43 |
| `black_money_relief_threshold_inr` | ₹20,00,000 | Black Money Act 2015, proviso to s.43 |
| `form_67_deadline` | End of the assessment year | Form 67, rule 128(9), Rules 1962 |
| `revised_return_deadline` | 31 March 2027 | s.139(5) as substituted by FA 2026 s.5(b) |

Two of those were settled during the AY 2026-27 filing and the reasoning is worth keeping:

- **`form_67_deadline`.** End of the assessment year, conditional on the return being filed
  within the section 139(1) or 139(4) window; on or before the return itself where that
  return is under section 139(8A). **AY 2026-27 is the last year on Form 67**, because
  income of FY 2025-26 stays under the Income-tax Act, 1961. Succeeded by
  `foreign_tax_credit_statement_deadline` above.
- **`revised_return_deadline`.** Settled on 3 August 2026; the `contested` flag was removed
  and the value corrected from 31 December 2026 to 31 March 2027. Our own research memos
  disagreed: one read section 139(5) as three months before the end of the assessment year;
  two read a Finance Act 2026 substitution as running to the end of the assessment year. The
  two were right — section 5(b) of the Finance Act, 2026 substituted section 139(5), with
  effect from 1 March 2026, to read "at any time before the end of the relevant assessment
  year or before the completion of the assessment, whichever is earlier". Section 234-I,
  inserted by section 16 of the same Act, charges a fee on a revised return furnished after
  the nine-month point but measures that point from the end of the **assessment** year, so
  read literally the fee window opened only after section 139(5) had already closed. That
  anomaly does not survive into the Act of 2025.

Source links for those entries, kept live for the URL check:

- [Step by Step Guide to Fill Schedules FSI, TR and FA](https://www.incometax.gov.in/iec/foportal/sites/default/files/2026-03/Step%20by%20Step%20Guide%20FA%20FSI.pdf)
- [Income-tax Act, 1961](https://incometaxindia.gov.in/pages/acts/income-tax-act.aspx) — ss.2(42A) and 139(5)
- [Income-tax Rules, 1962, rule 128](https://incometaxindia.gov.in/pages/rules/income-tax-rules-1962.aspx)
- [CBDT notifications index — Notification No. 100/2022 dated 18 August 2022](https://incometaxindia.gov.in/pages/communications/notifications.aspx)
- [CBDT, FAQs on Budget 2026](https://www.incometaxindia.gov.in/documents/20117/15766092/FAQs-Budget-2026.pdf)
- [Finance Act, 2026 (No. 4 of 2026), ss.5(b) and 16](https://egazette.gov.in/WriteReadData/2026/271439.pdf)
- [Finance Bill, 2026, Notes on Clauses — clauses 5 and 12](https://www.indiabudget.gov.in/doc/Finance_Bill.pdf)

---

## The `stable` entries, and why they are not on the list

Listed so that a reviewer can see the judgement rather than having to infer it. Citations
are to the Act of 2025 as the current statute; `rules/AY2026-27.json` holds the 1961-Act
form of the same entries and is correct as it stands.

| Entry | Why stable |
|---|---|
| `schedule_fa_reporting_basis` | The calendar-year basis exists to line Schedule FA up with the CRS/FATCA reporting period. Structural, not a Finance Act figure. |
| `schedule_fa_fx_convention` | The department's own guide fixes each amount to the TT buying rate on the date it relates to. Re-read only if the guide is reissued. |
| `income_fx_convention_specified_date` | The specified date has been the last day of the preceding month throughout; rule 206 of the Rules 2026 restates rule 115(2) of the Rules 1962 as a table. |
| `equity_perquisite_cost_of_acquisition` | Sections 17(1)(d) and 73(1) together, structural to how employer equity is taxed. |
| `transfer_expenditure_deductible` | Section 72(1)(a). Unchanged in substance for decades. |
| `schedule_fa_disclosure_unconditional` | There is no de minimis for Schedule FA. Worth re-reading the instructions for any newly introduced threshold, but no figure to check. |
| `mf_grandfathering_cutoff_date` | 1 February 2018. A historical date fixed by statute; it has not moved since 2018 and cannot without disturbing settled bases. |
| `mf_grandfathering_valuation_date` | 31 January 2018 — **one day earlier than the cutoff, deliberately**. Also historical. |
| `mf_grandfathering_fmv_basis_unlisted` | Net asset value, from section 90(8)(b)(iii). A basis, not a figure. **Carries a trap — see below.** |
| `mf_grandfathering_fmv_basis_listed` | Highest price quoted on the exchange on 31 January 2018, from section 90(8)(b)(i)–(ii). |
| `specified_mf_deemed_short_term` | The override in section 76(1) is structural. **Carries a trap — see below.** |
| `specified_mf_acquisition_cutoff_date` | 1 April 2023. Historical, and the date the Finance Act 2023 chose; it does not advance. |
| `mf_equity_oriented_threshold_pct` | 65% direct / 90% fund-of-funds, from section 198(8). Definitional rather than a rate — but if a Finance Act ever moves it, it moves both the section 196 and section 198 limbs at once. |
| `mf_lot_matching_method` | FIFO, mandatory for depository-held securities under section 67(7)(c) and universal RTA practice for statement-of-account holdings. |
| `mf_bonus_unit_cost` | Nil, from section 90(6)(d). Structural. |

## The two traps in the mutual fund entries

Both produce a plausible-looking wrong number rather than an error, which is why they are
structured `implementation_trap` blocks in the registry rather than prose in a memo, and why
`tests/test_rules_registry.py` fails if either is removed or hollowed out.

**`mf_grandfathering_fmv_basis_unlisted` — the AMFI NAV column.** AMFI's 31 January 2018 NAV
history file carries both a *Net Asset Value* column and a *Repurchase Price* column, and
they differ on **4,756 of its 9,502 rows**. Section 90(8)(b)(iii) requires the net asset
value. Reading the wrong column understates roughly half of all grandfathered cost bases,
with a number that looks entirely reasonable. Read the column by name and never by position,
test against a row where the two differ, and vendor the file with its SHA-256 rather than
re-downloading it — AMFI's endpoint is not versioned.

**`specified_mf_deemed_short_term` — section 76 overrides the holding period.** Section 76(1)
applies "Irrespective of anything contained in section 2(101)": a Specified Mutual Fund unit
acquired **on or after 1 April 2023** is short-term however long it was held. Any pipeline
that computes `holding_days` first and classifies second gets every one of these wrong, and
a single folio routinely holds lots on both sides of that date, so the bug will not show up
as "this fund is wrong" — it will show up as some lots being right. Classify by acquisition
date and fund type *before* the holding period is consulted, not after.

## Out of scope, deliberately

This registry covers **foreign asset disclosure, the schedules that depend on it, and
Indian mutual fund capital gains**. Slab rates, surcharge tiers and Chapter VI-A deductions
are **not** here, and neither is anything needed only to compute a final tax liability.

The scope widened with AY 2027-28. Section 112A and the 31 January 2018 grandfathering date
under section 55(2)(ac) were previously out of scope, correctly, because foreign shares are
never section 112A assets. Their Act-of-2025 successors — sections 198 and 90(7)–(8) — are
now **in** scope, because they govern Indian mutual fund units. If a figure is not needed to
produce Schedule FA, Indian mutual fund capital gains, or the Schedule CG, OS, FSI and TR
aggregates that hang off them, it does not belong in the registry.
