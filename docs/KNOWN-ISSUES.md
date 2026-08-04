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

**Status:** open and **material**, but **narrowed on 4 August 2026** — one half of it is now
settled, and settled against the taxpayer. Recorded in the registry against
`black_money_s43_penalty_inr`.
**Bites when:** relying on a return to cure an omitted Schedule FA for tax year 2026-27 or
later.

Read the operative words, because the structure matters more than the summary. Section 43 of
the Black Money (Undisclosed Foreign Income and Assets) and Imposition of Tax Act, 2015
applies to a person

> who has furnished the return of income for any previous year under sub-section (1) or
> sub-section (4) or sub-section (5) of section 139 of the said Act, [and] fails to furnish
> any information or furnishes inaccurate particulars in such return relating to any asset
> … located outside India

The reference to section 139 is in the **charging limb**, not in a separate list of curing
filings. The section identifies *which return the omission is judged in*. Nothing "cures" a
section 43 default; rather, if the return furnished under section 139(1), (4) or (5) does
disclose the asset, no default arises in the first place. That is why a revised return works
— it substitutes for the original and becomes the return furnished under section 139(5).

The 1961 Act was repealed by section 536(1) of the Income-tax Act, 2025 with effect from
1 April 2026. A return for tax year 2026-27 is furnished under **section 263 of the Act of
2025**, not section 139 of the 1961 Act.

### The half that is settled: an updated return was never in the charging limb

Section 43 names sub-sections (1), (4) and (5). **Section 139(8A) is not among them**, so its
successor section 263(6)(a) has no reference to be construed onto. Section 8(1) of the
General Clauses Act, 1897 construes a reference to a repealed provision as a reference to
the provision re-enacted in its place; it cannot supply a reference that was never made.
Renumbering therefore changes nothing here: **an updated return did not displace a section 43
default before 1 April 2026 and does not displace one after.** Filing one leaves the return
furnished under section 139(1) still lacking the disclosure, which is the thing section 43
penalises.

This is worth stating flatly because the transition invites the opposite mistake — reading
the renumbering as an opportunity to revisit a question that was actually closed all along.

### The half that is open: whether section 263(1), (4) and (5) read onto the charging limb

Probably yes, on section 8(1), which maps each of section 139(1), (4) and (5) onto the
corresponding re-enacted provision in section 263. What stops that being more than "probably"
is that **nothing makes it explicit**, and the search for an instrument that does was
exhaustive rather than cursory:

- The Act of 2025 has sixteen schedules and **none of them amends another enactment**. There
  is no consequential-amendment schedule, which is where a fix would normally sit. The Black
  Money Act appears in the Act of 2025 only as a *bar* — section 263(9)(d) lists it among the
  "specified laws" whose proceedings block an updated return — never as something amended.
- The Finance Act, 2026 does amend the Black Money Act — Part III, section 160 — but only to
  insert ₹20,00,000 provisos into sections 49 and 50, both backdated to 1 October 2024.
  **It does not touch section 43.** Parliament had the Black Money Act open on the table and
  did not take the opportunity.
- **Section 536 of the Act of 2025 carries no bridge for other enactments.** Sub-section (3)
  construes tax-year references "in this Act" only. Sub-section (4) expressly applies
  **section 6** of the General Clauses Act — effect of repeal — and says nothing about
  **section 8**, which is the section that would do this work. Section 8 applies of its own
  force and does not need to be invoked, so this is not fatal; it does mean the drafter left
  no signal either way.
- Section 8(1)'s escape hatch — "unless a different intention appears" — has something to
  bite on. **Section 2(6) of the Black Money Act defines "Income-tax Act" as "the Income-tax
  Act, 1961 (43 of 1961)"**, by name and number, and section 8(1) is drafted about references
  to a *provision*. An argument that the definition fixes the reference to a repealed statute
  is available to anyone who wants to make it.
- Section 536(2)(c) preserves the old Act for earlier tax years, which resolves nothing for
  2026-27 onward.

The exposure is also wider than section 43. The Black Money Act is drafted onto the 1961 Act
throughout: section 2(2) defines "assessee" by reference to section 6 and clause (6) of
section 6 of "the Income-tax Act, 1961 (43 of 1961)" — that inline Act number was put there
as recently as the Finance (No. 2) Act, 2019 — and section 2(10) defines "resident" the same
way. Whatever construction resolves section 43 resolves those too, and the same construction
is what makes the Act work at all from 1 April 2026. Its own year vocabulary is safe:
sections 2(4) and 2(9) define "assessment year" and "previous year" inside the Act and do not
borrow them.

