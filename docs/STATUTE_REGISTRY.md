# Where every statutory figure comes from

*Part of [itr-prep](../README.md) — the cited rules registry and the AY 2027-28 change of statute.*

Every rate, limit, threshold, deadline and conversion convention this tool relies on lives
in `rules/AY<year>.json`, each with an official citation. No figure the arithmetic depends on
is computed from memory — because the figures that matter here have already moved: the Black
Money Act relief threshold replaced an earlier ₹5 lakh bank-balance carve-out in 2024, the
foreign tax credit deadline was rewritten in 2022, and then the whole Act was replaced.

| Registry | Tax year | Statute | Entries |
|---|---|---|---|
| [`rules/AY2026-27.json`](../rules/AY2026-27.json) | FY 2025-26 | Income-tax Act, **1961** | 12, of which 6 `annual` |
| [`rules/AY2027-28.json`](../rules/AY2027-28.json) | FY 2026-27 | Income-tax Act, **2025** | 28, of which 13 `annual` |

```bash
itr-prep rules                # every entry, its value, its authority and its source
itr-prep rules --annual-only  # just the ones that need re-verifying each year
```

Each entry declares a **review class**. `stable` means fixed by statute — a settled
convention or a historical date. `annual` means a Finance Act or a notification can move
it, and it must be re-verified before the registry is used for a later assessment year.

### The registry is not a feature list

Every entry also declares a **`code_status`**, and `itr-prep rules` groups its output by it.
Ten of twenty-eight entries in the AY 2027-28 registry are figures the arithmetic reads;
the other eighteen are cited law that nothing in this tool acts on. That distinction was
invisible until the `code_status` field existed — every entry printed identically, with the
same citations and the same re-check instruction — and its absence is what led the author of
this tool to believe the mutual-fund support was implemented before it was. Since 25 August
2026 the mutual-fund entries the engine reads are `read_by_code`, and the distinction is
enforced rather than asserted.

| `code_status` | Entries per registry | What it means |
|---|---|---|
| `read_by_code` | 4 (AY 2026-27), 10 (AY 2027-28) | The arithmetic reads this value out of the registry. `black_money_relief_threshold_inr` and `black_money_s43_penalty_inr` by `threshold`, `foreign_share_long_term_holding` by `positions` and `cli`, the foreign tax credit deadline by `emit`, and — since the mutual fund pipeline — the grandfathering dates, holding periods, lot method, bonus cost and the indexation refusal read by `capgain` |
| `hardcoded_at_call_site` | 6 | Describes what the code really does, but the code does not read it. Changing the entry changes nothing |
| `not_read` | 2 | Nothing reads it and nothing acts on it. A recorded gap: `revised_return_deadline`, and `schedule_fa_reporting_period`, which is never cross-checked against the `--year` you pass |
| `research_only` | 10 (AY 2027-28 only) | Cited law with no code behind it yet: the rates and exemption (ss.196–198), the equity-oriented thresholds, and the contested Specified Mutual Fund definition |

`tests/test_rules_registry.py` greps `itrprep/` for every key and fails if a `read_by_code`
entry is not referenced there, or if an entry in any other class is. The classification would
rot within a release otherwise, and a registry that overstates what the tool does is the
specific failure this whole labelling exists to prevent.

### AY 2027-28 is a change of statute, not a refresh

The **Income-tax Act, 2025** came into force on 1 April 2026 and repealed the Income-tax
Act, 1961 by its section 536(1). Almost every provision was renumbered — but **section
536(2)(c) keeps the old Act applying to any tax year beginning before that date**, so
AY 2026-27, the year this tool was actually used to file, is permanently a 1961-Act year.

Both things have to stay true in this repository at once, which is why the section numbers
here are not consistent and should not be made so. Content about the AY 2026-27 filing keeps
its 1961-Act citations — [`docs/RUNBOOK_AY2026-27.md`](RUNBOOK_AY2026-27.md) and the
dated `CHANGELOG.md` entries are 1961-Act throughout — and forward-looking content cites the
Act of 2025, usually with the old number alongside. Every entry in `rules/AY2027-28.json`
carries an `act_transition` block naming the provision it descends from and classifying the
change as a renumbering, a substantive change, separate legislation or a new entry;
[`docs/ANNUAL-REVIEW.md`](ANNUAL-REVIEW.md) has the readable mapping table.

Three things worth knowing without reading that table:

