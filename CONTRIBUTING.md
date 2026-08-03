# Contributing

Corrections are very welcome. Two rules matter more than everything else in this file, so
they come first.

## 1. Never commit real data

Treat this repository as published, whatever its current visibility, and a tax filing is about
as sensitive as personal data gets.

- **No PAN, no account numbers, no real holdings, quantities, prices or dates.** Not in code,
  not in fixtures, not in an issue, not in a commit message.
- Fixtures use invented data throughout. The established placeholders are tickers like `CSCO`
  and grant numbers like `RU100001`; follow them rather than inventing a new convention.
- `work/`, `out/`, `.env` and decrypted documents are gitignored. Keep them that way.
- CI fails on a tracked `.env` or on any PAN-shaped string that is not one of the three
  documented placeholders.
- If real data does get committed, treat it as published: rotate anything credential-shaped
  and rewrite history. Deleting it in a later commit does nothing.

See [`SECURITY.md`](SECURITY.md) for how document passwords are handled, and why they must
never appear in a filename, a log line or a model's context window.

## 2. Cite a primary source, or say you cannot

Every statutory figure, date and convention this tool relies on is in
[`rules/AY2026-27.json`](rules/AY2026-27.json) with a citation, and code reads it from there.
Nothing is hardcoded at a call site.

**Acceptable authority for a rate, a limit or a date:**

- the Income-tax Act or the relevant Finance Act text,
- a CBDT notification or circular,
- `incometaxindia.gov.in` or `incometax.gov.in`,
- the Finance Bill memorandum or the Gazette.

**Not acceptable as the cited authority:** ClearTax, Taxmann, TaxGuru, Quicko, CAclubindia,
practitioner blogs, the Big Four's tax alerts, LinkedIn posts. They are genuinely useful for
*finding* a provision, and quoting one in prose is fine — but the citation has to be the
provision itself. `tests/test_rules_registry.py` enforces the domain rule, so a secondary
citation will not pass CI.

A search-results URL is not a citation either. It is a promise that a citation exists
somewhere.

**If you cannot verify something, say so in the pull request rather than committing it.** A
gap that is flagged is useful; a confident wrong figure is worse than nothing, because
somebody will file on it. The `contested` flag exists for genuinely unsettled points — the
revised-return deadline carried it until the enacted Finance Act 2026 text settled it — and
is the honest way to record a disagreement while it lasts.

### Adding or changing a registry entry

1. Add it to `rules/AY<year>.json` with `review`, `applies_to`, `verified_on`, `statute`,
   `check` and at least one official source.
2. Classify it. `stable` means fixed by statute and not expected to move — a settled
   convention or a historical date, carrying `applies_to: "all"`. `annual` means a Finance
   Act or a notification can move it. When in doubt, `annual`: the cost is one URL a year,
   and the cost of the other mistake is a wrong return.
3. If it is `annual`, add it to [`docs/ANNUAL-REVIEW.md`](docs/ANNUAL-REVIEW.md) with its
   source link and what specifically to re-check. The test fails if you forget.
4. Read it through `itrprep/rules.py` at the point of use. Do not copy the value into a module.

Scope for the registry is foreign asset disclosure and the schedules that depend on it.
Slab rates, Chapter VI-A deductions and the section 112A grandfathering date do not belong
here.

## Scope

This tool produces **Schedule FA** and the Schedule CG, OS, FSI and TR aggregates that hang
off it, for an Indian resident holding foreign shares and cash. That is the whole remit.

Out of scope, and a pull request adding any of it will be declined however good it is: old
versus new regime comparison, Chapter VI-A deductions, presumptive taxation, crypto or VDAs,
house property, business income, browser automation of the e-filing portal, and general ITR
form selection. Each of those is a different tool with a different risk profile.

The README's Roadmap records Indian mutual funds and the other ITR forms as directions the
author may take one day. Nothing there is built or scheduled, and it does not pre-approve a
pull request: if you want to open that door, open an issue about the design first.

So is **a model anywhere in the arithmetic** — an extraction step that infers a missing
figure, a summariser that totals the audit CSV, a reconciliation helper. A model may locate
and transcribe a figure and may never compute one; [`AGENTS.md`](AGENTS.md) states the rule
and [`docs/AI-ASSISTANCE.md`](docs/AI-ASSISTANCE.md) gives the evidence for it.

## What is most useful

- **Another broker adapter.** A `Profile` in `itrprep/adapters.py` plus a fixture export with
  every figure replaced by an invented one. The multi-section and multi-sheet suites show the
  shape a good fixture takes.
- **A newer utility version.** If the ITD ships a version where the named ranges or the
  `ImportScheduleFA` signature have moved, that is worth knowing.
  `scripts/probe_workbook.ps1` dumps what a workbook actually contains.
- **A wrong claim.** Everything in [`docs/VERIFIED_FINDINGS.md`](docs/VERIFIED_FINDINGS.md)
  cites a line number so it can be checked rather than believed. If one is wrong, that is the
  most valuable issue you can open.
- **A registry entry that has moved.** Especially the `annual` ones.

## Working on the code

```bash
./setup.sh                                            # venv + deps
.venv/bin/python -m pip install -e .                  # puts itr-prep on PATH
.venv/bin/python -m pip install -r requirements-unlock.txt   # only for `itr-prep unlock`
```

**Tests are plain scripts, not pytest.** Each collects its failures, prints every check with
`ok` or `FAIL`, and exits non-zero. There is no runner to learn and no fixture magic to read
around:

```bash
for t in tests/test_*.py; do .venv/bin/python "$t" || break; done
```

All of them must pass before every commit, and all of them run offline. Add checks to the
suite that already covers the area rather than starting a new file, and update the counts in
the README's Verification section.

**Lint:** `ruff check .` with the configuration in `pyproject.toml`. The rule selection is
deliberately narrow — it catches mistakes rather than imposing a style. If a rule fights the
code for no reader benefit, argue for a per-file ignore with a comment saying why, as the
existing ones do.

### Style, such as it is

- Docstrings explain **why**, and frequently explain a statutory trap. They are the most
  valuable prose in the repository. Write them for someone who has to defend this output to
  an assessing officer in three years.
- Comments explain intent or a constraint the code cannot express. They do not narrate.
- Errors name the thing that is wrong and what to do about it. `doctor` collects problems and
  reports them together rather than raising on the first; that pattern is deliberate, because
  someone with eleven bad rows should learn all eleven in one run.
- Money is `Decimal`, never `float`. Rupee amounts are integers at the point of emission.
- Two runtime dependencies. Adding a third needs a reason in the pull request.

## Commits and pull requests

Explain **why** in the commit message, not what the diff already shows. Say what the previous
behaviour got wrong and what the change makes possible. If a statutory position changed, cite
the provision.

In the pull request, state what you verified and how, and be explicit about what you did not
verify. "I could not confirm this against a CBDT notification" is a useful sentence.

## Licence

MIT. By contributing you agree your contribution is licensed under it.

Nothing here is tax advice, and a contribution does not make you responsible for anyone's
return — but do bear in mind that people file on this output.
