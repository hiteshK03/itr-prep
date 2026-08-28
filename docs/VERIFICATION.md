# Verification

*Part of [itr-prep](../README.md) — the eleven test suites, the live round-trips, and the supply chain.*

Eleven suites, all runnable offline once the caches are warm, and all of them on macOS and
Linux alike — CI runs the whole set on both:

```bash
.venv/bin/python tests/test_validation_teeth.py        # schema has teeth
.venv/bin/python tests/test_pipeline.py                # end-to-end invariants
.venv/bin/python tests/test_splits_cash_threshold.py   # splits, cash, threshold report
.venv/bin/python tests/test_doctor_readback.py         # preflight, sniffing, readback, platform boundary
.venv/bin/python tests/test_multisection_adapter.py    # per-section exports
.venv/bin/python tests/test_multisheet_workbook.py     # multi-sheet workbooks
.venv/bin/python tests/test_rules_registry.py          # citations, staleness, code_status
.venv/bin/python tests/test_unlock_credentials.py      # a password cannot escape the process
.venv/bin/python tests/test_capgain.py                 # mutual fund FIFO engine, grandfathering
.venv/bin/python tests/test_mf_input.py                # MF CSV contract, FY window, 112A
.venv/bin/python tests/test_cas_pdf.py                 # CAS statement transcription
```

The doctor suite plants an Indian security of every shape the scope guard claims to detect —
an `INE` ISIN, an `INF` ISIN, an `IN` ISIN that is neither, an ISIN carried only on the
issuer row, an INR row, a rupee sign, an NSE suffix, a BSE suffix and an issuer whose country
is `INDIA` — and asserts each is refused, by `doctor`, by `build`, by `threshold` and by
`run`. It then asserts the negative half, which is the half that could break the tool:
`IVV`, `JNJ`, `CSCO` and `AVGO` still trip nothing, a foreign fund whose *name* says "Fund",
"Growth", "Direct Plan" and "IDCW" still passes, a hand-written `INVALID` in the `isin`
column is not mistaken for an ISIN, and `BRITISH INDIAN OCEAN TERRITORY` is not India.

Every suite runs the citation, review-class, `code_status` and staleness blocks against
**every** registry on disk rather than only the newest, so adding `rules/AY2028-29.json`
cannot silently retire `rules/AY2026-27.json` from coverage. The **act-transition** block
asserts that each registry cites the Act its year is decided under, that every entry in the
later registry records where it came from, and that the Black Money Act entries are marked as
separate legislation rather than renumbered. The **encoded-trap** block fails if either
mutual fund trap is deleted or hollowed out, and the other-schedules summary is asserted to
name the form, rule and deadline the registry gives — Form 67 and rule 128(9) for
AY 2026-27, and no repealed provision at all for AY 2027-28.

Counts are deliberately not listed here. Price data comes from a live source, so check
numbers move between runs and releases, and a README that quotes them rots — what matters is
that every suite finishes with `All ... checks passed`.

**What a bare clone lacks** changes some suites' coverage. Without the optional unlock
extras, `test_unlock_credentials.py` skips its encrypted round-trip checks; without the ITD
schema in `schemas/`, `test_pipeline.py` drops its schema-dependent checks. Both say so when
they skip and neither fails. CI installs the unlock extras deliberately — a proof that skips
is not one — and does not fetch the schema, since the department's artefact is not ours to
download in a workflow.

"Offline" means "reads a cache", and a fresh clone has none — `data/` is gitignored, because
it is derived and because a real user's cached tickers would say what they hold. `./setup.sh`
warms both caches for you, and CI does the same before its own run. If you skipped `setup.sh`,
run `itr-prep fx-update` and one `itr-prep threshold` over each synthetic dataset first.

**`test_validation_teeth.py`** proves the schema validation actually rejects things. It
mutates a known-good row one field at a time and asserts the schema refuses it:
`BENIFICIARY` spelled correctly, an integer country code, a float rupee amount, a
`DD/MM/YYYY` date, a missing required field, an extra field, an over-length string, an
out-of-enum nature code, an over-precise 112A value.