- **The Black Money Act, 2015 is separate legislation and is not renumbered.** Section 43,
  the ₹10,00,000 penalty and the ₹20,00,000 relief threshold are untouched. There is a live
  cross-reference problem, though: section 43's charging limb names sub-sections (1), (4) and
  (5) of section 139 of the *1961* Act, and a tax year 2026-27 return is furnished under
  section 263 of the Act of 2025. Whether those read onto section 263 is unresolved. What is
  settled is the other half — section 139(8A) was never in that limb, so an updated return
  never displaced a section 43 default and renumbering does not change that. See
  [`docs/KNOWN-ISSUES.md`](KNOWN-ISSUES.md).
- **Two entries changed in substance, not just number.** The foreign tax credit statement
  became Form No. 44 under rule 76 of the Income-tax Rules, 2026, with an accountant's
  verification above ₹1,00,000 of foreign tax; and the revised-return deadline became twelve
  months from the end of the tax year under section 263(5).
- **The registry gained Indian mutual fund entries**, cited from the Gazette text:
  grandfathering (s.90(7)–(8)), Specified Mutual Funds (s.76), both capital gains rates
  (ss.196–198), holding periods (s.2(101)) and FIFO (s.67(7)(c)). Added as `research_only`;
  six of them — the dates, periods, lot method, bonus cost and indexation figures — were
  flipped to `read_by_code` on 25 August 2026 when `itrprep/capgain.py` started reading
  them, and `tests/test_rules_registry.py` now pins exactly that split. The rest stay
  `research_only`, and `itr-prep rules` prints them under a heading that says so.
  Two carry `implementation_trap` blocks that the test suite refuses to let anyone delete —
  AMFI's 31 January 2018 file has both a *Net Asset Value* and a *Repurchase Price* column
  and they differ on 4,756 of its 9,502 rows, and section 76 makes a Specified Mutual Fund
  unit acquired on or after 1 April 2023 short-term *irrespective of the holding period*.

That is enforced, not merely documented, because a note in a file gets skipped:

- **`itr-prep build` refuses to run** for an assessment year the registry does not cover. It
  does not quietly fall back to the newest one. Computing AY 2027-28 against AY 2026-27
  figures is exactly the silent failure this prevents.
- Building an **earlier** year runs — prior-year updated returns (s.139(8A) of the 1961 Act,
  s.263(6)(a) of the Act of 2025) are a documented workflow — but prints a banner saying
  which assessment year the figures it used are stated for, and which Act that year is
  decided under.
- **`tests/test_rules_registry.py` fails** if any entry lacks an official source URL, if
  any entry cites a secondary aggregator as its authority, if an `annual` entry has been
  left behind by the registry it lives in, if an `annual` entry is missing from
  [`docs/ANNUAL-REVIEW.md`](ANNUAL-REVIEW.md), or if an entry's `code_status` no longer
  matches what `itrprep/` references. It also asserts the arithmetic reads the registry rather
  than a reintroduced literal.

The suite fails while the runtime only warns, deliberately. A contributor or a CI run
should be stopped dead by a registry that has rotted. Someone mid-filing should not be:
Schedule FA is arithmetic on their own broker data and does not depend on a rate, so they
get a banner they cannot miss instead of a blocked deadline. The one place a stale figure
would change an answer — the ₹20 lakh threshold report — prints which registry and
verification date it used at the top of every report.

**Primary sources only.** The Act or Finance Act text, a CBDT notification or circular, or
the department's own site. ClearTax, TaxGuru, Taxmann and practitioner blogs are fine for
*finding* a provision and may be quoted in prose, but are never the cited authority for a
rate, a limit or a date; the test enforces the domain rule. `revised_return_deadline` was
flagged `contested` while our own research disagreed about it, rather than picking a date
and looking confident; it has since been settled against the enacted Finance Act 2026 text
and the flag removed. **One entry is `contested` now** —
`specified_mf_debt_threshold_pct`, where secondary commentary describes a 90-day carve-out
that is not in the Gazette text and the department's consolidated as-amended PDF returns 403
to every automated client, so the question could not be closed either way.

Scope is deliberately narrow: the registry holds what Schedule FA and its dependent
schedules need, plus Indian mutual fund capital gains. Slab rates, surcharge tiers and
Chapter VI-A deductions are not here. The 31 January 2018 grandfathering date used to be out
of scope too, correctly — foreign shares are never section 112A assets — but its Act-of-2025
successor at section 90(7)–(8) governs mutual fund units, so it is now in.
