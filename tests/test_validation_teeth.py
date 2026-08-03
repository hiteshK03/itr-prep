"""Negative tests: prove the schema validation actually rejects the known traps.

A validator that accepts everything is worse than none, because it manufactures false
confidence. Each case below mutates one field of a known-good row and asserts that the
official ITD schema rejects it.

Run:  .venv/bin/python tests/test_validation_teeth.py
"""

from __future__ import annotations

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import validate

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


def main() -> int:
    try:
        schema, schema_path = validate.load_schema()
    except validate.SchemaError as exc:
        print(str(exc))
        print("\nSKIPPED: this suite validates against the real ITD schema and cannot "
              "run without it.")
        return 0
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

    failures = 0

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
    total = len(must_pass) + len(must_fail)
    if failures:
        print(f"FAILED: {failures} of {total} cases behaved wrongly")
        return 1
    print(f"All {total} validation cases behaved correctly "
          f"({len(must_pass)} accepted, {len(must_fail)} rejected).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
