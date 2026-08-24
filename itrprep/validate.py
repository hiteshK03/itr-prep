"""Validating emitted JSON against the official ITD schema.

Two things about this schema matter and are easy to get wrong.

**It is draft-04, not draft-07.** `ITR-2_2026_Main_V1.1.json` declares
`http://json-schema.org/draft-04/schema#` and uses draft-04's boolean form of
`exclusiveMinimum`/`exclusiveMaximum` in 659 places. Under draft-07 semantics those
keywords must be numbers, so a draft-07 validator reads `"exclusiveMinimum": false` as
"must be greater than 0" and rejects every legitimately-zero amount -- for instance a
Table A2 account with nothing credited during the year. The validator is therefore chosen
from the schema's own `$schema` declaration rather than hardcoded.

**A ScheduleFA-only document cannot be validated at the root**, because ITR2's `required`
list names eight other blocks (CreationInfo, Form_ITR2, PartA_GEN1, ScheduleCYLA,
ScheduleBFLA, PartB-TI, PartB_TTI, Verification). The ScheduleFA subtree is validated
against `#/definitions/ScheduleFA` instead, which is still strict: `additionalProperties`
is false, every A2/A3 field is `required`, money fields are `integer`, dates carry a regex,
the country code and the status/nature enums are closed, and every string has a maxLength.
Full-document validation happens when `--merge-into` supplied a complete return.
"""

from __future__ import annotations

import glob
import json
import os
import re
from decimal import Decimal, InvalidOperation

from jsonschema.exceptions import ValidationError
from jsonschema.validators import extend, validator_for

# The schema is a large artefact published by the Income Tax Department. It is deliberately
# NOT vendored into this repository: it is theirs to distribute, it changes without notice,
# and a stale copy that silently validates against last year's rules is worse than no copy.
# So it is located at run time instead.
SCHEMA_ENV_VAR = "ITRPREP_SCHEMA"
SCHEMA_GLOB = "ITR-2_*Main*.json"
SCHEMA_DIRNAME = "schemas"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Assessment year appearing in the ITD's filename, e.g. ITR-2_2026_Main_V1.1.json is the
# schema for AY 2026-27, which reports calendar 2025.
_AY_IN_NAME = re.compile(r"ITR-2[_-](\d{4})")


class SchemaError(Exception):
    pass


def search_dirs() -> list[str]:
    """Where a schema may live, in precedence order, deduplicated."""
    candidates = [
        os.path.join(_REPO_ROOT, SCHEMA_DIRNAME),
        _REPO_ROOT,
        os.path.join(os.getcwd(), SCHEMA_DIRNAME),
        os.getcwd(),
    ]
    out: list[str] = []
    for path in candidates:
        real = os.path.normpath(path)
        if real not in out:
            out.append(real)
    return out


def find_schema(explicit: str = "", year: int | None = None) -> str:
    """Resolve the schema path: explicit, then environment, then a directory search.

    `year` is the reporting *calendar* year. The ITD names each schema after the assessment
    year, so calendar 2025 wants `ITR-2_2026_...`. When several schemas are present the
    matching one is chosen, which means prior-year builds validate against their own year's
    rules instead of whichever file happened to be found first.
    """
    if explicit:
        if not os.path.exists(explicit):
            raise SchemaError(_not_found_message(f"--schema {explicit} does not exist"))
        return explicit

    from_env = os.environ.get(SCHEMA_ENV_VAR, "").strip()
    if from_env:
        if not os.path.exists(from_env):
            raise SchemaError(
                _not_found_message(
                    f"${SCHEMA_ENV_VAR} points at {from_env}, which does not exist"
                )
            )
        return from_env

    found: list[str] = []
    for directory in search_dirs():
        for path in sorted(glob.glob(os.path.join(directory, SCHEMA_GLOB))):
            if path not in found:
                found.append(path)
    if not found:
        raise SchemaError(_not_found_message("no schema file was found"))

    if year is not None:
        wanted = str(year + 1)
        for path in found:
            match = _AY_IN_NAME.search(os.path.basename(path))
            if match and match.group(1) == wanted:
                return path
        # Nothing for that year. Validating against a different year's schema would be
        # misleading, so say which years are actually available.
        available = sorted(
            {m.group(1) for m in
             (_AY_IN_NAME.search(os.path.basename(p)) for p in found) if m}
        )
        raise SchemaError(
            f"No ITD schema for assessment year {wanted}-"
            f"{str(year + 2)[-2:]} (reporting calendar {year}).\n"
            f"Found schemas for assessment year(s): "
            f"{', '.join(available) if available else 'none identifiable'}.\n\n"
            + _download_hint()
        )

    # No year hint: take the newest, which is the one a plain `validate` most likely wants.
    return sorted(found, key=_ay_sort_key)[-1]


