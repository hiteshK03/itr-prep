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

- `tests/test_rules_registry.py` **fails** if an `annual` entry is missing from this file,
  or if its source URL is not linked here.
- `tests/test_rules_registry.py` **fails** if any `annual` entry in a registry is stated
  for an earlier assessment year than that registry's own.
- `itr-prep build --year N` **refuses to run** if there is no registry for the assessment
  year that `N` files. It does not fall back to the newest one.
- `itr-prep build --year N` for an *earlier* year than the newest registry runs, but prints
  a banner saying which assessment year the figures it used are stated for.

## How to do a review

1. Copy `rules/AY2026-27.json` to `rules/AY<next>.json`. **Do not edit the old file** —
   a filed year has to stay reproducible from the registry it was filed against.
2. Update `assessment_year`, `financial_year`, `schedule_fa_calendar_year` and
   `verified_on`.
3. Work through every entry below. For each one: read the official source, confirm or
   correct the value, then set that entry's `applies_to` and `verified_on`.
4. `.venv/bin/python tests/test_rules_registry.py` — it will tell you what you missed.
5. `ITRPREP_CHECK_SOURCE_URLS=1 .venv/bin/python tests/test_rules_registry.py` to confirm
   no cited URL has 404'd since last year.
6. Run the other five suites, then update this file if you added or removed an entry.

**Source discipline.** Primary sources only: the Income-tax Act or Finance Act text, a
CBDT notification or circular, or the department's own site. ClearTax, TaxGuru, Taxmann and
practitioner blogs are fine for *finding* a provision and may be quoted in prose, but must
never be the cited authority for a rate, a limit or a date. The test enforces the domain
rule, so a secondary citation will not merge.

---

## The `annual` entries

### `schedule_fa_reporting_period`

The calendar year Schedule FA reports for this assessment year.

Confirm the calendar year the assessment year's ITR-2 instructions name for Schedule FA.
It advances by one year with the assessment year, but confirm rather than assume — this is
the single most consequential date in the tool, and the calendar-year basis is the error
practitioners make most often.

