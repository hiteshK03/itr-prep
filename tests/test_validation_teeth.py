"""Negative tests: prove the schema validation actually rejects the known traps.

A validator that accepts everything is worse than none, because it manufactures false
confidence. Each case below mutates one field of a known-good row and asserts the schema
rejects it.

**Which schema, and why it matters.** These cases used to run only when the department's
ITR-2 schema was present, and CI deliberately does not fetch it -- so the README described
24 validation cases that no automation had ever run, and `itrprep/validate.py` was
unexercised in CI despite containing the draft-04 selection that once caused every
legitimately-zero rupee amount to be rejected for 2023 and 2024.

So there are two schemas this can run against, and the suite says which every time:

- **The official ITD schema**, if you have downloaded it. This is the only run that says
  anything about whether the department will accept a return.
- **`tests/fixtures/fa_contract.fixture.json`** otherwise. That file is *not* the
  department's schema. It is a hand-written transcription of the field contract recorded in
  `docs/VERIFIED_FINDINGS.md` sections 2, 3 and 4, which cites the VBA line numbers it was
  read from. Running against it proves the validator has teeth -- that draft-04 is detected,
  that the ScheduleFA subtree is re-rooted correctly, that errors surface -- and proves
  nothing whatever about the department's acceptance.

The fixture is deliberately not named `ITR-2_*Main*.json` and does not live in `schemas/`,
so `build` cannot pick it up and report a return as validated when it is not. That is not
left to convention: `check_fixture_is_not_discoverable` below fails if it ever becomes
discoverable.

Run:  .venv/bin/python tests/test_validation_teeth.py
"""

from __future__ import annotations

import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import validate

_HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT_FIXTURE = os.path.join(_HERE, "fixtures", "fa_contract.fixture.json")

GOOD_A3 = {
    "CountryName": "UNITED STATES OF AMERICA",
    "CountryCodeExcludingIndia": "2",
    "NameOfEntity": "Cisco Systems, Inc.",
    "AddressOfEntity": "170 West Tasman Drive, San Jose, California",
    "ZipCode": "08933",
    "NatureOfEntity": "Listed Company",
    "InterestAcquiringDate": "2025-02-15",
    "InitialValOfInvstmnt": 388350,
    "PeakBalanceDuringPeriod": 641782,
    "ClosingBalance": 0,
    "TotGrossAmtPaidCredited": 0,
    "TotGrossProceeds": 555282,
}

GOOD_A2 = {
    "CountryName": "UNITED STATES OF AMERICA",
    "CountryCodeExcludingIndia": "2",
    "FinancialInstName": "Morgan Stanley Smith Barney LLC (E*TRADE)",
    "FinancialInstAddress": "1585 Broadway, New York, New York",
    "ZipCode": "10036",
    "AccountNumber": "TEST-0001",
    "Status": "OWNER",
    "AccOpenDate": "2022-07-01",
    "PeakBalanceDuringPeriod": 3821302,
    "ClosingBalance": 2146020,
    "GrossAmtPaidCredited": 0,
    "NatureOfAmount": "N",
}


def _fa(a3=None, a2=None):
    out = {}
    if a3 is not None:
        out["DtlsForeignEquityDebtInterest"] = [a3]
    if a2 is not None:
        out["DtlsForeignCustodialAcc"] = [a2]
    return out


def _mutate(base, **changes):
    row = copy.deepcopy(base)
    for key, value in changes.items():
        if value is _DELETE:
            row.pop(key, None)
        else:
            row[key] = value
    return row


class _Delete:
    pass


_DELETE = _Delete()


NOT_ITD_MARKER = "NOT THE ITD SCHEMA"


def _is_fixture(path: str) -> bool:
    """Does the schema at `path` declare itself a hand-written stand-in?"""
    try:
        with open(path, encoding="utf-8") as fh:
            return NOT_ITD_MARKER in str(json.load(fh).get("title", "")).upper()
    except (OSError, ValueError):
        return False


def check_fixture_is_not_discoverable() -> list[str]:
    """The fixture must never be mistakable for the department's schema.

    Two ways that could go wrong, and both are checked rather than trusted: the file could be
    renamed or moved into `schemas/` so `validate.find_schema()` returns it, and the warning
    in its own `title` could be dropped by somebody tidying up.
    """
    problems = []
    try:
        found = validate.find_schema()
    except validate.SchemaError:
        found = ""
    # Either the fixture itself became discoverable, or a copy of it did. The second is the
    # likelier accident -- somebody drops it in schemas/ to "make validation work" -- so the
    # test is on what the discovered file says about itself, not only on its path.
    if found and (os.path.samefile(found, CONTRACT_FIXTURE) or _is_fixture(found)):
        problems.append(
            f"a hand-written contract fixture is discoverable as an ITD schema ({found}). "
            "`build` would validate against it and report a return as checked when nothing "
            "has checked it. Keep it out of schemas/ and out of validate.SCHEMA_GLOB."
        )
    if not _is_fixture(CONTRACT_FIXTURE):
        problems.append(
            "the contract fixture's title no longer says it is not the ITD schema. That "
            "sentence is the only thing telling a reader who opens the file what it is."
        )
    return problems