**Which schema, and the honest version of what this proves.** These cases run in CI against
[`tests/fixtures/fa_contract.fixture.json`](../tests/fixtures/fa_contract.fixture.json), which
is **not the department's schema and must never be used as one.** It is a hand-written
transcription of the field contract in
[`docs/VERIFIED_FINDINGS.md`](VERIFIED_FINDINGS.md) §2–§4, which cites the VBA line
numbers it was read from, and it is a strict subset — the country-code enum has 5 of the
department's 249 entries. So be precise about what each run buys:

- **Against the fixture** (a bare clone, and CI): the validator has teeth. draft-04 is
  detected from the schema's own declaration, the ScheduleFA subtree is re-rooted correctly,
  every documented trap is rejected and every legitimate value is accepted. It says **nothing
  about whether the department will accept your return.**
- **Against the ITD schema** (once you download it): the above, plus the only statement that
  matters at filing time.

The suite names which one it used in its own summary line, prints an unmissable banner when
it is the fixture, and fails if `build` could ever discover the fixture as a real schema. A
subtle one it also covers: **the ITD schema is draft-04, not draft-07**, and uses the
boolean form of `exclusiveMinimum`. A draft-07 validator reads `"exclusiveMinimum": false`
as "must exceed 0" and wrongly rejects every legitimately-zero amount — which is exactly
what happened for 2023 and 2024 before this was found. The validator is chosen from the
schema's own declaration.

**`test_pipeline.py`** runs the synthetic dataset (`tests/synthetic/`) through the whole
pipeline for 2023, 2024 and 2025. Rather than golden numbers — which would rot, since
prices come from a live source — it asserts conservation properties: apportioned dividends
sum to dividends received, attributed proceeds sum to sales made, peak ≥ closing,
fully-exited lots have a nil closing balance, and the provenance trail (every figure names
the export row it came from) survives end to end.

**`test_splits_cash_threshold.py`** covers the three later additions against a second
dataset (`tests/synthetic_split/`) built around a real corporate action: 10 AVGO shares held
through the 10-for-1 split of 15 July 2024. The point of the exercise: **choosing the wrong
split basis is a factor-of-ten error** (₹21,22,463 against ₹2,12,246 for the same holding),
and the build refuses to run without `--split-basis`. It also asserts cash lands in Table A2
only, and that a threshold-report year with no data says `NO DATA` rather than zero.

**`test_doctor_readback.py`** covers the preflight command, the header sniffer and the
import verifier. For detection it swaps an E\*TRADE export's filename with a Fidelity one
and back and asserts both are still classified correctly, then that an unclassifiable file
is refused rather than guessed. For the verifier it synthesises the failure shapes seen in
practice — dropped last row, wrong rupee figure in the second row, bare `2` country cell,
serial-number date, stripped zip zero, missing item 19 — and asserts each is caught,
including a JSON that disagrees with its own audit CSV even when the spreadsheet faithfully
matches that JSON. It closes with the platform boundary: the behaviour on Windows, WSL, Mac
and plain Linux is asserted from whichever host runs the suite, and every module in
`itrprep/` must import everywhere with none but `host.py` mentioning
`win32com`/`powershell.exe`/`Excel.Application`.

