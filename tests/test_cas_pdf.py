"""The CAS transcriber, validated against a synthetic statement PDF.

The real-statement layout was verified against a single CDSL Consolidated Account
Statement fetched as a layout reference on 25 August 2026; that file stays outside
the repo. Everything in THIS test is invented at runtime: the test generates a
small CAS-shaped PDF with PyMuPDF (the same layout grammar -- banner, folio summary,
"<code GZ> - name" headers, "ISIN :" lines, labels above date rows, STT rows, a
demat-equity noise section) and checks the transcriber against hand-written
expectations.

Run:  .venv/bin/python tests/test_cas_pdf.py
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import cas_pdf

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


# ---------------------------------------------------------------------------
# Synthetic CAS PDF builder
# ---------------------------------------------------------------------------

EQ_ISIN = "INF123F01234"   # equity-oriented index fund
GD_ISIN = "INF123F01235"   # gold fund -> debt classification
MY_ISIN = "INF123F01236"   # mystery fund -> unknown classification


def build_synthetic_cas(path: str, password: str | None = None) -> None:
    """Write a one-page CAS-shaped PDF carrying only invented figures."""
    import pymupdf

    doc = pymupdf.open()  # empty document
    page = doc.new_page(width=595, height=842)

    def line(y: float, words: list[tuple[float, str]]) -> None:
        for x, word in words:
            page.insert_text((x, y), word, fontsize=9)

    # Banner + statement period
    line(100, [(86, "CONSOLIDATED"), (175, "ACCOUNT"), (232, "STATEMENT"),
               (299, "(CAS)"), (329, "FOR"), (354, "SECURITIES"),
               (419, "HELD"), (451, "IN"), (466, "DEMAT")])
    line(114, [(174, "FORM"), (209, "AND"), (236, "INVESTMENTS"),
               (316, "IN"), (330, "MUTUAL"), (379, "FUNDS")])
    line(140, [(100, "STATEMENT"), (160, "OF"), (176, "TRANSACTIONS"),
               (256, "FOR"), (278, "THE"), (300, "PERIOD"), (340, "FROM"),
               (372, "01-04-2025"), (430, "TO"), (445, "31-03-2026")])

    # Folio summary section (front of statement): Scheme Name / ISIN pairs
    line(165, [(24, "Scheme"), (61, "Name"), (89, ":"), (94, "SYNTH"),
               (126, "NIFTY"), (149, "INDEX"), (186, "FUND"),
               (360, "Scheme"), (397, "Code"), (422, ":"), (427, "916GZ")])
    line(180, [(26, "ISIN"), (45, ":"), (49, EQ_ISIN),
               (210, "UCC"), (232, ":"), (360, "RTA"), (380, ":"), (385, "CAMS")])
    line(200, [(24, "Scheme"), (61, "Name"), (89, ":"), (94, "SYNTH"),
               (126, "GOLD"), (149, "SAVINGS"), (186, "FUND")])
    line(215, [(26, "ISIN"), (45, ":"), (49, GD_ISIN), (210, "UCC"), (232, ":")])
    line(235, [(24, "Scheme"), (61, "Name"), (89, ":"), (94, "SYNTH"),
               (126, "SPECIAL"), (155, "OPPORTUNITIES"), (230, "FUND")])
    line(250, [(26, "ISIN"), (45, ":"), (49, MY_ISIN), (210, "UCC"), (232, ":")])

    # ---- Scheme A transaction table (equity index fund) ----
    line(290, [(27, "916GZ"), (56, "-"), (61, "SYNTH"), (90, "NIFTY"),
               (111, "INDEX"), (128, "FUND"), (145, "DIRECT"), (187, "GROWTH")])
    line(305, [(26, "ISIN"), (45, ":"), (49, EQ_ISIN), (316, "UCC"), (336, ":")])
    line(325, [(39, "Date"), (82, "Transaction"), (137, "Description"),
               (200, "Amount"), (238, "(`)"), (269, "NAV"), (290, "(`)"),
               (327, "Price"), (352, "(`)"), (396, "Units")])
    line(345, [(76, "Opening"), (113, "Balance"), (400, "100.000")])
    line(360, [(76, "Purchase")])
    line(375, [(26, "05-04-2025"), (76, "SYNTH"), (105, "REF"),
               (220, "5,000.00"), (280, "50.0000"), (340, "50.0000"),
               (400, "100.000")])
    line(383, [(76, "700001234")])
    line(398, [(76, "Switch"), (105, "In"), (114, "-"), (119, "From"),
               (142, "SYNTH"), (165, "GOLD")])
    line(413, [(26, "15-06-2025"), (76, "SAVINGS"), (110, "FUND"),
               (220, "2,750.00"), (280, "55.0000"), (340, "55.0000"),
               (400, "50.000")])
    line(428, [(76, "Switch-Out"), (127, "-"), (132, "To"), (139, "SYNTH"),
               (162, "GOLD")])
    line(443, [(26, "10-10-2025"), (76, "SAVINGS"), (98, "FUND"),
               (212, "-6,000.00"), (280, "60.0000"), (340, "60.0000"),
               (402, "-100.000")])
    line(451, [(76, "STT"), (241, "6.00")])
    line(466, [(76, "Closing"), (108, "Balance"), (400, "150.000")])

    # ---- Scheme B transaction table (gold fund: redemption only) ----
    line(500, [(27, "917GZ"), (56, "-"), (61, "SYNTH"), (90, "GOLD"),
               (111, "SAVINGS"), (145, "FUND"), (166, "GROWTH")])
    line(515, [(26, "ISIN"), (45, ":"), (49, GD_ISIN), (316, "UCC"), (336, ":")])
    line(530, [(39, "Date"), (82, "Transaction"), (137, "Description"),
               (200, "Amount"), (238, "(`)"), (269, "NAV"), (290, "(`)"),
               (327, "Price"), (352, "(`)"), (396, "Units")])
    line(550, [(76, "Opening"), (113, "Balance"), (400, "100.000")])
    line(565, [(76, "Redemption")])
    line(580, [(26, "20-01-2026"), (76, "SYNTH"), (105, "REF"),
               (212, "-3,600.00"), (280, "36.0000"), (340, "36.0000"),
               (402, "-100.000")])
    line(595, [(76, "Closing"), (108, "Balance"), (400, "0.000")])

    # Demat equity noise: a date row outside any MF transaction table. The
    # banner closes the table first, so this row must NOT be transcribed.
    line(630, [(201, "HOLDING"), (251, "STATEMENT"), (311, "AS"), (326, "ON"),
               (344, "31-03-2026")])
    line(660, [(22, "INE123H01000"), (102, "VIPUL"), (129, "LIMITED"),
               (166, "-"), (171, "NEW"), (194, "EQUITY")])
    line(675, [(26, "01-05-2025"), (76, "SHARES"), (220, "1,000.00"),
               (400, "100.000")])

    if password is not None:
        import pymupdf as fitz
        doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="OWNERONLY", user_pw=password)
    else:
        doc.save(path)
    doc.close()


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def main() -> int:
    tmp = tempfile.mkdtemp(prefix="cas_test_")
    plain = os.path.join(tmp, "synthetic_cas.pdf")
    locked = os.path.join(tmp, "locked_cas.pdf")

    print("\ncas transcriber: synthetic plain statement")
    build_synthetic_cas(plain)
    tx = cas_pdf.transcribe_cas(plain)

    check("statement period parsed",
          tx.period_from == dt.date(2025, 4, 1) and tx.period_to == dt.date(2026, 3, 31),
          f"got {tx.period_from}..{tx.period_to}")

    schemes = {s.isin: s for s in tx.schemes}
    check("three schemes after ISIN dedupe", len(tx.schemes) == 3,
          f"got {len(tx.schemes)}: {[s.isin for s in tx.schemes]}")
    eq = schemes.get(EQ_ISIN)
    check("equity index fund named from summary or header",
          eq is not None and "SYNTH" in eq.name,
          eq.name if eq is not None else "missing")
    check("index fund classified equity_oriented",
          eq is not None and eq.classification == "equity_oriented",
          eq.classification if eq is not None else "missing")
    gd = schemes.get(GD_ISIN)
    check("gold fund classified other (engine vocabulary)",
          gd is not None and gd.classification == "other",
          gd.classification if gd is not None else "missing")
    my = schemes.get(MY_ISIN)
    check("mystery fund left unclassified",
          my is not None and my.classification == "",
          my.classification if my is not None else "missing")

    by_kind: dict[str, list] = {}
    for r in tx.transactions:
        by_kind.setdefault(r.kind, []).append(r)
    check("one purchase", len(by_kind.get("purchase", [])) == 1)
    check("one switch_in", len(by_kind.get("switch_in", [])) == 1)
    check("one switch_out", len(by_kind.get("switch_out", [])) == 1)
    check("one redemption", len(by_kind.get("redemption", [])) == 1)
    check("four transactions total (demat noise excluded)",
          len(tx.transactions) == 4, f"got {len(tx.transactions)}")

    purchase = by_kind["purchase"][0]
    check("purchase units/NAV transcribed",
          purchase.units == Decimal("100.000") and purchase.nav == Decimal("50.0000"),
          f"units={purchase.units} nav={purchase.nav}")
    check("purchase carries its transaction reference",
          purchase.ref == "700001234", f"ref={purchase.ref!r}")

    switch_out = by_kind["switch_out"][0]
    check("switch-out units/NAV negative in source, preserved",
          switch_out.units == Decimal("-100.000") and switch_out.nav == Decimal("60.0000"),
          f"units={switch_out.units} nav={switch_out.nav}")
    check("STT attached to the switch-out as transfer_expense",
          switch_out.transfer_expense == Decimal("6.00"),
          f"expense={switch_out.transfer_expense}")

    redemption = by_kind["redemption"][0]
    check("redemption has no STT attached",
          redemption.transfer_expense == Decimal("0"))
    check("first-transaction-is-sale warning fired for the gold fund",
          any(GD_ISIN in w and "held before" in w for w in tx.warnings),
          str(tx.warnings))
    check("closing-balance sanity warnings present",
          any("closing balance" in w.lower() for w in tx.warnings))

    print("\ncas transcriber: CSV output")
    schemes_path, txns_path = cas_pdf.write_csvs(tx, tmp)
    import csv
    with open(txns_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    check("CSV header matches the pipeline contract",
          rows[0] == cas_pdf.TXN_CSV_COLUMNS, str(rows[0]))
    check("four data rows", len(rows) == 5, f"got {len(rows) - 1}")
    sale_row = [r for r in rows[1:] if r[1] == "sale" and r[0] == EQ_ISIN][0]
    check("sale units written positive", sale_row[3] == "100.000", sale_row[3])
    check("sale price written positive", sale_row[4] == "60.0000", sale_row[4])
    check("STT landed in transfer_expense column", sale_row[5] == "6.00", sale_row[5])

    with open(schemes_path, newline="", encoding="utf-8") as fh:
        srows = list(csv.reader(fh))
    check("schemes CSV carries the inferred classification",
          any(r[0] == EQ_ISIN and r[2] == "equity_oriented" for r in srows[1:]))

    # Second write must back up, not destroy, the first.
    cas_pdf.write_csvs(tx, tmp)
    check("existing CSVs backed up on rewrite",
          os.path.exists(txns_path + ".bak") and os.path.exists(schemes_path + ".bak"))

    print("\ncas transcriber: encrypted statement")
    build_synthetic_cas(locked, password="TESTPAN12345")
    tx2 = cas_pdf.transcribe_cas(locked, password="TESTPAN12345")
    check("correct password opens the statement", len(tx2.schemes) == 3)
    refuses_wrong_password = False
    try:
        cas_pdf.transcribe_cas(locked, password="WRONGPAN99999")
    except cas_pdf.CasError:
        refuses_wrong_password = True
    check("wrong password refused with CasError", refuses_wrong_password)

    refuses_missing = False
    try:
        cas_pdf.transcribe_cas(os.path.join(tmp, "does_not_exist.pdf"))
    except cas_pdf.CasError:
        refuses_missing = True
    check("missing file refused with CasError", refuses_missing)

    print()
    if failures:
        print(f"FAILED: {len(failures)} cas_pdf check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All cas_pdf checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
