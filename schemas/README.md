# Where to put the ITD schema

Drop the Income Tax Department's ITR-2 JSON schema in this directory and the tool will
find it. Nothing in here except this file is tracked by git: the schema is the
department's artefact to publish, it is revised without notice, and a stale vendored copy
that quietly validates against the wrong year's rules would be worse than having none.

## Getting it

The e-filing portal publishes it alongside the offline utilities:

<https://www.incometax.gov.in> → **Downloads** → **Income Tax Returns** → the assessment
year you are filing → the ITR-2 **schema** download.

The file is named after the *assessment* year, so the one that reports calendar 2025 is
`ITR-2_2026_Main_V1.1.json` (AY 2026-27). Keep the published filename: the tool reads the
year out of it, so with several years' schemas present, `--year 2024` validates against
`ITR-2_2025_Main_*.json` rather than against whichever file it happened to see first.

```
schemas/
  ITR-2_2026_Main_V1.1.json    # AY 2026-27, reports calendar 2025
  ITR-2_2025_Main_V1.1.json    # AY 2025-26, reports calendar 2024
```

## Alternatives to this directory

```bash
export ITRPREP_SCHEMA=/path/to/ITR-2_2026_Main_V1.1.json   # env var
itr-prep build --schema /path/to/ITR-2_2026_Main_V1.1.json # explicit flag
```

The search order is `--schema`, then `$ITRPREP_SCHEMA`, then `schemas/` and the repository
root, then `schemas/` and the current directory.

## Why not skip validation

`--no-validate` exists, but the schema is the only thing that checks the output will be
accepted before you spend an evening in the Excel utility. A file that is structurally
wrong imports without complaint and fails at the portal.

## The thing in tests/fixtures that looks like a schema

`tests/fixtures/fa_contract.fixture.json` is **not** a substitute for the file described
above and must never be put in this directory. It is a hand-written transcription of the
Schedule FA field contract recorded in [`../docs/VERIFIED_FINDINGS.md`](../docs/VERIFIED_FINDINGS.md),
and it exists only so `tests/test_validation_teeth.py` can prove the validator rejects the
documented traps in CI, where the department's artefact is deliberately not fetched. It
covers one subtree, its country-code enum has 5 of 249 entries, and validating a return
against it proves nothing about whether the return will be accepted.

It is named so that the tool cannot discover it, and the suite fails if that ever changes —
including if somebody copies it in here to make validation appear to work.