**`test_multisection_adapter.py`** and **`test_multisheet_workbook.py`** exercise the export
reader against the shapes in [Normalize each broker export](../README.md#1-normalize-each-broker-export):
per-section column resolution, multi-sheet workbooks, gross/withheld/net sell-to-cover
handling, FMV over discounted price, and the loud-failure guarantee on any row that cannot
be read.

**`test_rules_registry.py`** is the enforcement half of the rules registry — see
[Where every statutory figure comes from](STATUTE_REGISTRY.md#where-every-statutory-figure-comes-from) —
including the drift check that the arithmetic actually reads the registry.
`ITRPREP_CHECK_SOURCE_URLS=1` additionally HEADs every cited URL, failing only on 404 or
410, since the department's site answers 403 to any non-browser client.

**`test_unlock_credentials.py`** is adversarial rather than functional: it tries to make a
document password escape the process. It builds a genuinely encrypted PDF, fails to open it
with the wrong credential, then searches the error text, the formatted traceback, and the
CLI's combined stdout and stderr for both the correct password and the wrong one. It asserts
`Credential` withholds its value from `repr`, `str`, f-strings, `%s` formatting and
enclosing containers, and that decrypted output lands 0600 in an owner-only directory git
ignores. The PDF and workbook round-trips skip without the optional unlock extras.

**`test_capgain.py`**, **`test_mf_input.py`** and **`test_cas_pdf.py`** cover the mutual
fund pipeline: the FIFO engine's grandfathering arithmetic (section 90(7)), the CSV
contract and financial-year window, and the CAS statement transcription, including the
runtime-generated synthetic CAS PDF it is tested against.

### The Excel round-trip, live, on all three utilities

Not inferred — **run**, with `itr-prep import`, and verified cell by cell:

| Utility | Reporting year | A3 rows | A2 rows | Result |
|---|---|---|---|---|
| `ITR2_AY_26-27_V1.2.xlsm` | 2025 | 12 | 3 | **PASS** |
| `ITR2_AY_25-26_V1.2.xlsm` | 2024 | 6 | 3 | **PASS** |
| `ITR2_AY_24-25_V1.8.xlsm` | 2023 | 3 | 2 | **PASS** |

Every text field, date and rupee figure in every row matched the generated JSON, and the
JSON's totals matched the audit CSV. This closes the last verification gap: the prior-year
import path was previously only inferred from the fact that the VBA is character-identical
across the three utilities. It is now measured. See also
[`docs/ROUNDTRIP_RESULT.md`](ROUNDTRIP_RESULT.md).

The live runs also found a defect no amount of static reading would have: the utility's zip
cell is number-formatted, so `02210` is stored as `2210`. Roughly a tenth of US zip codes
begin with a zero. `itr-prep import` now repairs it and the verifier fails the import if the
repair does not take.

What is **not** verified: the file-picker dialog itself (bypassed by calling the same
functions `ImportJson` calls), the `--format prefill` output, and anything on the portal
side after Generate JSON.


## Supply chain

`pip install itr-schedule-fa` was **not** used, and no code was taken from it.

That package appeared on PyPI on 2026-07-28 — all three versions within seven hours, the
same day this tool was written — and targets this exact niche. Reading its metadata and
wheel source before deciding:

- It depends on `fa-inrdata-api` and `sbi-tt-rates`, two more packages of the same vintage,
  so adopting it means trusting at least three brand-new packages inside a tax filing.
- Its peak value comes from a **remote HTTP API** (`fainrapi.max_value`). A number you
  cannot reproduce offline is a poor basis for a disclosure you may have to defend years
  later. This tool caches SBI rates and prices locally and shows every input in the audit
  CSV.
- It computes peak as `max_inr_price x quantity`, taking the maximum of a price series and
  multiplying by a single quantity. That is only correct while the share count is constant,
  so it would misstate any lot with a mid-year sale.
- It emits a "portal-ready CSV". The mechanism verified here is JSON through the Excel
  utility; the utility ships CSV helpers for Schedule 112A and TDS but **none for
  Schedule FA**.
- It also depends on `yfinance`, which failed outright in the environment this was written
  in: its bundled `curl_cffi` CA bundle would not verify, so every request died with
  `CertificateVerifyError`. One more moving part in the chain between a broker export and a
  filed return.

Nothing was worth vendoring. The one idea worth noting is that maximising an INR-converted
series corresponds to `--peak-basis inr`, which is already supported as an option.

Runtime dependencies are only `requests` and `jsonschema`, both pinned. `oletools` and
`pdfminer.six` are dev-only, used to decompile the utility's VBA and read the ITD PDFs while
establishing the JSON contract.

`itr-prep unlock` needs `pypdf` and `msoffcrypto-tool`, which are kept in a separate
`requirements-unlock.txt` rather than added to the base install: they are only useful if you
have password-protected statements, and the pipeline itself never touches them. Without them
`unlock` says exactly what to install and every other command is unaffected.
