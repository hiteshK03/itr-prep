# Working with a model on a real filing

The rule is in [`AGENTS.md`](../AGENTS.md): **a model may locate and transcribe a figure; it
may never subtract, total or reconcile one.** This page is the reasoning behind it, the
evidence, and the parts of the work where a model is genuinely useful.

None of it is about which model to run. That question rots in weeks and is not a property of
this repository — see [What is deliberately not here](#what-is-deliberately-not-here).

## The tiers

The useful frame is not "local or cloud". It is which tier of the work a piece of data
belongs to, because the tiers differ in what they expose and in what capability they need.

| Tier | The work | Where it runs |
|---|---|---|
| 0 | Every arithmetic operation on real financial data: parsing, lot construction, FIFO and same-day matching, FX conversion, peak values, split restatement, JSON emission, schema validation, cell-by-cell readback | Deterministic Python. **No model, local or cloud.** |
| 1 | Writing and debugging that Python; statutory research; schema work; interpreting a portal error code; drafting a briefing for your CA | Any model you like — on synthetic fixtures and an abstracted fact pattern, never on your own figures |
| 2 | The residue where real data genuinely must be in a context window: reading a broker PDF with no clean export, transcribing figures into a document you are writing | A local model, on a machine you own |
| 3 | The final figures, the disclosure position, whether to file an updated return | A person, and a chartered accountant |

Two things fall out of that table, and both cut against the instinct that sends people
looking for a local model in the first place.

**Almost all of the personal data is in tier 0, where there is no model at all.** A filing is
overwhelmingly arithmetic on a transaction history, and this tool does that arithmetic in
code, offline, reproducibly, with an audit CSV showing its working.

**Almost all of the model-hours are in tier 1, where there is nothing personal to protect.**
Writing an adapter, reading the department's schema, working out what a validation rule
means: none of it needs your holdings, and this repository is built so that none of it gets
them.

Tier 2 is the only place the two overlap. It is deliberately small, and the discipline in the
next section is what keeps it that way.

## The evidence for the rule

Two results, pointing the same way.

**Small open-weight models fail on multi-step calculation, and they fail completely rather
than gracefully.** A benchmark of financial-table extraction and calculation built from real
annual reports finds models in the ~24B class scoring at or near zero on the multi-step
calculation split — failing catastrophically in multivariate scenarios, in the authors'
words — and models in the 8B class producing errors at rates that make them unsuitable
wherever financial fidelity matters. The same benchmark finds direct lookup is the scenario
these models handle best, and that even the strongest frontier model tested carries a 4–8%
error rate there. ([arXiv 2508.05201](https://www.arxiv.org/pdf/2508.05201))

**A deterministic parser beats a model, and a deterministic parser with a model behind it
beats both.** A 2026 study of tabular PDF extraction with 12–14B local models found a
deterministic parser with model fallback reaching 0.99–1.00 exact match, while model-only
extraction did worse than the parser on its own.
([arXiv 2604.00003](https://arxiv.org/abs/2604.00003v2))

Read together: the thing a model is worst at is exactly the thing tier 0 already does in
code, and the thing it is best at — finding a value on a page — is still worth checking by
hand. That is the whole rule. `scripts/pdf_to_csv.py` is already the shape the second result
recommends: a deterministic extractor whose own docstring tells you to check every row
against the source PDF. A model belongs behind it, under the same check, not in front of it.

## The control that actually works is what goes into the prompt

The instinct behind "run the model locally" is that the exposure lives in the model call. On
work shaped like this, it mostly does not. The exposure lives in what goes into the context
window, and that is a choice made before any model is chosen.

The discipline is to **abstract the fact pattern**. A question about whether an ESPP discount
is charged as a perquisite does not need your PAN, your employer, your salary or your share
count; it needs the shape of the transaction. A question about why an importer silently
dropped a row does not need your holdings; it needs a fixture with the same defect.
`tests/synthetic/` and `tests/synthetic_split/` exist for this reason, and it is the same
instinct behind describing a defect in a commit message without the real figure that revealed
it.

Applied honestly, this leaves very little that has to be tier 2 at all — which is the reason
the privacy gain from going local is smaller than it feels.

## Where a local model runs matters more than which one it is

**Use a machine you own.** A work-issued laptop or an employer-managed workstation is the
wrong host for a personal tax return, and how much VRAM it has does not enter the question.
Your employer is generally a party to the return: they issue the Form 16, their TAN is on it,
and their withholding is one of the figures being reconciled. Putting your PAN, your salary
and your foreign brokerage account numbers on their hardware hands the data to the one
organisation with a live interest in it — and it is likely an acceptable-use problem quite
apart from privacy.

**Shared network storage makes this worse rather than better.** A home directory mounted from
a corporate filer is snapshotted and backed up by processes you do not control, readable by
storage administrators, and outside your deletion authority. Writing a Form 16 there is a
worse privacy outcome than sending a de-identified extract to a commercial API under a
contract: the vendor has no interest in you and cannot connect an abstracted fact pattern to
a person, and an employer is neither of those things. The intuition that local is private
inverts here, so check it rather than assuming it.

The same reasoning applies, more weakly, to a managed endpoint of any kind: mandatory
sensitivity labelling, endpoint agents, and a backup regime you did not choose. The README
raises the point where the import step meets a labelled tenant, and it is a larger question
than it looks there.

**Check that "local" is actually local.** Some editors and agent front-ends accept a
localhost model endpoint and still route the prompt through their own backend to assemble it,
which buys nothing at all; some agents also make background calls to a default cloud model
unless every model setting points at the local endpoint and the cloud credential is removed
from the environment. Confirm it with a connection check — `lsof -i -P` or an outbound
firewall rule — before trusting the setup with a real document.

## What a local model is actually worth here

Narrow, and worth having. It writes the document that has to carry a PAN and a salary figure,
which is transcription and organisation rather than reasoning. It reads the broker PDF that
has no clean export, behind the parser and under verification. It is not the reason this
pipeline is safe — the pipeline is safe because it is code — and it does not extend to
reconciliation, which stays manual.

## What is deliberately not here

No model recommendation, no quantization advice, no memory budget, no tokens-per-second
table. Those answers change monthly, they are properties of a machine rather than of this
repository, and a stale one in a public repo is worse than none at all.

For a sense of the class, and no more than that: as of August 2026, this job is served by a
~12B dense model that reads images natively, run at 8-bit rather than at four, on a laptop
with 24 GB of unified memory — adequate for extraction and transcription and nothing more
demanding. Two things there outlast the numbers. It has to be multimodal, because tier 2 is
reading a rendered page rather than text, and a text-only model cannot do that job at all.
And the precision has to be high enough that the model still agrees with itself, because a
heavily quantized small model can disagree with its own full-precision self often enough to
matter on a column of digits. Note that published "runs in 24 GB" advice usually means a
discrete card with 24 GB of dedicated memory and an operating system living elsewhere, which
is not the same machine. Work the budget out again when you need it.
