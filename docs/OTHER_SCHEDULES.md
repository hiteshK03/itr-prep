# Prior years, and the schedules beyond Schedule FA

*Part of [itr-prep](../README.md) — updated returns for AY 2024-25 / 2025-26, Schedule CG/OS/FSI/TR, Form 67 and Form 44.*

## Prior years: AY 2024-25 and AY 2025-26

`--year 2023` and `--year 2024` can feed an **updated return under s.139(8A)** for AY 2024-25
or AY 2025-26. This section documents the mechanics **if** one is being filed; it is not a
recommendation to file one, and three things should be settled before you reach for it:

- **Run the threshold report first.** Where a year's aggregate of non-immovable foreign assets
  is under ₹20,00,000 on every basis, the proviso to section 43 of the Black Money Act
  provides that "this section **shall not apply**" — a disapplication, not a discretion — so
  for that year there is no section 43 default and nothing for an updated return to cure.
- **An updated return does not displace a section 43 default in any event.** Section 43's
  charging limb names sub-sections (1), (4) and (5) of section 139; s.139(8A) is not among
  them. See [`docs/KNOWN-ISSUES.md`](KNOWN-ISSUES.md) issue 3. A **revised** return under
  s.139(5) is in that limb; an updated return substitutes for nothing.
- **An updated return needs positive additional tax.** A disclosure-only correction with no
  additional liability is not a filing this route supports.

So the reason to file one is the **income** left out of the original return, not the missing
schedule — and that reason has to be worth the additional tax under s.140B, whose rate rises
with each 12-month band. Take advice. This tool builds Schedule FA; it does not decide
whether a year should be filed.

All three years in the table below are decided under the Income-tax Act, 1961, so the
citations in this section are to that Act deliberately. Calendar year → assessment year:

| `--year` | Financial year | Assessment year | Utility |
|---|---|---|---|
| 2023 | FY 2023-24 | AY 2024-25 | `ITR2_AY_24-25_V1.8.xlsm` |
| 2024 | FY 2024-25 | AY 2025-26 | `ITR2_AY_25-26_V1.2.xlsm` |
| 2025 | FY 2025-26 | AY 2026-27 | `ITR2_AY_26-27_V1.2.xlsm` |

Use the utility **for that assessment year**, with **s.139(8A)** selected in
`Part A Gen_139(8A)`, and complete `Part B ATI`.

**The Schedule FA import path is identical across all three years — verified, not assumed.**
The VBA was decompiled from each utility and compared:

- `Function ImportScheduleFA(ByVal jsonObject As Object)` is **1,409 lines in all three and
  character-identical**, apart from the casing of one loop variable (`node` vs `Node`),
  which VBA treats as the same identifier.
- All three read the **same 63 JSON keys**, including every Table A2 and A3 field.
- All three write to VBA code-name `Sheet27`, which resolves to the sheet named **`TR_FA`**
  in all three workbooks.
- All three expose `Part A Gen_139(8A)` and `Part B ATI`.
- The `ScheduleFA` **JSON schema definitions are byte-identical** between the AY 2025-26 and
  AY 2026-27 schemas: same 12 required fields for `DtlsForeignEquityDebtInterest`, same 12
  for `DtlsForeignCustodialAcc`, same types and constraints, no `maxItems` on either.