**Take advice before relying on a return to cure a Schedule FA omission for a 2025-Act
year, and re-check each Finance Act for a consequential amendment to section 43** — that is
where the fix belongs and where it will appear if it is ever made.

For AY 2026-27 and earlier the position is unchanged and the existing analysis holds: a
revised return under section 139(5) is in the charging limb and an updated return under
section 139(8A) is not. That the 1961 Act governs those years is not an inference. CBDT says
so: *FAQs on Interplay and Transition*, Q3.9 — "The old Act continues to govern all proceedings
relating to tax years before 1st April, 2026" — and Q3.10, which confirms an updated return
for AY 2025-26 or earlier is filed "subject to the time limits prescribed under Section
139(8A) of the old Act".

**Sources.** Income-tax Act, 2025 (No. 30 of 2025), sections 263 and 536 —
[Gazette](https://egazette.gov.in/WriteReadData/2025/265620.pdf). Finance Act, 2026 (No. 4 of
2026), Part III section 160 —
[Gazette](https://egazette.gov.in/WriteReadData/2026/271439.pdf). General Clauses Act, 1897,
section 8 — [India Code](https://www.indiacode.nic.in/handle/123456789/2328). CBDT,
[*FAQs on Interplay and Transition from the Income Tax Act, 1961 to the Income Tax Act, 2025*](https://www.incometaxindia.gov.in/documents/81799/11848482/FAQs-on-Interplay-and-Transition.pdf).

---

## 4. The ₹20,00,000 section 43 proviso fixes no valuation date

**Status:** open, and open because Parliament left it open — not because the research is
incomplete. Recorded in the registry against `black_money_relief_threshold_inr`.
**Bites when:** the threshold report declares a year OVER or UNDER. `itrprep/threshold.py`
already shows both bases and warns when they disagree; this entry says why it has to.

The proviso to section 43, inserted by the Finance (No. 2) Act, 2024 with effect from
1 October 2024, reads in full:

> Provided that this section shall not apply in respect of an asset or assets (other than
> immovable property), where the aggregate value of such asset or assets does not exceed
> twenty lakh rupees.

Three things are clear from those words and one is missing.

**Clear.** It is an *aggregate* test across the undisclosed non-immovable assets, not a
per-asset test — "an asset or assets … the aggregate value of such asset or assets". It is a
disapplication, not a discretion: "this section shall not apply", so where the aggregate is
under the line the Assessing Officer has nothing to exercise judgement about. And it operates
per year, because section 43 itself attaches to a return furnished "for any previous year".

**Missing: the date, and the basis.** The proviso says "value" without saying *when*, and
without saying cost or market. The Explanation to section 43 does not fill the gap — it
imports the Explanation to section 42, which supplies only a *currency conversion* rule, and
even that is written for one asset class:

> For determining the value equivalent in rupees of **the balance in an account maintained in
> foreign currency**, the rate of exchange … shall be the telegraphic transfer buying rate of
> such currency **as on the date for which the value is to be determined** …

"The date for which the value is to be determined" presupposes some other provision fixing
that date. For a bank balance, section 3 read with the valuation rules does. For listed
shares there is nothing in section 43, and Parliament widened the proviso to all non-immovable
assets in 2024 without extending the valuation machinery to match.

So the rupee *conversion* is settled — SBI telegraphic transfer buying rate on whatever the
valuation date turns out to be — and the valuation date and basis are not. A holding can be
under ₹20,00,000 at cost, under it at 31 December, and over it at its peak during the year,
and the statute does not choose. Do not let a report, a memo or a conversation quietly pick
one and present the answer as settled.

**Sources.** Black Money Act, 2015, sections 42 and 43 as amended —
[incometaxindia.gov.in](https://incometaxindia.gov.in/Pages/acts/index.aspx). The proviso was
substituted by **section 164 of Act 15 of 2024**, the Finance (No. 2) Act, 2024, with effect
from 1 October 2024, per the amendment footnote to section 43 in the as-amended text; the
same section substituted the proviso to section 42.