def main() -> int:
    structural = check_fixture_is_not_discoverable()

    try:
        schema, schema_path = validate.load_schema()
    except validate.SchemaError:
        if not os.path.exists(CONTRACT_FIXTURE):
            # The fixture is tracked, so its absence is a broken checkout rather than a
            # configuration a contributor can be in. Say so instead of skipping: a suite
            # that quietly asserts nothing is the failure mode this file exists to close.
            print(f"FAILED: {CONTRACT_FIXTURE} is missing and no ITD schema is present, so "
                  "there is nothing to validate against.")
            return 1
        schema, schema_path = validate.load_schema(CONTRACT_FIXTURE)
    # "Official" means the department's artefact, not merely that some schema was found. A
    # copy of the fixture behind $ITRPREP_SCHEMA would otherwise be announced as the real one.
    official = not _is_fixture(schema_path)
    if not official:
        print("=" * 78)
        print("!! The official ITD schema is not present, so these cases run against")
        print("!! tests/fixtures/fa_contract.fixture.json -- a HAND-WRITTEN transcription of")
        print("!! docs/VERIFIED_FINDINGS.md, NOT the department's artefact. This proves the")
        print("!! validator rejects what it should. It says nothing about whether the")
        print("!! department will accept any return. schemas/README.md has the real one.")
        print("=" * 78)
        print()
    print(f"schema      : {schema_path}")
    print(f"schema draft: {validate.schema_draft(schema)}")
    print(f"validator   : "
          f"{__import__('jsonschema').validators.validator_for(schema).__name__}\n")

    must_pass = [
        ("known-good A3 row", _fa(a3=GOOD_A3)),
        ("known-good A2 row", _fa(a2=GOOD_A2)),
        ("both tables together", _fa(a3=GOOD_A3, a2=GOOD_A2)),
        # A2 with nothing credited all year. This is the case a draft-07 validator
        # wrongly rejects because of the boolean exclusiveMinimum.
        ("A2 with zero GrossAmtPaidCredited",
         _fa(a2=_mutate(GOOD_A2, GrossAmtPaidCredited=0, NatureOfAmount="N"))),
        ("A3 with negative closing balance",
         _fa(a3=_mutate(GOOD_A3, ClosingBalance=-1))),
        ("empty ScheduleFA", {}),
    ]

    must_fail = [
        # The trap the whole project hinges on.
        ("Status spelled correctly as BENEFICIARY",
         _fa(a2=_mutate(GOOD_A2, Status="BENEFICIARY"))),
        ("Status lowercased",
         _fa(a2=_mutate(GOOD_A2, Status="owner"))),
        # Country code must be the STRING "2".
        ("CountryCodeExcludingIndia as integer 2",
         _fa(a3=_mutate(GOOD_A3, CountryCodeExcludingIndia=2))),
        ("CountryCodeExcludingIndia not in enum",
         _fa(a3=_mutate(GOOD_A3, CountryCodeExcludingIndia="999999"))),
        # Money fields are integer, not float or string.
        ("PeakBalanceDuringPeriod as float",
         _fa(a3=_mutate(GOOD_A3, PeakBalanceDuringPeriod=641782.45))),
        ("PeakBalanceDuringPeriod as string",
         _fa(a3=_mutate(GOOD_A3, PeakBalanceDuringPeriod="641782"))),
        # Dates are ISO in JSON, never the DD/MM/YYYY the sheet displays.
        ("InterestAcquiringDate as DD/MM/YYYY",
         _fa(a3=_mutate(GOOD_A3, InterestAcquiringDate="15/02/2025"))),
        ("InterestAcquiringDate with impossible month",
         _fa(a3=_mutate(GOOD_A3, InterestAcquiringDate="2025-13-01"))),
        # Every field is required and additionalProperties is false.
        ("A3 missing CountryName",
         _fa(a3=_mutate(GOOD_A3, CountryName=_DELETE))),
        ("A3 missing TotGrossProceeds",
         _fa(a3=_mutate(GOOD_A3, TotGrossProceeds=_DELETE))),
        ("A3 with an extra unexpected key",
         _fa(a3=_mutate(GOOD_A3, Ticker="CSCO"))),
        ("A2 missing NatureOfAmount",
         _fa(a2=_mutate(GOOD_A2, NatureOfAmount=_DELETE))),
        ("A2 NatureOfAmount not in enum",
         _fa(a2=_mutate(GOOD_A2, NatureOfAmount="X"))),
        # A2 alone forbids negatives, unlike the A3 money fields.
        ("A2 negative GrossAmtPaidCredited",
         _fa(a2=_mutate(GOOD_A2, GrossAmtPaidCredited=-5))),
        # maxLength ceilings.
        ("NatureOfEntity longer than 34 chars",
         _fa(a3=_mutate(GOOD_A3, NatureOfEntity="X" * 35))),
        ("ZipCode longer than 8 chars",
         _fa(a3=_mutate(GOOD_A3, ZipCode="123456789"))),
        ("NameOfEntity empty",
         _fa(a3=_mutate(GOOD_A3, NameOfEntity=""))),
        ("unknown table name",
         {"DtlsForeignEquityDebt": [GOOD_A3]}),
    ]

    failures = len(structural)
    for problem in structural:
        print(f"STRUCTURAL FAILURE   {problem}")
    if not structural:
        print("ok                   the contract fixture cannot be found as an ITD schema")
        print("ok                   and says in its own title that it is not one")
        print()

    for label, instance in must_pass:
        errors = validate.validate_schedule_fa(instance, schema)
        if errors:
            failures += 1
            print(f"UNEXPECTED REJECT  {label}")
            for e in errors[:3]:
                print(f"                     {e}")
        else:
            print(f"accepted (correct)   {label}")

    print()
    for label, instance in must_fail:
        errors = validate.validate_schedule_fa(instance, schema)
        if not errors:
            failures += 1
            print(f"UNEXPECTED ACCEPT  {label}")
        else:
            print(f"rejected (correct)   {label}")
            print(f"                     -> {errors[0][:110]}")

    print()
    total = len(must_pass) + len(must_fail) + 2
    against = ("the official ITD schema" if official
               else "the hand-written contract fixture, NOT the ITD schema")
    if failures:
        print(f"FAILED: {failures} of {total} cases behaved wrongly, against {against}")
        return 1
    print(f"All {total} validation cases behaved correctly against {against} "
          f"({len(must_pass)} accepted, {len(must_fail)} rejected, 2 structural).")

    if official:
        failures += multiple_of_teeth(schema)
    return failures and 1 or 0