- [Step by Step Guide to Fill Schedules FSI, TR and FA](https://www.incometax.gov.in/iec/foportal/sites/default/files/2026-03/Step%20by%20Step%20Guide%20FA%20FSI.pdf)
  — note the URL carries a date path and will change when the department reissues it
- [ITR-2 instructions and utilities](https://www.incometax.gov.in/iec/foportal/downloads/income-tax-returns)

### `foreign_share_long_term_holding`

24 months / 730 days, for the Schedule CG short-versus-long split. Never used for
Schedule FA.

Holding periods were rewritten by the Finance (No. 2) Act 2024 with effect from
23 July 2024. Re-read section 2(42A) as amended by this assessment year's Finance Act and
confirm unlisted shares are still at 24 months. Keep `months` and `days` consistent.

- [Income-tax Act, 1961, section 2(42A)](https://incometaxindia.gov.in/pages/acts/income-tax-act.aspx)

### `black_money_s43_penalty_inr`

₹10,00,000, flat, per assessment year, for an omitted Schedule FA.

Confirm the figure in section 43 is still ₹10,00,000. Also confirm whether this assessment
year's Finance Act has changed the list of sub-sections of section 139 whose filing cures
the default — a revised return under section 139(5) is in that list and an updated return
under section 139(8A) is not, which is the point the whole prior-year workflow turns on.

- [Acts administered by the department, including the Black Money Act, 2015](https://incometaxindia.gov.in/Pages/acts/index.aspx)
- [CBDT, FAQs on Budget 2026](https://www.incometaxindia.gov.in/documents/20117/15766092/FAQs-Budget-2026.pdf)

### `black_money_relief_threshold_inr`

₹20,00,000 — the aggregate below which the section 43 penalty is disapplied.

**This one has already moved**, replacing an earlier ₹5,00,000 bank-balance carve-out with
effect from 1 October 2024, so treat it as live. Confirm the figure, and confirm immovable
property is still excluded from the relief. The Finance Act 2026 inserted matching provisos
into sections 49 and 50 (prosecution) without disturbing this one, so watch for further
movement. The proviso still fixes no valuation date for shares, which is why the threshold
report shows two bases rather than choosing one.

- [CBDT, FAQs on Budget 2026](https://www.incometaxindia.gov.in/documents/20117/15766092/FAQs-Budget-2026.pdf)
- [Acts administered by the department, including the Black Money Act, 2015](https://incometaxindia.gov.in/Pages/acts/index.aspx)

### `form_67_deadline`

End of the assessment year, conditional on the return being filed within the section
139(1) or 139(4) window; on or before the return itself where that return is under section
139(8A).

The date advances with the assessment year, so re-derive it.

**The Form 44 question is settled, and the answer is that this entry does not survive past
AY 2026-27.** Form No. 67 under rule 128 of the Income-tax Rules, 1962 is succeeded by
**Form No. 44 under rule 76 of the Income-tax Rules, 2026** (CBDT Notification No. 22/2026,
G.S.R. 198(E), 20 March 2026), in force from 1 April 2026 and applying to **tax year 2026-27
onwards** — income earned from 1 April 2026, which the old nomenclature called AY 2027-28.
AY 2026-27 is the last year on Form 67, because income of FY 2025-26 stays under the
Income-tax Act, 1961.

The deadline *structure* carries over unchanged — rule 76(12) gives twelve months from the
end of the tax year where the return is within the section 263(1) or 263(4) window, and
rule 76(13) repeats the updated-return proviso for a return under section 263(6)(a). What
changes is substantive, so a successor registry must **rename** this entry rather than
re-date it: rule 76(16) requires an accountant to verify Form 44 where the assessee is a
company or foreign tax paid for the tax year is ₹1,00,000 or more, the form asks for the
foreign TIN, and a new Form No. 45 intimates a later refund of foreign tax.

- [Income-tax Rules, 1962, rule 128](https://incometaxindia.gov.in/pages/rules/income-tax-rules-1962.aspx)
- [CBDT notifications index — Notification No. 100/2022 dated 18 August 2022](https://incometaxindia.gov.in/pages/communications/notifications.aspx)
- [CBDT Notification No. 22/2026, G.S.R. 198(E) — Income-tax Rules, 2026, rule 76 and Form No. 44](https://www.incometax.gov.in/iec/foportal/sites/default/files/2026-03/En-Notified-IT-Rules-2026-20-03-2026.pdf)

### `revised_return_deadline`

**Settled on 3 August 2026. The `contested` flag has been removed and the value corrected
from 31 December 2026 to 31 March 2027.**

A revised return under section 139(5) is the only self-help cure for a Schedule FA omission
in the current year, so its deadline matters more here than it looks. Our own research memos
disagreed: one read section 139(5) as three months before the end of the assessment year,
giving 31 December 2026; two read a Finance Act 2026 substitution as running to the end of
the assessment year, giving 31 March 2027. **The two were right.** Section 5(b) of the
Finance Act, 2026 substituted section 139(5), with effect from 1 March 2026, to read
"at any time before the end of the relevant assessment year or before the completion of the
assessment, whichever is earlier".

Two things to re-check for a later year:

1. The date is the end of the assessment year and moves with it, so re-derive rather than
   copy. Note the second limb too — completion of the assessment closes the window earlier.
2. Read **section 234-I** (inserted by section 16 of the same Finance Act) as it then stands.
   It charges ₹1,000 where total income does not exceed ₹5,00,000 and ₹5,000 otherwise on a
   revised return furnished after the nine-month point. As enacted it measures nine and
   twelve months from the end of the **assessment** year, whereas the Notes on Clauses say
   "previous year" and the Income-tax Act 2025 counterpart (section 428(b)) says tax year.
   Read literally, the fee window opens only after section 139(5) has already closed, so it
   can never be reached; expect a corrigendum, and budget for the fee anyway.

- [Finance Act, 2026 (No. 4 of 2026), sections 5(b) and 16](https://egazette.gov.in/WriteReadData/2026/271439.pdf)
- [Memorandum explaining the provisions of the Finance Bill, 2026](https://www.indiabudget.gov.in/doc/memo.pdf)
- [Finance Bill, 2026, Notes on Clauses — clauses 5 and 12](https://www.indiabudget.gov.in/doc/Finance_Bill.pdf)
- [Income-tax Act, 1961, section 139(5)](https://incometaxindia.gov.in/pages/acts/income-tax-act.aspx)

---

## The `stable` entries, and why they are not on the list

Listed so that a reviewer can see the judgement rather than having to infer it.

| Entry | Why stable |
|---|---|
| `schedule_fa_reporting_basis` | The calendar-year basis exists to line Schedule FA up with the CRS/FATCA reporting period. It is structural, not a Finance Act figure. |
| `schedule_fa_fx_convention` | The department's own guide fixes each amount to the TT buying rate on the date it relates to. Re-read only if the guide is reissued. |
| `income_fx_convention_rule_115` | Rule 115(2)'s specified date has been the last day of the preceding month throughout. |
| `equity_perquisite_cost_of_acquisition` | Sections 17(2)(vi) and 49(2AA) together, structural to how employer equity is taxed. |
| `transfer_expenditure_deductible` | Section 48. Unchanged in substance for decades. |
| `schedule_fa_disclosure_unconditional` | There is no de minimis for Schedule FA. Worth re-reading the instructions for any newly introduced threshold, but no figure to check. |

## Out of scope, deliberately

This registry covers **foreign asset disclosure and the schedules that depend on it**, and
nothing else. Slab rates, surcharge tiers, Chapter VI-A deductions, the section 112A
exemption limit and the 31 January 2018 grandfathering date under section 55(2)(ac) are
**not** here, because section 112A applies to STT-paid listed Indian equity and foreign
shares are never section 112A assets — so this tool has no occasion to assert any of them.
If a figure is not needed to produce Schedule FA or the Schedule CG, OS, FSI and TR
aggregates that hang off it, it does not belong in the registry.
