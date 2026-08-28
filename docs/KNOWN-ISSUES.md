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

**Decided, 25 August 2026** (with the mutual fund pipeline, the first Schedule 112A emitter).
None of the four options above was taken. The defect is not in the constraint and not in the
values: `multipleOf: 0.0001` says "four decimal places", and a four-decimal value is a
multiple of 0.0001 in the only arithmetic that matters — decimal arithmetic. The defect is
that the validator implements the check as `int(x / 0.0001) != x / 0.0001` in binary floats,
where `0.0001` is not representable and the quotient is not exact. So the fix is to correct
the validator, not the document:

`itrprep/validate.py` extends the validator class the schema itself asks for with one
override — `multipleOf` evaluated exactly on the value's shortest round-trip decimal
representation (`Decimal(repr(x))`), which is the literal the serialised JSON carries and
therefore the figure the department receives. Consequences, each checked by
`tests/test_validation_teeth.py`:

- Every legal four-decimal value passes (the 27.9% false-failure rate is gone).
- A genuinely over-precise value — five decimals, or float noise such as `0.1 + 0.2` —
  still fails.
- The department's schema file is loaded byte-for-byte and never edited, so nothing here
  validates against a local invention.

What this deliberately does *not* do is round or rewrite a user's figures: the emitter must
produce four-decimal values (unit counts and 2018 NAVs are), and validation confirms that
rather than repairing it. If a value cannot be expressed in four decimals the build fails
with the schema error, loudly, which is the behaviour every other part of the pipeline has.

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
section 8 — [India Code](https://indiacode.gov.in/handle/123456789/588172). CBDT,
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

**Clear.** It is an *aggregate* test, not a per-asset test — "an asset or assets … the
aggregate value of such asset or assets". It is a disapplication, not a discretion: "this
section shall not apply", so where the aggregate is under the line the Assessing Officer has
nothing to exercise judgement about. And it operates per year, because section 43 itself
attaches to a return furnished "for any previous year".

> This paragraph read "an aggregate test across the **undisclosed** non-immovable assets"
> until 5 August 2026. That is still the better view, but it was asserted here as clear when
> it is not: *which* assets fall inside the aggregate is a separate question from whether the
> test is aggregate at all, and it is open. **See issue 5.**

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

---

## 5. Which assets the ₹20,00,000 proviso aggregates over is unsettled

**Status:** open. **Better view held at about 80% confidence, and no authority either way** —
no court, no tribunal, no circular, no FAQ has decided it. Recorded against
`black_money_relief_threshold_inr` alongside issue 4, which is the valuation-date half of the
same sentence.
**Bites when:** a threshold report is read as *the* proviso figure for a year in which
Schedule FA was **partly** completed. It is harmless where Schedule FA was blank or absent,
which is why it can go unnoticed for a long time.

The proviso disapplies section 43 "in respect of an asset or assets (other than immovable
property), where the aggregate value of **such asset or assets** does not exceed twenty lakh
rupees". Issue 4 records that this is an aggregate test and that its valuation date is
missing. This entry is about a different gap: **"such asset or assets" needs a referent, and
the proviso does not supply one.** Two readings are available.

- **Narrow.** "Such" points back to the assets in respect of which section 43 applies — the
  ones the charging limb identified, that is, **the undisclosed ones**. Aggregate those.
- **Broad.** "Such" points at the taxpayer's whole non-immovable foreign portfolio for the
  year, disclosed and undisclosed together.

**The narrow reading is the better one, on three legs.**

1. **The charging limb identifies defaults asset by asset.** Section 43 penalises a person who
   "fails to furnish any information … relating to *any asset* … or relating to any income
   from a source located outside India". The default is constituted by the particular asset or
   income not disclosed. A proviso that disapplies "this section … in respect of an asset or
   assets" is disapplying it in respect of the same things the section fastened on. On the
   broad reading, "such" reaches assets the section never mentioned.
2. **The stated mischief is the omitted asset's own value.** The Memorandum to the Finance
   (No. 2) Bill, 2024 explains the amendment as addressing cases where the penalty was
   disproportionate to the value of the asset that went undisclosed. That framing measures
   proportionality against the omission, not against everything the taxpayer holds.
3. **Section 42 is the objection, and it runs the other way.** The same amendment inserted the
   identical proviso into section 42, whose charging limb catches a person who "at any time
   during such previous year … held any asset … located outside India" — so under section 42
   *every* asset held is one in respect of which the section applies, and the proviso there
   does sweep the whole portfolio. **One form of words, applied faithfully to two different
   charging limbs, yields the whole portfolio under section 42 and the undisclosed subset
   under section 43.** That is why Parliament could reuse it. The broad reading has to make
   the words mean "whole portfolio" in both places — correct under section 42 only by
   accident, and requiring under section 43 a referent that section never supplies.

**Why the confidence is 80% and not higher.** The point is unlitigated. The reported section
43 material after the amendment goes to whether the penalty is mandatory, not to aggregation
scope. Practitioner commentary that touches the question tends to state the broad reading
without arguing it, which is weak authority but is what a reader will find first. And an
Assessing Officer has an administratively easier job under the broad reading, which is not a
legal argument but does predict what may be asserted.

