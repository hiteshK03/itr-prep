"""Build a minimal but genuinely valid XLSX fixture, using only the stdlib.

Needed because the XLSX reader in `adapters` has to be tested against a real file, and
writing one by hand is the only way to do that without adding openpyxl as a dependency.

The point of interest is the date column: Excel stores a date as a day count from
1899-12-30 with a number format applied, so a reader that ignores styles produces `45107`
where the export said `2023-06-30`. This fixture stores its dates that way on purpose.

`build_workbook` writes as many worksheets as it is given, because a real stock-plan
export is a workbook and not a sheet -- an E*TRADE "By Benefit Type" download puts ESPP
purchases on one tab and restricted stock on another -- and a reader that stops at the
first tab loses whole vests without saying so. Sheets can be marked hidden, which is the
other way a tab goes unnoticed.

Run:  .venv/bin/python tests/make_xlsx_fixture.py <out.xlsx>
"""

from __future__ import annotations

import datetime as dt
import sys
import zipfile

EPOCH = dt.date(1899, 12, 30)

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

# cellXfs index 0 = general, index 1 = numFmtId 14 (built-in short date).
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="0"/>
<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="1"><fill><patternFill patternType="none"/></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs>
</styleSheet>"""

# Deliberately mirrors a real INDmoney export: a preamble above the header, distinctive
# "(USD)" column names, and dates stored as serials.
ROWS = [
    ["INDmoney US Stocks - Transaction Report", "", "", "", "", ""],
    ["Generated on 2026-01-10", "", "", "", "", ""],
    [],
    ["Date", "Stock Name", "Type", "Quantity", "Price (USD)", "Amount (USD)"],
    [dt.date(2025, 1, 8), "IVV", "Buy", "12", "592.19", "7106.28"],
    [dt.date(2025, 3, 27), "IVV", "Dividend", "0", "0", "19.44"],
    [dt.date(2025, 6, 17), "IVV", "Buy", "14", "598.76", "8382.64"],
    [dt.date(2025, 10, 15), "IVV", "Sell", "20", "668.28", "13365.60"],
]


def _col(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def build(path: str) -> None:
    """The single-sheet INDmoney fixture."""
    build_workbook(path, [("History", ROWS)])


def build_workbook(path: str, sheets, hidden=()) -> None:
    """Write one workbook holding `sheets`, a list of (sheet name, rows).

    `hidden` names the sheets to mark hidden. A hidden sheet is still a sheet: the reader
    must report it rather than quietly leave its rows out.
    """
    strings: list[str] = []

    def intern(value: str) -> int:
        if value not in strings:
            strings.append(value)
        return strings.index(value)

    sheet_parts: list[str] = []
    for _name, rows in sheets:
        sheet_rows = []
        for row_index, row in enumerate(rows, start=1):
            cells = []
            for col_index, value in enumerate(row):
                ref = f"{_col(col_index)}{row_index}"
                if value == "":
                    continue
                if isinstance(value, dt.date):
                    serial = (value - EPOCH).days
                    cells.append(f'<c r="{ref}" s="1"><v>{serial}</v></c>')
                else:
                    cells.append(
                        f'<c r="{ref}" t="s"><v>{intern(str(value))}</v></c>'
                    )
            sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
        sheet_parts.append(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
        )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        + "".join(
            f'<sheet name="{_esc(name)}" sheetId="{i}" r:id="rId{i}"'
            + (' state="hidden"' if name in hidden else "")
            + "/>"
            for i, (name, _rows) in enumerate(sheets, start=1)
        )
        + "</sheets></workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" '
            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        + f'<Relationship Id="rId{len(sheets) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        f'<Relationship Id="rId{len(sheets) + 2}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
        'Target="sharedStrings.xml"/>'
        "</Relationships>"
    )
    shared = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(strings)}" uniqueCount="{len(strings)}">'
        + "".join(f"<si><t>{_esc(s)}</t></si>" for s in strings)
        + "</sst>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", STYLES)
        archive.writestr("xl/sharedStrings.xml", shared)
        for index, part in enumerate(sheet_parts, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", part)


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/tmp/indmoney_fixture.xlsx"
    build(target)
    print(f"wrote {target}")