def _ay_sort_key(path: str):
    match = _AY_IN_NAME.search(os.path.basename(path))
    return (int(match.group(1)) if match else 0, path)


def _download_hint() -> str:
    return (
        "The schema is published by the Income Tax Department and is not redistributed\n"
        f"with this tool. Get `{SCHEMA_GLOB}` -- for example\n"
        "`ITR-2_2026_Main_V1.1.json` for AY 2026-27 -- from the e-filing portal at\n"
        "https://www.incometax.gov.in -> Downloads -> Income Tax Returns, where it is\n"
        "published alongside the offline utilities as the ITR-2 schema.\n\n"
        "Then do any one of:\n"
        f"  - drop it in {os.path.join(_REPO_ROOT, SCHEMA_DIRNAME)}/\n"
        f"  - export {SCHEMA_ENV_VAR}=/path/to/ITR-2_2026_Main_V1.1.json\n"
        "  - pass --schema /path/to/ITR-2_2026_Main_V1.1.json\n\n"
        "Or pass --no-validate to build without validating, which is not advised: the\n"
        "schema is the only check that the output will be accepted."
    )


def _not_found_message(problem: str) -> str:
    searched = "\n".join(f"  {d}" for d in search_dirs())
    return (
        f"ITD ITR-2 schema not available: {problem}.\n\n"
        f"Searched for `{SCHEMA_GLOB}` in:\n{searched}\n\n" + _download_hint()
    )


def load_schema(path: str = "", year: int | None = None) -> tuple[dict, str]:
    """Load the schema. Returns (schema, path it was read from)."""
    resolved = find_schema(path, year)
    with open(resolved, encoding="utf-8") as fh:
        return json.load(fh), resolved


def schema_draft(schema: dict) -> str:
    return schema.get("$schema", "(unspecified)")


def _validator(schema: dict):
    """Pick the validator class the schema itself asks for, then extend it with the exact
    ``multipleOf`` check (see below) before instantiating."""
    cls = validator_for(schema)
    cls.check_schema(schema)
    return extend(cls, {"multipleOf": _exact_multiple_of})(schema)


def _exact_multiple_of(validator, dB, instance, schema):
    """``multipleOf`` done in decimal, not binary floats.

    The department's Schedule 112A schema puts ``"multipleOf": 0.0001`` on five per-unit
    fields -- "four decimal places". jsonschema's stock implementation checks
    ``int(instance / dB) != instance / dB`` in binary floats, where ``0.0001`` is not
    representable, so roughly 28% of perfectly legal four-decimal values fail
    (``12.34`` is one of them). The constraint and the values are both right; the
    arithmetic is wrong. So the check is re-implemented exactly, on the value's shortest
    round-trip decimal representation -- ``Decimal(repr(x))`` -- which is the literal
    ``json.dump`` writes and therefore the figure the department actually receives.

    Over-precise values still fail: five decimals, or float noise like ``0.1 + 0.2``,
    are not multiples of 0.0001 in decimal either. The decision, and the options it
    rejected, are recorded in KNOWN-ISSUES.md, issue 1.
    """
    if not validator.is_type(instance, "number"):
        return
    try:
        failed = Decimal(repr(instance)) % Decimal(repr(dB)) != 0
    except (InvalidOperation, ValueError):
        # Non-finite floats (inf/nan) and anything Decimal refuses cannot be an exact
        # multiple of a decimal step.
        failed = True
    if failed:
        yield ValidationError(f"{instance!r} is not a multiple of {dB}")


def validate_schedule_fa(schedule_fa: dict, schema: dict) -> list[str]:
    """Validate a ScheduleFA object against `#/definitions/ScheduleFA`."""
    # Re-root the document on the ScheduleFA definition while keeping `definitions` in
    # place, so every internal $ref still resolves without an external resolver.
    subschema = {
        "$schema": schema.get("$schema"),
        "definitions": schema["definitions"],
        "$ref": "#/definitions/ScheduleFA",
    }
    return _format_errors(_validator(subschema), schedule_fa)


def validate_full_document(document: dict, schema: dict) -> list[str]:
    """Validate a whole {"ITR": {"ITR2": ...}} document."""
    return _format_errors(_validator(schema), document)


def _format_errors(validator, instance) -> list[str]:
    errors = []
    for err in sorted(validator.iter_errors(instance),
                      key=lambda e: list(map(str, e.absolute_path))):
        location = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{location}: {err.message}")
    return errors
