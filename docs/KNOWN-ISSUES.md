# Known issues

Things established, not solved. Each one is here because forgetting it costs more than
recording it, and because the honest position is that it is open.

An issue leaves this file when it is settled against a primary source, or when the code that
would trip over it is written and the fix goes in with it. Not before.

---

## 1. Schedule 112A's JSON schema rejects legal four-decimal values

**Status:** open. Nothing in the repository hits it yet.
**Bites when:** anyone emits Schedule 112A JSON — the natural next step if the mutual fund
registry entries ever become a pipeline.

The ITD's ITR-2 JSON schema puts `"multipleOf": 0.0001` on five per-unit fields of
Schedule 112A:

- `NumSharesUnits`
- `SalePricePerShareUnit`
- `AcquisitionCost`
- `FairMktValuePerShareunit`
- `ExpExclCnctTransfer`

Read as intended, that permits any value to four decimal places, which is what a mutual fund
unit count and a 31 January 2018 NAV both need. Read as the validator implements it, it does
not, because `multipleOf` is evaluated in binary floating point and most four-decimal
decimals are not exactly representable.

Measured against this repository's own `jsonschema` (4.26.0):

- `12.34` **fails**.
- `99.9999` **fails**.
- **27.9%** of randomly generated legal four-decimal values fail.
- Passing a `Decimal` instead of a `float` does not avoid it — the validator raises
  `TypeError` inside `multipleOf` handling rather than returning a validation error.

Schedule FA has no such constraint anywhere, which is why the tool has never met this. The
existing emitter writes integers into Schedule FA and validates cleanly.

**Why this is not fixed here.** Every available response is a decision with consequences
beyond one function, and none of them should be made incidentally by whoever first writes a
Schedule 112A row:

- Rounding each value to a multiple that survives the float check changes figures the user
  will reconcile against a registrar's statement.
- Stripping `multipleOf` from a local copy of the schema means validating against something
  that is not the department's artefact, which defeats the point of validating.
- Serialising through a string and validating the string sidesteps `multipleOf` but changes
  the document's types.
- Filing the values and accepting that the offline utility may reject them is a choice too,
  and possibly the right one, since the utility's own VBA validation is not this schema.

Decide it deliberately, in daylight, before Schedule 112A JSON is emitted.

---

## 2. Whether the Finance Act, 2026 amended the Specified Mutual Fund definition

**Status:** open and **material**. Recorded in the registry as
`specified_mf_debt_threshold_pct`, flagged `contested`.
**Bites when:** classifying a mutual fund unit — it decides whether a gain is taxed at the
section 196/198 rates or at slab rates.

Section 76(5)(b) of the Income-tax Act, 2025, as it appears in the Gazette text, defines a
Specified Mutual Fund as one that

> invests more than 65% of its total proceeds in debt and money market instruments or a fund
> which invests 65% or more of its total proceeds in units of such a fund

Two things could not be established against a primary source.

**The 90-day carve-out.** Secondary commentary — practitioner newsletters, not cited here
because they are not authority — describes the 65% test as being measured on an averaging or
liquidity-buffer basis over 90 days. **No such words appear anywhere in the Gazette text of
section 76.** Either the commentary is describing an amendment, or it is describing SEBI
categorisation machinery and attributing it to the Act, or it is simply wrong. Which one
matters: a fund sitting near the line classifies differently under each reading.

**Why it could not be closed.** Part B of Chapter III of the Finance Act, 2026 (No. 4 of
2026, 30 March 2026) was read in full from the Gazette, and it does not amend section 76.
That is good evidence but not conclusive, because an amendment could reach section 76 through
a schedule, a consequential amendment, or a later notification. The obvious way to check —
the department's consolidated "Income-tax Act, 2025 as amended by the Finance Act, 2026" PDF
— **returns HTTP 403 to every automated client**, so it could not be diffed against the
enacted text.

**Why it is dangerous rather than merely unknown.** The 1961-Act predecessor, section 50AA,
was drafted with the opposite polarity: *not more than 35% in domestic equity*. Section
76(5)(b) is *more than 65% in debt and money market instruments*. These are not complements
of one another, and any implementation ported from 1961-Act logic will have the test the
wrong way round. A misclassification produces a complete, plausible, wrongly-rated answer —
there is nothing for a test to catch unless the test knows the right classification already.

**What would settle it:** the enacted Finance Act, 2026 text read against a consolidated
Act of 2025 from a source that serves automated clients, or a CBDT circular, or the notified
ITR form's own instructions for tax year 2026-27. Until then the entry stays `contested` and
must not be relied on. Do not clear the flag on the strength of commentary.

---

## 3. Whether a section 263 return cures a Black Money Act section 43 default

**Status:** open and **material**. Recorded in the registry against
`black_money_s43_penalty_inr`.
**Bites when:** relying on a return to cure an omitted Schedule FA for tax year 2026-27 or
later.

Section 43 of the Black Money (Undisclosed Foreign Income and Assets) and Imposition of Tax
Act, 2015 penalises a failure to disclose a foreign asset, and disapplies the penalty where
the asset is disclosed in a return furnished under listed sub-sections of **section 139 of
the Income-tax Act, 1961**.

That Act was repealed by section 536(1) of the Income-tax Act, 2025 with effect from
1 April 2026. A return for tax year 2026-27 is furnished under **section 263 of the Act of
2025**, not section 139 of the 1961 Act. Whether section 263 reads onto section 43's list is
not answered by anything primary that could be found:

- The Black Money Act is separate legislation and the Act of 2025 does not amend it. Section
  43 is still section 43 and its figures are unchanged.
- The Finance Act, 2026 does amend the Black Money Act — Part III, section 160 — but only to
  insert ₹20,00,000 provisos into sections 49 and 50. **It does not touch section 43.**
- Section 536(2)(c) preserves the old Act for earlier tax years, which resolves nothing for
  2026-27 onward.
- A general-clauses reading, under which a reference to a repealed enactment is construed as
  a reference to its re-enactment, is the likely answer. "Likely" is not a basis for relying
  on a cure against a ₹10,00,000-per-year penalty.

**Take advice before relying on a return to cure a Schedule FA omission for a 2025-Act
year.** For AY 2026-27 and earlier the position is unchanged and the existing analysis
holds: a revised return under section 139(5) is on the list and an updated return under
section 139(8A) is not.
