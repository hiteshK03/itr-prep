"""Verify what actually landed in the Excel utility against what we meant to send.

This exists because `ImportScheduleFA` runs its whole body under `On Error Resume Next`.
A wrong type, a locked cell, a row beyond the pre-sized block: all of them are swallowed and
the sub returns normally. So a successful-looking import proves nothing, and the runbook's
answer until now was to ask a person to eyeball a spreadsheet at the end of a long day.

The verification is deliberately total rather than sampled. The failure this guards against
is not "the importer is broken" -- it demonstrably works -- but "this particular run dropped
row 19", which sampling two rows cannot see.

Kept free of COM so it can be tested against a recorded dump. The PowerShell driver's only
job is to read cells and write them out; every judgement happens here.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

# Named range -> JSON key, for the two tables this tool writes.
A3_TEXT_FIELDS = {
    "FA_A3_BankName": "NameOfEntity",
    "FA_A3_BankAdd": "AddressOfEntity",
    "FA_A3_NatureOfEntity": "NatureOfEntity",
}
A3_ZIP_FIELD = "FA_A3_ZipCode"
A3_MONEY_FIELDS = {
    "FA_A3_initialvalue": "InitialValOfInvstmnt",
    "FA_A3_PeakBal": "PeakBalanceDuringPeriod",
    "FA_A3_ClosingBal": "ClosingBalance",
    "FA_A3_Totalgrossamount": "TotGrossAmtPaidCredited",
    "FA_A3_Totalgrosproceeds": "TotGrossProceeds",
}
A3_DATE_FIELDS = {"FA_A3_AccOpeningDate": "InterestAcquiringDate"}

A2_TEXT_FIELDS = {
    "FA_A2_BankName": "FinancialInstName",
    "FA_A2_BankAdd": "FinancialInstAddress",
    "FA_A2_ForeignAccountNumber": "AccountNumber",
    "FA_A2_StatusBeneficiary": "Status",
}

# The JSON carries a one-letter nature-of-amount code and the sheet shows the label the
# utility expands it to. Transcribed from the importer's own If/ElseIf chain, so a sheet
# showing anything else means the code did not resolve.
A2_NATURE_LABELS = {
    "I": "Interest",
    "D": "Dividend",
    "S": "Proceeds from sale or redemption of financial assets",
    "O": "Other income",
    "N": "No Amount paid/credited",
}
A2_MONEY_FIELDS = {
    "FA_A2_PeakBal": "PeakBalanceDuringPeriod",
    "FA_A2_ClosingBal": "ClosingBalance",
    "FA_A2_Grossinterest": "GrossAmtPaidCredited",
}
A2_DATE_FIELDS = {"FA_A2_AccOpeningDate": "AccOpenDate"}
A2_ZIP_FIELD = "FA_A2_ZipCode"

# The utility's country dropdown stores "<code>-<NAME>". Anything else means the code did
# not resolve, and a Schedule FA row whose country is blank or "2-" fails validation at the
# portal rather than here.
COUNTRY_CELL = re.compile(r"^(\d+)\s*-\s*(.+)$")

DATE_CELL = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


@dataclass
class Mismatch:
    table: str
    row: int
    field: str
    expected: str
    got: str
    note: str = ""


@dataclass
class VerifyReport:
    checks: list[str] = field(default_factory=list)
    mismatches: list[Mismatch] = field(default_factory=list)
    fatal: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.mismatches and not self.fatal

    def ok(self, message: str) -> None:
        self.checks.append(message)

    def fail(self, *args, **kwargs) -> None:
        self.mismatches.append(Mismatch(*args, **kwargs))


def verify(dump: dict, expected: dict, audit_path: str = "") -> VerifyReport:
    """Compare a cell dump against the JSON that was imported.

    `dump` is what the PowerShell driver wrote: cell text and raw value for every named
    column, row by row. `expected` is the full generated JSON. `audit_path` closes the loop
    back to the CSV the numbers were computed in, so the whole chain is checked and not just
    its last link.
    """
    report = VerifyReport()
    fa = (expected.get("ITR", {}).get("ITR2", {}).get("ScheduleFA")
          or expected.get("ScheduleFA") or {})
    if not fa:
        report.fatal.append("the JSON has no ScheduleFA node to compare against")
        return report

    _check_aoi_flag(dump, report)

    _check_table(
        report, dump.get("a3") or {}, fa.get("DtlsForeignEquityDebtInterest") or [],
        table="A3", country_field="FA_A3_Country",
        text_fields=A3_TEXT_FIELDS, money_fields=A3_MONEY_FIELDS,
        date_fields=A3_DATE_FIELDS, zip_field=A3_ZIP_FIELD,
    )
    _check_table(
        report, dump.get("a2") or {}, fa.get("DtlsForeignCustodialAcc") or [],
        table="A2", country_field="FA_A2_Country",
        text_fields=A2_TEXT_FIELDS, money_fields=A2_MONEY_FIELDS,
        date_fields=A2_DATE_FIELDS, zip_field=A2_ZIP_FIELD,
    )

    if audit_path:
        _check_against_audit(report, fa, audit_path)
    return report


def _check_aoi_flag(dump, report) -> None:
    """Validation rule 746 rejects a return with Schedule FA data unless item 19 is Yes."""
    flag = str(dump.get("aoi_flag", "")).strip()
    if flag.lower() == "yes":
        report.ok('Part B-TTI item 19 (resident holding foreign assets) = "Yes"')
    else:
        report.fail(
            "PartB-TTI", 19, "AOIFlag_1", "Yes", flag or "(blank)",
            "the utility rejects a return carrying Schedule FA rows unless this is Yes",
        )


def _check_table(report, dump_table, expected_rows, *, table, country_field,
                 text_fields, money_fields, date_fields, zip_field="") -> None:
    got_rows = dump_table.get("rows") or []
    want = len(expected_rows)

    if want == 0:
        if _populated(got_rows):
            report.fatal.append(
                f"Table {table} has populated rows in the sheet but none in the JSON"
            )
        else:
            report.ok(f"Table {table}: nothing to import, nothing present")
        return

    populated = _populated(got_rows)
    if len(populated) != want:
        report.fail(
            table, 0, "row count", str(want), str(len(populated)),
            "a short count is the importer silently dropping rows -- usually the block "
            "in the sheet is smaller than the JSON. Re-import into a fresh copy; if it "
            "recurs, add rows to the table first (AddRows_A3_FA3).",
        )
    else:
        report.ok(f"Table {table}: {want} row(s) imported, count matches")

    # The last row is where truncation shows, so it is checked explicitly and by name
    # rather than being merely one of the rows in the loop below.
    if populated:
        last_got = populated[-1]
        if not _text(last_got, country_field):
            report.fail(
                table, want, "last row", "populated", "blank",
                "the final row is empty, which is what a truncated import looks like",
            )
        else:
            report.ok(
                f"Table {table}: final row (#{want}) is populated "
                f"[{_text(last_got, next(iter(text_fields)))[:28]}]"
            )

    for index, (want_row, got_row) in enumerate(zip(expected_rows, populated), start=1):
        _check_country(report, table, index, got_row, country_field, want_row)

        for cell_name, json_key in text_fields.items():
            expected_text = str(want_row.get(json_key, "") or "")
            got_text = _text(got_row, cell_name)
            if _norm_text(got_text) != _norm_text(expected_text):
                report.fail(table, index, cell_name, expected_text, got_text)

        for cell_name, json_key in date_fields.items():
            _check_date(report, table, index, got_row, cell_name,
                        str(want_row.get(json_key, "") or ""))

        for cell_name, json_key in money_fields.items():
            _check_money(report, table, index, got_row, cell_name,
                         want_row.get(json_key))

        if zip_field:
            _check_zip(report, table, index, got_row, zip_field,
                       str(want_row.get("ZipCode", "") or ""))

        if table == "A2":
            _check_nature(report, index, got_row, want_row)

    if not [m for m in report.mismatches if m.table == table]:
        report.ok(
            f"Table {table}: every text, date and rupee figure in all {want} row(s) "
            f"matches the JSON exactly"
        )


def _check_country(report, table, index, got_row, field_name, want_row) -> None:
    text = _text(got_row, field_name)
    code = str(want_row.get("CountryCodeExcludingIndia", "") or "")
    name = str(want_row.get("CountryName", "") or "")
    match = COUNTRY_CELL.match(text.strip())
    if not match:
        report.fail(
            table, index, field_name, f"{code}-{name}", text or "(blank)",
            "the country cell must render as code-NAME; a bare code or a blank means "
            "the dropdown did not resolve and the portal will reject the row",
        )
        return
    got_code, got_name = match.group(1), match.group(2).strip()
    if got_code != code or _norm_text(got_name) != _norm_text(name):
        report.fail(table, index, field_name, f"{code}-{name}", text)


def _check_zip(report, table, index, got_row, field_name, expected) -> None:
    """Zip codes get their own check because of the leading-zero defect.

    The utility's zip cell is number-formatted, so a US zip that begins with a zero is
    stored as a number and loses it: Boston's 02210 becomes 2210, Jersey City's 07306
    becomes 7306. Nothing warns you, and the utility then generates that wrong zip into
    the JSON you upload. Roughly a tenth of US zips start with a zero -- the whole of New
    England plus NJ, NY and PR -- so this is not a corner case.
    """
    got = _text(got_row, field_name).strip()
    expected = expected.strip()
    if _norm_text(got) == _norm_text(expected):
        return
    if expected.startswith("0") and got == expected.lstrip("0"):
        report.fail(
            table, index, field_name, expected, got,
            "leading zero stripped: the cell is number-formatted, so this zip was "
            "stored as a number. Re-run the import (it repairs these automatically), or "
            "format the cell as Text and retype the zip.",
        )
        return
    report.fail(table, index, field_name, expected or "(blank)", got or "(blank)")


def _check_nature(report, index, got_row, want_row) -> None:
    code = str(want_row.get("NatureOfAmount", "") or "").strip().upper()
    got = _text(got_row, "FA_A2_Grossinterest_Nature")
    if not code:
        return
    want_label = A2_NATURE_LABELS.get(code)
    if want_label is None:
        report.fail(
            "A2", index, "FA_A2_Grossinterest_Nature",
            f"code {code}", got,
            "the JSON uses a nature-of-amount code the utility does not recognise; "
            f"valid codes are {', '.join(sorted(A2_NATURE_LABELS))}",
        )
        return
    if _norm_text(got) != _norm_text(want_label):
        report.fail(
            "A2", index, "FA_A2_Grossinterest_Nature", want_label, got or "(blank)",
            f"code {code!r} should have expanded to this label",
        )


def _check_date(report, table, index, got_row, field_name, expected_iso) -> None:
    text = _text(got_row, field_name).strip()
    if not expected_iso:
        if text:
            report.fail(table, index, field_name, "(blank)", text)
        return
    try:
        want = dt.date.fromisoformat(expected_iso[:10])
    except ValueError:
        report.fail(table, index, field_name, expected_iso, text,
                    "the JSON date is not ISO, which is a generator bug")
        return
    match = DATE_CELL.match(text)
    if not match:
        report.fail(
            table, index, field_name, want.strftime("%d/%m/%Y"), text or "(blank)",
            "the cell must render as DD/MM/YYYY. A serial number here means the cell "
            "took a raw value instead of a date, and MM/DD/YYYY means the wrong locale "
            "-- either silently changes what you filed.",
        )
        return
    day, month, year = (int(g) for g in match.groups())
    if (year, month, day) != (want.year, want.month, want.day):
        report.fail(table, index, field_name, want.strftime("%d/%m/%Y"), text)


def _check_money(report, table, index, got_row, field_name, expected_value) -> None:
    want = _to_decimal(expected_value)
    got = _to_decimal(_value(got_row, field_name))
    if got is None:
        got = _to_decimal(_text(got_row, field_name))
    if want is None:
        return
    if got is None:
        report.fail(
            table, index, field_name, _rupees(want),
            _text(got_row, field_name) or "(blank)",
            "the cell holds no number at all",
        )
        return
    if got != want:
        report.fail(
            table, index, field_name, _rupees(want), _rupees(got),
            f"off by {_rupees(got - want)}",
        )


def _check_against_audit(report, fa, audit_path) -> None:
    """Close the loop: the rupee totals in the JSON must equal the audit CSV's own sums.

    Verifying the sheet against the JSON proves the import. This proves the JSON, so a
    mistake anywhere between the per-lot computation and the spreadsheet is caught.
    """
    try:
        with open(audit_path, newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if (r.get("ticker") or "").strip()]
    except OSError as exc:
        report.fatal.append(f"could not read the audit CSV {audit_path}: {exc}")
        return
    if not rows:
        report.ok("audit CSV has no lot rows to cross-check")
        return

    a3 = fa.get("DtlsForeignEquityDebtInterest") or []
    pairs = [
        ("peak_value_inr", "PeakBalanceDuringPeriod", "A3 peak"),
        ("closing_value_inr", "ClosingBalance", "A3 closing"),
        ("initial_value_inr", "InitialValOfInvstmnt", "A3 initial"),
        ("gross_proceeds_inr", "TotGrossProceeds", "A3 proceeds"),
        ("gross_credited_inr", "TotGrossAmtPaidCredited", "A3 dividends"),
    ]
    if len(rows) != len(a3):
        report.fail(
            "audit", 0, "lot count", str(len(rows)), str(len(a3)),
            f"{audit_path} has {len(rows)} lot rows but the JSON has {len(a3)} A3 rows",
        )
        return
    for csv_col, json_key, label in pairs:
        csv_total = sum((_to_decimal(r.get(csv_col)) or Decimal(0)) for r in rows)
        json_total = sum((_to_decimal(r.get(json_key)) or Decimal(0)) for r in a3)
        if csv_total != json_total:
            report.fail("audit", 0, label, _rupees(csv_total), _rupees(json_total),
                        "the JSON disagrees with the audit trail it was built from")
    if not [m for m in report.mismatches if m.table == "audit"]:
        report.ok(
            f"audit trail: all {len(pairs)} rupee totals across {len(rows)} lot(s) "
            f"agree with the JSON"
        )


# -- helpers -----------------------------------------------------------------

def _populated(rows):
    """Rows the importer actually wrote, ignoring the sheet's trailing blank block.

    The tables ship pre-sized with more rows than are used, so the blank tail is normal and
    must not be counted. A blank row in the *middle* still shortens this list, which is what
    makes a dropped row visible as a count mismatch.
    """
    return [
        row for row in rows
        if any(str(cell.get("text", "")).strip() or str(cell.get("value", "")).strip()
               for cell in row.values() if isinstance(cell, dict))
    ]


def _text(row, field_name) -> str:
    cell = row.get(field_name) or {}
    return str(cell.get("text", "") or "")


def _value(row, field_name):
    cell = row.get(field_name) or {}
    return cell.get("value")


def _norm_text(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()


def _to_decimal(raw):
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return Decimal(str(raw)).quantize(Decimal(1))
    text = str(raw).strip()
    for ch in ",\u20b9 ":
        text = text.replace(ch, "")
    if not text:
        return None
    try:
        return Decimal(text).quantize(Decimal(1))
    except Exception:  # noqa: BLE001 -- unparseable is a legitimate answer here
        return None


def _rupees(value) -> str:
    if value is None:
        return "(none)"
    return f"{int(value):,}"


def render(report: VerifyReport, workbook: str = "") -> str:
    lines = [
        "=" * 78,
        "IMPORT READBACK VERIFICATION",
        "=" * 78,
    ]
    if workbook:
        lines.append(f"workbook: {workbook}")
    lines.append("")
    for check in report.checks:
        lines.append(f"  ok    {check}")
    if report.fatal:
        lines.append("")
        lines.append("FATAL:")
        for message in report.fatal:
            lines.append(f"  {message}")
    if report.mismatches:
        lines.append("")
        lines.append(f"MISMATCHES ({len(report.mismatches)}):")
        lines.append("")
        lines.append(f"  {'table':<6} {'row':>4} {'field':<26} "
                     f"{'expected':>16} {'in sheet':>16}")
        lines.append("  " + "-" * 74)
        for m in report.mismatches:
            lines.append(
                f"  {m.table:<6} {m.row:>4} {m.field:<26} "
                f"{m.expected[:16]:>16} {m.got[:16]:>16}"
            )
            if m.note:
                lines.append(f"         {m.note}")
    lines.append("")
    lines.append("=" * 78)
    if report.passed:
        lines.append("PASS -- every imported cell matches the generated JSON and the "
                     "audit trail.")
    else:
        lines.append(
            f"FAIL -- {len(report.mismatches)} mismatch(es), "
            f"{len(report.fatal)} fatal problem(s). Do NOT file this workbook. Start "
            "again from a fresh copy of the utility."
        )
    lines.append("=" * 78)
    return "\n".join(lines)
