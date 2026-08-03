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