**And all three have now been round-tripped live**, with `itr-prep import`, each into a fresh
copy of its own utility, each passing full cell-by-cell verification against its audit CSV —
see [Verification](VERIFICATION.md#the-excel-round-trip-live-on-all-three-utilities). The equivalence above
is no longer load-bearing; it is corroborated by measurement. Import a prior year with:

```bash
itr-prep import --year 2024 --json out/schedule_fa_2024.json \
              --utility /path/to/ITR2_AY_25-26_V1.2.xlsm
```

Two caveats remain worth stating:

- The **AY 2024-25 JSON schema** is no longer published at a retrievable URL, so `--year 2023`
  output is validated against the AY 2025-26 / AY 2026-27 schema. Given the A2/A3 definitions
  are unchanged between those two and the AY 2024-25 utility's importer reads the identical
  keys, this is a low risk — but it is inference from the importer rather than a check
  against that year's own schema. Validate inside the AY 2024-25 utility before filing.
- Utility **versions** matter: use the latest published for each AY (V1.8 for AY 2024-25,
  V1.2 for AY 2025-26). Earlier versions of the same year's utility were not compared.

---

## Schedule CG, OS, FSI, TR and the foreign tax credit statement

Schedule FA does not cover capital gains or dividend income. `..._other_schedules.txt`
gives you those figures, on the **financial year** (1 Apr – 31 Mar), not the calendar year:

- **Schedule CG** — aggregate full value of consideration and cost of acquisition, split
  into short term (held ≤ 24 months) and long term (> 24 months). Hundreds of trades
  collapse into these two blocks. Foreign shares are unlisted for Indian purposes, hence
  the 24-month threshold.
- **Schedule OS / FSI / TR and the foreign tax credit statement** — gross foreign dividend
  and US tax withheld, in both USD and INR. The paragraph that names the form and its
  deadline is rendered from the registry for the year being built, so it says Form 67 for
  AY 2026-27 and Form 44 for AY 2027-28 rather than asserting either.

These are **reported, not emitted into the JSON**, deliberately. Schedule CG's structure
depends on choices this tool has no business making — which section, indexation, set-off
against other losses — and a wrong auto-filled capital gains schedule is far more dangerous
than one you enter yourself. Enter them by hand or hand the file to your CA.

**For AY 2026-27 and earlier — a 1961-Act year, so 1961-Act citations throughout the rest
of this section.**

**Form 67 is due by the end of the assessment year, not by the return's due date.** Rule
128(9) of the Income-tax Rules, 1962 was substituted by **CBDT Notification No. 100/2022
dated 18 August 2022** (Income-tax (27th Amendment) Rules, 2022, G.S.R. 636(E)), with
retrospective effect from 1 April 2022. Form 67 is to be furnished **on or before the end of
the assessment year** in which the income is offered to tax — **31 March 2027 for
AY 2026-27** — provided the return itself is filed within the time allowed by s.139(1) or
s.139(4). The pre-2022 requirement to get it in by the s.139(1) due date no longer applies.

**The proviso runs the other way, and it is the one that bites on a prior year.** Where the
return is furnished under **s.139(8A)**, Form 67 for the income included in that updated
return must be furnished **on or before the date that return is furnished**. It cannot be
filed afterwards. So for each year in
[Prior years](#prior-years-ay-2024-25-and-ay-2025-26), the order is Form 67, then the ITR-U.

Being late is not necessarily fatal either. A consistent line of ITAT authority holds the
Rule 128(9) timeline **directory rather than mandatory** — the rule attaches no consequence
to non-adherence, and a procedural lapse cannot extinguish a substantive right to credit:
*Ms. Brinda Rama Krishna v. ITO* (ITAT Bangalore, ITA No. 454/Bang/2021, 17 November 2021;
[2021] 135 taxmann.com 358), followed in *42 Hertz Software India Pvt. Ltd. v. ACIT* ([2022]
139 taxmann.com 448) and *Sonakshi Sinha v. CIT(A)* ([2022] 142 taxmann.com 414 (Mum)). That
is a fallback for a credit already claimed, not a filing plan.

**AY 2026-27 is the last year on Form 67.** From tax year 2026-27 — income earned from
1 April 2026, governed by the Income-tax Act, 2025 — the claim moves to **Form No. 44 under
rule 76 of the Income-tax Rules, 2026** (CBDT Notification No. 22/2026, G.S.R. 198(E),
20 March 2026). Both limbs of the deadline survive: rule 76(12) gives twelve months from
the end of the tax year where the return is within the section 263(1) or 263(4) window, and
rule 76(13) repeats the updated-return proviso for a return under section 263(6)(a). What
changed in substance is that rule 76(16) requires an accountant to verify Form 44 where the
assessee is a company or foreign tax paid for the tax year is ₹1,00,000 or more, the form
asks for the foreign tax identification number, and a new Form No. 45 intimates the
**settlement of a dispute** over foreign tax whose credit was not claimed (rule 76(6) and
(15)). A later *refund* of foreign tax already credited is not Form 45 — rule 76(14) puts
that back on Form No. 44, in its Part C. The ITAT authority above is on rule 128(9) and
does not automatically carry to rule 76; treat the deadline as real.