def _row_112a(**overrides) -> dict:
    """A schema-complete Schedule 112A detail row (definition Schedule112A115ADType),
    with four-decimal per-unit values -- the exact shape KNOWN-ISSUES.md issue 1 is about."""
    row = {
        "ShareOnOrBefore": "AE",
        "ISINCode": "INFSYNTHTST1",
        "ShareUnitName": "SYNTHETIC EQUITY FUND TEST SCHEME",
        "NumSharesUnits": 1234.5678,
        "SalePricePerShareUnit": 45.6789,
        "TotSaleValue": 56394,
        "CostAcqWithoutIndx": 30000,
        "AcquisitionCost": 12345.6789,
        "LTCGBeforelowerB1B2": 26394,
        "FairMktValuePerShareunit": 40.1234,
        "TotFairMktValueCapAst": 49535,
        "ExpExclCnctTransfer": 0.0,
        "TotalDeductions": 0,
        "Balance": 26394,
    }
    row.update(overrides)
    return row


def multiple_of_teeth(schema: dict) -> int:
    """KNOWN-ISSUES.md issue 1, decided: the department's Schedule 112A schema puts
    multipleOf 0.0001 on five per-unit fields, and jsonschema's binary-float check wrongly
    rejects roughly 28% of legal four-decimal values. itrprep/validate.py overrides the
    check with exact decimal arithmetic. These cases prove both directions of the fix.
    Runs only against the official schema -- the constraint is the department's."""
    defs = schema["definitions"]
    subschema = {
        "$schema": schema.get("$schema"),
        "definitions": defs,
        "$ref": "#/definitions/Schedule112A115ADType",
    }

    # 12.34 is the smallest failing value named in the issue; add the kinds the registry
    # cares about: unit counts and 31-Jan-2018 NAVs, both naturally four-decimal.
    four_decimal = [12.34, 99.9999, 0.1234, 37495.6585, 826852.1246, 236439.0]
    over_precise = [12.34567, 0.00001, 1.234567891, 0.1 + 0.2]

    failures = 0
    for v in four_decimal:
        row = _row_112a(NumSharesUnits=v, AcquisitionCost=v,
                        SalePricePerShareUnit=v, FairMktValuePerShareunit=v,
                        ExpExclCnctTransfer=v)
        errs = [e for e in validate._format_errors(validate._validator(subschema), row)
                if "multiple of" in e]
        if errs:
            failures += 1
            print(f"UNEXPECTED REJECT  legal four-decimal 112A value {v!r}: {errs[0][:90]}")
        else:
            print(f"accepted (correct)   legal four-decimal 112A value {v!r}")
    for v in over_precise:
        row = _row_112a(NumSharesUnits=v)
        errs = [e for e in validate._format_errors(validate._validator(subschema), row)
                if "multiple of" in e]
        if not errs:
            failures += 1
            print(f"UNEXPECTED ACCEPT  over-precise 112A value {v!r}")
        else:
            print(f"rejected (correct)   over-precise 112A value {v!r}")
    print()
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