**What this means for the report this package produces.** `itrprep/threshold.py` aggregates
**every** non-immovable holding in the ledger for the year. That is the broad reading, and it
is the right default for a tool: it is conservative, it needs no view about what a particular
return did or did not disclose, and it cannot be wrong in the taxpayer's favour. **But the
number it prints is not necessarily the number the proviso tests.** Where a year's Schedule FA
was partly completed, the figure that matters on the better view is lower — possibly much
lower — and the tool has no way to know which holdings were disclosed. **So:**

- Treat an OVER verdict for a partly-disclosed year as **"OVER on the broad reading"**, and
  as a prompt to compute the undisclosed subset by hand, not as an answer.
- An UNDER verdict is safe on both readings. The broad aggregate is a ceiling on the narrow
  one, so if the whole portfolio is under the line, the undisclosed subset is too.
- Where Schedule FA was blank or no return was furnished, the two readings coincide and the
  distinction does not arise.

**Sources.** Black Money Act, 2015, sections 42 and 43 as amended, and the proviso substituted
by **section 164 of Act 15 of 2024** — as at issue 4. *Memorandum Explaining the Provisions in
the Finance (No. 2) Bill, 2024*, under "Amendments in section 42 and 43 of the Black Money
Act, 2015" — [indiabudget.gov.in](https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf).
The searches that came back empty are part of the finding and were: the proviso's operative
words against reported decisions and CBDT material, and section 43 aggregation scope generally.
**Absence of authority is recorded as a result here, not as an incomplete search.**

---

## 6. An Indian security with no ISIN and no currency is not caught

**Status:** open, and open by construction rather than by omission. The guard that catches the
detectable cases is in `itrprep/scope.py` and is enforced by `doctor`, `build`, `threshold` and
`run`.
**Bites when:** somebody hand-enters an Indian mutual fund or Indian equity as a bare ticker —
no `isin`, no `currency`, no `.NS` or `.BO` suffix, and an issuer row that does not say `INDIA`.

Until this pass, an Indian mutual fund in `transactions.csv` was disclosed in Schedule FA as
though it were a foreign equity in a foreign custodial account: no error, no warning, a
complete return asserting a foreign asset the filer does not hold. That is now refused, on
four structural signals — an ISIN whose ISO-3166 country prefix is `IN`, an INR-denominated
row, an NSE or BSE venue suffix on the ticker, and an issuer whose country is `INDIA`.

**What it cannot reach.** All four signals depend on data the tool does not itself produce.
`isin` and `currency` are optional, hand-entered columns; no adapter writes either, because no
supported broker export carries an ISIN. The venue suffix depends on the user having typed the
ticker the way a market-data source would. So a row with none of them is invisible to the
guard, and the pipeline will value and disclose it exactly as before.

**Why it is not closed by matching scheme names.** That was considered and rejected. "Fund",
"Growth", "Direct Plan" and "IDCW" all appear in the names of legitimate foreign holdings —
`IVV` is an iShares ETF and is in this repository's own fixtures — so a name-based rule would
refuse holdings that genuinely belong in Schedule FA. A guard that breaks the correct case to
catch more of the incorrect one is a worse guard.

**What would actually close it** is asking, rather than inferring: a required per-ticker
declaration of where the security is domiciled, refused if absent, in the way `--split-basis`
is demanded rather than guessed. That is a change to the input contract and to every existing
working directory, so it is recorded here rather than done incidentally.

The refusal states this limit in its own output, so the person being refused is told what the
check did not look at. Somebody who is *not* refused is told nothing, which is the residual
risk and cannot be fixed from inside the guard.

---

## 7. `schedule_fa_reporting_period` is never checked against the year you pass

**Status:** open. Present in both registries, tagged `not_read`, and read by nothing.
**Bites when:** the registry's reporting period and the tool's own idea of the reporting period
diverge — that is, if a future Finance Act moves Schedule FA off the calendar year, or if a
registry entry is edited in the belief that the code will follow it.

`rules/AY2026-27.json` and `rules/AY2027-28.json` both carry a
`schedule_fa_reporting_period` entry stating that Schedule FA reports the calendar year, cited
to the department's instructions. Nothing reads it. The calendar-year window is derived
independently in `itrprep/positions.py` from the `--year` the user passes, and the two are
never compared. If they ever disagreed, the registry would be documenting one period while the
arithmetic computed another, and no check anywhere would notice.

The cross-check is cheap — assert the derived window against the registry entry at the point
`--year` is resolved, and refuse if they differ — but it is a behavioural change to the build
path and was deliberately left out of the pass that added the `code_status` labelling, whose
scope was to make inert entries visible rather than to wire them up. The same applies to
`revised_return_deadline`, which is also `not_read`, but which nothing computes from and which
would only ever be printed.

`tests/test_rules_registry.py` will fail if either entry's tag stops matching what the code
references, so wiring one up without retagging it is caught.
