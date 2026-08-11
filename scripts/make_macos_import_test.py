#!/usr/bin/env python3
"""Build the test kit for the department's macOS Common Offline Utility.

Two things about that utility are unknown and cannot be settled from Linux, because the
macOS build is Apple Silicon only and there is no equivalent of `itr-prep import`'s cell-by-cell
read-back for it:

  1. which shape of JSON its "Import draft ITR / import JSON" entry point accepts -- the
     partial `{"ITR":{"ITR2":{"ScheduleFA": ...}}}` document this tool emits by default, or the
     complete return `--merge-into` produces; and
  2. whether a large Schedule FA Table A3 survives that import with every row intact.

The second is the one that matters. The Excel utility's Schedule FA importer runs under
`On Error Resume Next` and drops rows without saying so, which is why `itr-prep import` reads
every cell back; nothing equivalent exists for the desktop app, so the only check available
there is a person's eyes. This script therefore builds a dataset sized like a real return --
178 Table A3 rows -- whose rows carry a sequential marker in the entity-name column, an
ascending acquisition date, and a zero-padded zip that doubles as a second sequence. Scrolling
the app's Schedule FA screen then answers "did every row arrive, in order, unmangled?" in
seconds rather than by cross-referencing a spreadsheet.

Everything it writes is invented. No PAN, account number, holding or figure here belongs to
anybody. Output goes to a gitignored directory; see docs/MACOS_UTILITY_TEST.md for what to do
with it.

    python scripts/make_macos_import_test.py

Needs the ITD ITR-2 schema in schemas/ (see schemas/README.md) and a warm FX cache
(`itr-prep fx-update`). It fails rather than producing an unvalidated file.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from itrprep import validate  # noqa: E402

DEFAULT_OUT_DIR = os.path.join(ROOT, "macos-utility-test")
DEFAULT_ROWS = 178
DEFAULT_YEAR = 2025

# ---------------------------------------------------------------- the synthetic dataset

# One ticker per Table A3 row. Table A3 is emitted sorted by (ticker, acquisition date,
# lot id), and zero-padded tickers sort into numeric order, so row N of the table is always
# ticker N -- which is what makes the sequential marker below trustworthy as a position check
# rather than just a presence check.
TICKER_PREFIX = "SYN"

FIRST_ACQUISITION = dt.date(2023, 1, 9)
ACQUISITION_STEP_DAYS = 5
SHARES_PER_LOT = Decimal(10)

# Each ticker's closing price through the reporting year, as a multiple of its own base
# price. The peak sits in August and the year closes near where it opened, so every row gets
# a peak strictly above its closing balance -- itself a quick thing to eyeball.
MONTH_MULTIPLIER = {
    1: "1.00", 2: "1.05", 3: "1.10", 4: "1.15", 5: "1.20", 6: "1.25",
    7: "1.30", 8: "1.35", 9: "1.28", 10: "1.18", 11: "1.10", 12: "1.04",
}
YEAR_END_MULTIPLIER = "1.02"
SALE_MULTIPLIER = "1.15"

# Rows that exercise the two columns a holding-and-never-selling dataset would leave at zero
# across the whole table -- and, in the sold rows, a legitimately zero closing balance, which
# is the value the ITD schema's draft-04 `exclusiveMinimum: false` makes it easy to reject by
# accident.
DIVIDEND_EVERY = 10
DIVIDEND_DATE = dt.date(2025, 9, 15)
DIVIDEND_USD = Decimal("100.00")
DIVIDEND_WITHHELD_USD = Decimal("25.00")
SOLD_ROWS = (47, 153)
SALE_DATE = dt.date(2025, 10, 15)

ACCOUNTS = [
    # (account_id, first row, last row, institution, address, zip, account number, opened)
    ("synth_alpha", 1, 60, "Synthetic Test Custodian Alpha LLC",
     "1 Test Plaza, Synthetic City, Nowhere State", "99001", "SYNTH-A3TEST-0001", "2022-01-03"),
    ("synth_bravo", 61, 120, "Synthetic Test Custodian Bravo LLC",
     "2 Test Plaza, Synthetic City, Nowhere State", "99002", "SYNTH-A3TEST-0002", "2022-06-01"),
    ("synth_charlie", 121, 178, "Synthetic Test Custodian Charlie LLC",
     "3 Test Plaza, Synthetic City, Nowhere State", "99003", "SYNTH-A3TEST-0003", "2023-02-01"),
]


def ticker_for(n: int) -> str:
    return f"{TICKER_PREFIX}{n:03d}"


def entity_name(n: int, rows: int) -> str:
    """The marker a person actually reads while scrolling.

    Uniform shape so a gap in the sequence is obvious at a glance, with the first and last
    rows called out by name because those are the two a truncating importer loses.
    """
    marker = f"ROW {n:03d} OF {rows}"
    if n == 1:
        return f"{marker} - FIRST ROW - SYNTHETIC TEST ISSUER"
    if n == rows:
        return f"{marker} - LAST ROW - SYNTHETIC TEST ISSUER"
    return f"{marker} - SYNTHETIC TEST ISSUER"


def entity_address(n: int, rows: int) -> str:
    """The same sequence again, in a second column, so a shuffle between columns shows."""
    return f"Unit {n:03d} of {rows}, 12 Import Test Road, Synthetic City, Nowhere State"


def entity_zip(n: int) -> str:
    """Zero-padded, so every row's zip has leading zeros.

    A numeric-formatted zip cell is what turns 02210 into 2210 in the Excel utility -- a real
    defect this project had to repair. Padding every row means the same defect, if the desktop
    app has it, shows up as a whole column rather than as one row nobody thinks to check.
    """
    return f"{n:05d}"


def account_for(n: int) -> tuple:
    for account in ACCOUNTS:
        if account[1] <= n <= account[2]:
            return account
    raise SystemExit(f"row {n} falls outside every account range in ACCOUNTS")


def base_price(n: int) -> Decimal:
    return Decimal(100 + n)


def acquisition_date(n: int) -> dt.date:
    return FIRST_ACQUISITION + dt.timedelta(days=ACQUISITION_STEP_DAYS * (n - 1))


def write_inputs(work_dir: str, rows: int, year: int) -> None:
    os.makedirs(work_dir, exist_ok=True)

    with open(os.path.join(work_dir, "issuers.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ticker", "entity_name", "entity_address", "entity_zip",
                         "entity_nature", "country_code", "country_name"])
        for n in range(1, rows + 1):
            writer.writerow([ticker_for(n), entity_name(n, rows), entity_address(n, rows),
                             entity_zip(n), "Listed Company", "2",
                             "UNITED STATES OF AMERICA"])

    with open(os.path.join(work_dir, "accounts.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["account_id", "institution_name", "institution_address",
                         "institution_zip", "account_number", "status", "account_open_date",
                         "country_code", "country_name"])
        for account_id, _first, _last, name, address, zipcode, number, opened in ACCOUNTS:
            writer.writerow([account_id, name, address, zipcode, number, "OWNER", opened,
                             "2", "UNITED STATES OF AMERICA"])

    with open(os.path.join(work_dir, "transactions.csv"), "w", newline="",
              encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["account_id", "ticker", "txn_type", "date", "quantity", "price_usd",
                         "amount_usd", "tax_withheld_usd", "acq_kind", "lot_id", "notes"])
        for n in range(1, rows + 1):
            account_id = account_for(n)[0]
            ticker = ticker_for(n)
            price = base_price(n)
            writer.writerow([account_id, ticker, "BUY", acquisition_date(n).isoformat(),
                             SHARES_PER_LOT, price, SHARES_PER_LOT * price, "", "OPEN_MARKET",
                             f"{ticker}-LOT-1", f"synthetic Table A3 row {n:03d} of {rows}"])
        for n in range(1, rows + 1):
            if n % DIVIDEND_EVERY:
                continue
            writer.writerow([account_for(n)[0], ticker_for(n), "DIVIDEND",
                             DIVIDEND_DATE.isoformat(), "", "", DIVIDEND_USD,
                             DIVIDEND_WITHHELD_USD, "", "",
                             "gives this row a non-zero gross amount credited"])
        for n in (r for r in SOLD_ROWS if r <= rows):
            ticker = ticker_for(n)
            price = (base_price(n) * Decimal(SALE_MULTIPLIER)).quantize(Decimal("0.01"))
            writer.writerow([account_for(n)[0], ticker, "SELL", SALE_DATE.isoformat(),
                             SHARES_PER_LOT, price, SHARES_PER_LOT * price, "", "",
                             f"{ticker}-LOT-1",
                             "fully exited: nil closing balance, non-zero gross proceeds"])

    _write_price_overrides(os.path.join(work_dir, "prices_override.csv"), rows, year)


def _write_price_overrides(path: str, rows: int, year: int) -> None:
    """Supply every close the build needs, so nothing is fetched and nothing is cached.

    `splits.scan` asks each ticker for a series in every year from the earliest transaction
    to at least the current one, and a year it cannot load is reported as a year whose splits
    went unchecked. Covering those years with a single close each keeps the run from warning
    about every invented ticker in turn, none of which could have had a split anyway.
    """
    first_year = min(acquisition_date(n).year for n in range(1, rows + 1))
    scan_years = range(min(first_year, year), max(dt.date.today().year, year) + 1)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ticker", "date", "close_usd"])
        for n in range(1, rows + 1):
            ticker = ticker_for(n)
            price = base_price(n)
            for other in scan_years:
                if other == year:
                    continue
                writer.writerow([ticker, dt.date(other, 1, 2).isoformat(), price])
            # 1 January so a lot carried in from an earlier year can be valued on the first
            # day of the window: `close_on` looks back only within the same year's series.
            writer.writerow([ticker, dt.date(year, 1, 1).isoformat(), price])
            for month, multiplier in MONTH_MULTIPLIER.items():
                writer.writerow([ticker, dt.date(year, month, 1).isoformat(),
                                 (price * Decimal(multiplier)).quantize(Decimal("0.01"))])
            writer.writerow([ticker, dt.date(year, 12, 31).isoformat(),
                             (price * Decimal(YEAR_END_MULTIPLIER)).quantize(Decimal("0.01"))])


# ---------------------------------------------------------------- the complete-return base

# The one placeholder PAN this repository documents (.env.example) and one of the three
# PAN-shaped strings its data-hygiene CI check permits in a tracked file.
PLACEHOLDER_PAN = "AAAAA9999A"

# Verification/Declaration/AssesseeVerPAN is the one PAN field the ITD schema constrains
# beyond the general shape: `[A-Z]{3}[P][A-Z][0-9]{4}[A-Z]`, where the fourth character is the
# holder type and P means an individual. No documented placeholder has one, so it is derived
# here instead of written out, which keeps the only PAN-shaped literal in the tree the
# documented one.
VERIFICATION_PAN = PLACEHOLDER_PAN[:3] + "P" + PLACEHOLDER_PAN[4:]

FILER_NAME = "SYNTHETIC TESTFILER"

_DATE_PATTERN = "([12]\\d{3}-(0[1-9]|1[0-2])-(0[1-9]|[12]\\d|3[01]))"
_EMAIL_PATTERN = (
    "([\\.a-zA-Z0-9_\\-])+@([a-zA-Z0-9_\\-])+(([a-zA-Z0-9_\\-])*\\.([a-zA-Z0-9_\\-])+)+"
)
_PATTERN_SAMPLES = {
    _DATE_PATTERN: "2026-04-01",
    _EMAIL_PATTERN: "synthetic.test@example.invalid",
    "[S][W][0-9]{8}": "SW10000001",
    "[A-Z]{3}[P][A-Z][0-9]{4}[A-Z]": VERIFICATION_PAN,
    "[A-Z]{5}[0-9]{4}[A-Z]": PLACEHOLDER_PAN,
    # CreationInfo.Digest: `-` is an explicitly allowed value, and it is the only one this
    # project will write. Reproducing the real digest would mean reproducing the integrity
    # control the department put on the upload file -- see the README's "The line this
    # project will not cross". The utility computes its own when it generates the return.
    "-|.{44}": "-",
}
_LITERAL_PATTERN = re.compile(r"[A-Za-z0-9 ._:'/-]+")

# `nonEmptyString` is mixed into most string fields through `allOf`, and its pattern permits
# anything (an empty first alternative included). A field carrying only this one is
# unconstrained, so it must not be mistaken for a shape that has to be matched.
_UNCONSTRAINED_PATTERN = (
    "|(\\s*([\\w\\d_=!@#$%\\^*\\(\\){}\\[\\]\\|\\\\:;',\\.\\?/~`\\-\\+<>&]"
    "[\\s\\w\\d_=!@#$%\\^*\\(\\){}\\[\\]\\|\\\\:;',\\.\\?/~`\\-\\+<>&]*)\\s*)"
)

# Everything a schema-shaped skeleton would otherwise fill with a plausible-looking nothing.
# Sane values matter here beyond validity: if the desktop app rejects the base return over an
# unrelated field, the experiment answers the wrong question.
BASE_OVERRIDES = {
    "CreationInfo/SWVersionNo": "1.0",
    "CreationInfo/IntermediaryCity": "Mumbai",
    "Form_ITR2/Description": ("For Individuals and HUFs not having income from profits and "
                              "gains of business or profession"),
    "PartA_GEN1/PersonalInfo/AssesseeName/SurNameOrOrgName": FILER_NAME,
    "PartA_GEN1/PersonalInfo/Address/ResidenceNo": "1",
    "PartA_GEN1/PersonalInfo/Address/LocalityOrArea": "Synthetic Test Locality",
    "PartA_GEN1/PersonalInfo/Address/CityOrTownOrDistrict": "Synthetic Test City",
    "PartA_GEN1/PersonalInfo/Address/StateCode": "19",
    "PartA_GEN1/PersonalInfo/Address/CountryCode": "91",
    "PartA_GEN1/PersonalInfo/Address/PinCode": 400001,
    "PartA_GEN1/PersonalInfo/Address/CountryCodeMobile": 91,
    "PartA_GEN1/PersonalInfo/Address/MobileNo": 9000000000,
    "PartA_GEN1/PersonalInfo/SecondaryAdd": "N",
    # Invented, and the one field in this block that cannot say so in its own value. The schema
    # constrains DOB to a real date and an implausible one risks the app rejecting the base
    # return over something unrelated to Schedule FA, so there is no equivalent of
    # `example.invalid` or 9000000000 to reach for. It is a placeholder date, nobody's.
    "PartA_GEN1/PersonalInfo/DOB": "1985-03-02",
    "PartA_GEN1/PersonalInfo/Status": "I",
    "PartA_GEN1/FilingStatus/OptOutNewTaxRegime": "N",
    "PartA_GEN1/FilingStatus/SeventhProvisio139": "N",
    "PartA_GEN1/FilingStatus/ResidentialStatus": "RES",
    "PartA_GEN1/FilingStatus/HeldUnlistedEqShrPrYrFlg": "N",
    "PartA_GEN1/FilingStatus/FiiFpiFlag": "N",
    # Validation rule 746: the return is invalid without this, whatever Schedule FA says.
    "PartB_TTI/AssetOutIndiaFlag": "YES",
    "PartB_TTI/Refund/BankAccountDtls/BankDtlsFlag": "N",
    "Verification/Declaration/AssesseeVerName": FILER_NAME,
    "Verification/Declaration/FatherName": "SYNTHETIC TESTFILER SENIOR",
    "Verification/Capacity": "S",
    "Verification/Place": "Mumbai",
}


class SchemaShapeError(Exception):
    pass


def build_base_return(schema: dict) -> dict:
    """A complete ITR-2 with every block the schema marks required, and nothing else.

    Derived from the schema rather than written out, because the department revises it
    without notice: a required field added next year gets filled instead of silently
    missing, and an unfamiliar `pattern` stops the script instead of being guessed at.
    """
    itr2 = _skeleton(schema, {"$ref": "#/definitions/ITR2"})
    for path, value in BASE_OVERRIDES.items():
        _set_path(itr2, path, value)
    today = dt.date.today().isoformat()
    _set_path(itr2, "CreationInfo/JSONCreationDate", today)
    _set_path(itr2, "Verification/Date", today)
    return {"ITR": {"ITR2": itr2}}


def _resolve(schema: dict, node: dict) -> dict:
    for _ in range(20):
        if "$ref" not in node:
            return node
        node = schema["definitions"][node["$ref"].rsplit("/", 1)[-1]]
    raise SchemaShapeError("$ref chain did not terminate")


def _flatten(schema: dict, node: dict) -> dict:
    """One dict per node: the ITD schema puts nonEmptyString constraints behind `allOf`."""
    node = _resolve(schema, node)
    out = {k: v for k, v in node.items() if k != "allOf"}
    for member in node.get("allOf", []):
        for key, value in _resolve(schema, member).items():
            out.setdefault(key, value)
    return out


def _skeleton(schema: dict, node: dict, path: str = ""):
    node = _flatten(schema, node)
    if "enum" in node:
        return node["enum"][0]
    kind = node.get("type")
    if kind is None:
        kind = "object" if "properties" in node else "array" if "items" in node else "string"
    if kind == "object":
        properties = node.get("properties", {})
        out = {}
        for key in node.get("required", []):
            if key not in properties:
                raise SchemaShapeError(f"{path}/{key}: required but not described")
            out[key] = _skeleton(schema, properties[key], f"{path}/{key}")
        return out
    if kind == "array":
        return [_skeleton(schema, node.get("items", {}), f"{path}/0")
                for _ in range(node.get("minItems", 0))]
    if kind in ("integer", "number"):
        low = node.get("minimum", 0)
        if node.get("exclusiveMinimum") is True:
            low += 1
        return int(low) if kind == "integer" else low
    if kind == "boolean":
        return False
    return _sample_string(node, path)


def _sample_string(node: dict, path: str) -> str:
    pattern = node.get("pattern")
    maximum = node.get("maxLength", 120)
    if pattern is None or pattern == _UNCONSTRAINED_PATTERN:
        return f"SYNTHETIC {path.rsplit('/', 1)[-1].upper()}"[:maximum]
    if pattern in _PATTERN_SAMPLES:
        return _PATTERN_SAMPLES[pattern]
    for candidate in pattern.split("|"):
        candidate = candidate.strip("()^$")
        if _LITERAL_PATTERN.fullmatch(candidate):
            return candidate[:maximum]
    raise SchemaShapeError(
        f"{path}: required, and its pattern {pattern!r} is not one this script knows how "
        f"to satisfy. Add it to _PATTERN_SAMPLES rather than letting the base return go "
        f"out invalid."
    )


def _set_path(document: dict, path: str, value) -> None:
    node = document
    parts = path.split("/")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


# ---------------------------------------------------------------- driving the build

def run_build(work_dir: str, out_path: str, year: int, price_cache: str,
              merge_into: str = "") -> None:
    command = [sys.executable, "-m", "itrprep.cli", "build",
               "--year", str(year), "--work", work_dir, "--out", out_path,
               "--price-cache", price_cache, "--offline"]
    if merge_into:
        command += ["--merge-into", merge_into]
    print(f"\n$ {' '.join(command)}\n")
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise SystemExit(f"build failed with exit code {result.returncode}")
    if "Schema validation PASSED" not in result.stdout:
        raise SystemExit(
            "the build did not report a passing schema validation. The ITD ITR-2 schema "
            "has to be in schemas/ for this kit to mean anything -- see schemas/README.md."
        )
    expected_scope = "full ITR document" if merge_into else "ScheduleFA subtree"
    if expected_scope not in result.stdout:
        raise SystemExit(f"expected the build to validate the {expected_scope}")


# ---------------------------------------------------------------- reading it back

def schedule_fa_of(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["ITR"]["ITR2"]["ScheduleFA"]


def verify(partial_path: str, complete_path: str, rows: int) -> tuple[list[dict], list[dict]]:
    """Check the files themselves, rather than trusting what wrote them.

    Everything the checklist tells a person to look for on the Mac is asserted here first, so
    the checklist can never end up quoting an answer the kit does not actually produce.
    """
    partial = schedule_fa_of(partial_path)
    complete = schedule_fa_of(complete_path)
    a3 = partial["DtlsForeignEquityDebtInterest"]
    a2 = partial["DtlsForeignCustodialAcc"]

    problems = []
    if len(a3) != rows:
        problems.append(f"{partial_path}: Table A3 has {len(a3)} rows, expected {rows}")
    if len(a2) != len(ACCOUNTS):
        problems.append(f"{partial_path}: Table A2 has {len(a2)} rows, "
                        f"expected {len(ACCOUNTS)}")
    if complete != partial:
        problems.append("the two files disagree about Schedule FA; they must not, or the "
                        "two import attempts are not testing the same thing")

    previous_date = ""
    for index, row in enumerate(a3, start=1):
        if not row["NameOfEntity"].startswith(f"ROW {index:03d} OF {rows}"):
            problems.append(f"row {index} is out of sequence: {row['NameOfEntity']!r}")
        if row["ZipCode"] != entity_zip(index):
            problems.append(f"row {index} zip is {row['ZipCode']!r}, "
                            f"expected {entity_zip(index)!r}")
        if row["InterestAcquiringDate"] <= previous_date:
            problems.append(f"row {index} acquisition date {row['InterestAcquiringDate']} "
                            f"does not follow {previous_date}")
        previous_date = row["InterestAcquiringDate"]
        if row["PeakBalanceDuringPeriod"] <= row["ClosingBalance"]:
            problems.append(f"row {index} peak {row['PeakBalanceDuringPeriod']} does not "
                            f"exceed its closing {row['ClosingBalance']}")

    expected_sold = len([r for r in SOLD_ROWS if r <= rows])
    for label, got, want in (
        ("rows crediting a gross amount",
         sum(1 for r in a3 if r["TotGrossAmtPaidCredited"]), rows // DIVIDEND_EVERY),
        ("rows with gross proceeds",
         sum(1 for r in a3 if r["TotGrossProceeds"]), expected_sold),
        ("rows with a nil closing balance",
         sum(1 for r in a3 if not r["ClosingBalance"]), expected_sold),
    ):
        if got != want:
            problems.append(f"{label}: {got}, expected {want}")

    with open(complete_path, encoding="utf-8") as fh:
        blocks = set(json.load(fh)["ITR"]["ITR2"])
    missing = {"CreationInfo", "Form_ITR2", "PartA_GEN1", "ScheduleCYLA", "ScheduleBFLA",
               "PartB-TI", "PartB_TTI", "Verification"} - blocks
    if missing:
        problems.append(f"{complete_path} is not a complete return; missing "
                        f"{', '.join(sorted(missing))}")

    if problems:
        for problem in problems:
            print(f"  FAIL {problem}", file=sys.stderr)
        raise SystemExit("the generated files are not what the checklist claims")
    return a3, a2


def write_expected(path: str, a3: list[dict], a2: list[dict], year: int,
                   partial_path: str, complete_path: str) -> None:
    lines = [
        f"Schedule FA import test for calendar {year} -- read back from the generated files",
        "",
        f"  partial document  : {os.path.relpath(partial_path, ROOT)}",
        f"  complete return   : {os.path.relpath(complete_path, ROOT)}",
        f"  Table A3 rows     : {len(a3)}",
        f"  Table A2 rows     : {len(a2)}",
        "",
        "First Table A3 row:",
        json.dumps(a3[0], indent=2),
        "",
        "Last Table A3 row:",
        json.dumps(a3[-1], indent=2),
        "",
        f"Rows with a non-zero TotGrossAmtPaidCredited: "
        f"{sum(1 for r in a3 if r['TotGrossAmtPaidCredited'])}",
        f"Rows with a non-zero TotGrossProceeds       : "
        f"{sum(1 for r in a3 if r['TotGrossProceeds'])}",
        f"Rows with a nil ClosingBalance              : "
        f"{sum(1 for r in a3 if not r['ClosingBalance'])}",
        f"Rows whose peak exceeds their closing       : "
        f"{sum(1 for r in a3 if r['PeakBalanceDuringPeriod'] > r['ClosingBalance'])}",
        "",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                        help="gitignored directory to write the kit into")
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS,
                        help="Table A3 rows to generate")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR,
                        help="reporting calendar year")
    args = parser.parse_args()

    if args.rows > ACCOUNTS[-1][2]:
        raise SystemExit(f"--rows above {ACCOUNTS[-1][2]} needs another entry in ACCOUNTS")

    work_dir = os.path.join(args.out_dir, "work")
    out_dir = os.path.join(args.out_dir, "out")
    price_cache = os.path.join(args.out_dir, "price-cache")
    for directory in (work_dir, out_dir, price_cache):
        os.makedirs(directory, exist_ok=True)

    print(f"Writing {args.rows} synthetic Table A3 rows into {work_dir}")
    write_inputs(work_dir, args.rows, args.year)

    schema, schema_path = validate.load_schema(year=args.year)
    print(f"Building the complete-return base against {schema_path}")
    base = build_base_return(schema)
    errors = validate.validate_full_document(base, schema)
    if errors:
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        raise SystemExit("the complete-return base does not validate; refusing to ship it")
    base_path = os.path.join(args.out_dir, "base_return.json")
    with open(base_path, "w", encoding="utf-8") as fh:
        json.dump(base, fh, indent=1)
        fh.write("\n")

    partial_path = os.path.join(out_dir, f"schedule_fa_{args.year}.json")
    complete_path = os.path.join(out_dir, f"complete_return_{args.year}.json")
    run_build(work_dir, partial_path, args.year, price_cache)
    run_build(work_dir, complete_path, args.year, price_cache, merge_into=base_path)

    print("\n" + "=" * 78)
    a3, a2 = verify(partial_path, complete_path, args.rows)
    write_expected(os.path.join(args.out_dir, "EXPECTED.txt"), a3, a2, args.year,
                   partial_path, complete_path)
    print("=" * 78)
    print("Both shapes generated, validated and read back. Next: "
          "docs/MACOS_UTILITY_TEST.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
