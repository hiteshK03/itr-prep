"""Checks for the preflight command, the header sniffer and the import verifier.

The readback checks matter most. The verifier is the only thing standing between a silently
truncated Excel import and a filed return, and it is the one component that cannot be
exercised by running the pipeline -- it needs a cell dump from a real workbook. So the dumps
here are synthesised, including the exact failure shapes seen in practice: a dropped last
row, a stripped leading zero in a zip code, a country cell that did not resolve, and a date
that arrived as a serial number.

Run:  .venv/bin/python tests/test_doctor_readback.py
"""

from __future__ import annotations

import copy
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import adapters, doctor, intermediate, readback, scope, validate  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNTH = os.path.join(ROOT, "tests", "synthetic")
SPLIT_SYNTH = os.path.join(ROOT, "tests", "synthetic_split")
EXPORTS = os.path.join(SYNTH, "broker_exports")
FX_CACHE = os.path.join(ROOT, "data", "sbi_ttbuy_usd.csv")
PRICE_CACHE = os.path.join(ROOT, "data", "prices")
# The interpreter running this suite, not a guessed one. `.venv/bin/python` is a
# POSIX venv layout that does not exist on Windows and does not exist at all on a
# fresh clone, which is what CI is.
PYTHON = sys.executable

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
        failures.append(label)


def work_paths(work: str) -> dict:
    return {
        "transactions": os.path.join(work, "transactions.csv"),
        "issuers": os.path.join(work, "issuers.csv"),
        "accounts": os.path.join(work, "accounts.csv"),
        "cash": os.path.join(work, "cash_balances.csv"),
        "overrides": os.path.join(work, "prices_override.csv"),
    }


# -- doctor ------------------------------------------------------------------

def test_doctor_clean() -> None:
    print("\ndoctor: a good working directory")
    from itrprep.prices import PriceStore

    prices = PriceStore(PRICE_CACHE, offline=True)
    report = doctor.run_checks(
        work_paths(SYNTH), years=[2023, 2024, 2025], prices=prices,
        fx_cache=FX_CACHE, offline=True,
    )
    check("no errors on the synthetic dataset", not report.errors,
          "; ".join(f.message for f in report.errors))
    check("reports what it checked", len(report.checked) >= 8)
    check("render says READY TO BUILD",
          "READY TO BUILD" in doctor.render(report, SYNTH, [2023, 2024, 2025]))


def test_doctor_catches_example_rows() -> None:
    print("\ndoctor: untouched templates are a hard error")
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        subprocess.run([PYTHON, "-m", "itrprep.cli", "init", "--work", work],
                       cwd=ROOT, capture_output=True, check=True)
        from itrprep.prices import PriceStore

        report = doctor.run_checks(
            work_paths(work), years=[2025], prices=PriceStore(PRICE_CACHE, offline=True),
            fx_cache=FX_CACHE, offline=True,
        )
        example = [f for f in report.errors if f.category == "example rows"]
        check("example rows are an ERROR, not a warning", bool(example))
        check("the placeholder account number is named",
              any("REPLACE-WITH-REAL" in f.message for f in example))
        check("render says NOT READY",
              "NOT READY" in doctor.render(report, work, [2025]))


def test_doctor_catches_broken_references() -> None:
    print("\ndoctor: missing issuer and account rows")
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        shutil.copytree(SYNTH, work)
        # Strip CSCO from issuers.csv and rename one account, so both reference checks fire.
        issuers = os.path.join(work, "issuers.csv")
        with open(issuers) as fh:
            lines = fh.readlines()
        with open(issuers, "w") as fh:
            fh.writelines([ln for ln in lines if not ln.startswith("CSCO,")])
        accounts = os.path.join(work, "accounts.csv")
        text = open(accounts).read().replace("indmoney_us", "indmoney_typo")
        open(accounts, "w").write(text)

        report = doctor.run_checks(work_paths(work), years=[2025], prices=None,
                                   fx_cache=FX_CACHE, offline=True)
        messages = " | ".join(f.message for f in report.errors)
        check("the missing issuer ticker is named", "CSCO" in messages, messages)
        check("the unresolvable account_id is named", "indmoney_us" in messages, messages)
        check("both are errors", len(report.errors) >= 2)


def test_doctor_catches_oversell_and_missing_cash() -> None:
    print("\ndoctor: an oversold position and an unlisted cash account")
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        shutil.copytree(SYNTH, work)
        path = os.path.join(work, "transactions.csv")
        with open(path, "a") as fh:
            fh.write("etrade_stockplan,CSCO,SELL,2025-12-01,9999,300,,,,,oversell probe\n")
        report = doctor.run_checks(work_paths(work), years=[2025], prices=None,
                                   fx_cache=FX_CACHE, offline=True)
        check("the oversell is an error",
              any(f.category == "sale reconciliation" for f in report.errors))
        check("missing cash balances are a warning, not an error",
              any(f.category == "cash_balances.csv" for f in report.warnings)
              and not any(f.category == "cash_balances.csv" for f in report.errors))
        named = [f for f in report.warnings if f.category == "cash_balances.csv"]
        check("the account-years missing cash are named by id",
              bool(named) and "etrade_stockplan" in named[0].message)


def test_doctor_surfaces_splits() -> None:
    print("\ndoctor: a split affecting a holding surfaces before the build")
    from itrprep.prices import PriceStore

    report = doctor.run_checks(
        work_paths(SPLIT_SYNTH), years=[2023, 2024, 2025],
        prices=PriceStore(PRICE_CACHE, offline=True), fx_cache=FX_CACHE, offline=True,
    )
    splits_found = [f for f in report.warnings if f.category == "splits"]
    check("the split is reported", bool(splits_found))
    check("the message names the ratio and the ticker",
          bool(splits_found) and "AVGO" in splits_found[0].message
          and "10-for-1" in splits_found[0].message)
    check("the hint names the flag the build will demand",
          bool(splits_found) and "--split-basis" in splits_found[0].hint)
    priced = [f for f in report.warnings if f.category == "prices"]
    check("the price-sanity check independently flags the 10x row", bool(priced))


def test_doctor_exit_codes() -> None:
    print("\ndoctor: exit codes")
    clean = subprocess.run(
        [PYTHON, "-m", "itrprep.cli", "doctor", "--work", SYNTH, "--years", "2023-2025"],
        cwd=ROOT, capture_output=True, text=True,
    )
    check("exit 0 when only warnings", clean.returncode == 0,
          f"rc={clean.returncode}")
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        subprocess.run([PYTHON, "-m", "itrprep.cli", "init", "--work", work],
                       cwd=ROOT, capture_output=True, check=True)
        dirty = subprocess.run(
            [PYTHON, "-m", "itrprep.cli", "doctor", "--work", work, "--years", "2025"],
            cwd=ROOT, capture_output=True, text=True,
        )
    check("exit 1 when there are errors", dirty.returncode == 1,
          f"rc={dirty.returncode}")


# -- the Indian-securities scope guard ---------------------------------------
#
# `scripts/check_no_real_data.py --self-test` is the precedent for this block: plant every
# shape the check claims to catch, in a throwaway copy, and assert it is caught. The negative
# cases matter as much as the positive ones here, because a guard that fired on `IVV` -- an
# iShares ETF, foreign, legitimately disclosable -- would be worse than no guard at all.
#
# Every value below is invented. No real security carries a `999Z01ZZ9` body, and the ISINs are
# well-formed only in shape.

FAKE_INDIAN_EQUITY_ISIN = "INE999Z01ZZ9"   # INE: an Indian company's equity
FAKE_INDIAN_FUND_ISIN = "INF999Z01ZZ9"     # INF: an Indian mutual fund scheme
FAKE_INDIAN_GILT_ISIN = "IN0099Z01ZZ9"     # IN, third letter neither E nor F
FAKE_FOREIGN_ISIN = "US99999ZZZZ9"

_PLANTED_TXN = {
    "account_id": "indmoney_us",
    "txn_type": "BUY",
    "date": "2025-04-01",
    "quantity": "100",
    "price_usd": "12.50",
    "amount_usd": "1250.00",
    "acq_kind": "OPEN_MARKET",
    "lot_id": "PLANTED-1",
    "notes": "planted by the test suite",
}

_PLANTED_ISSUER = {
    "entity_name": "Invented Holdings Limited",
    "entity_address": "1 Invented Road, Nowhere",
    "entity_zip": "999999",
    "entity_nature": "Listed Company",
    "country_code": "2",
    "country_name": "UNITED STATES OF AMERICA",
}


def _append_rows(path: str, rows: list[dict], extra_columns: list[str]) -> None:
    with open(path, newline="", encoding="utf-8") as fh:
        existing = list(csv.DictReader(fh))
        fields = list(existing[0].keys())
    for column in extra_columns:
        if column not in fields:
            fields.append(column)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in existing + rows:
            writer.writerow({f: row.get(f, "") for f in fields})


def _plant(tmp: str, *, txns: list[dict] = (), issuers: list[dict] = ()) -> str:
    """A copy of the synthetic dataset with extra holdings grafted on."""
    work = os.path.join(tmp, "work")
    shutil.copytree(SYNTH, work)
    if txns:
        _append_rows(os.path.join(work, "transactions.csv"),
                     [dict(_PLANTED_TXN, **t) for t in txns],
                     ["isin", "currency"])
    if issuers:
        _append_rows(os.path.join(work, "issuers.csv"),
                     [dict(_PLANTED_ISSUER, **i) for i in issuers], ["isin"])
    return work


def _scope_errors(work: str, **kwargs) -> list:
    report = doctor.run_checks(work_paths(work), years=[2025], prices=None,
                              fx_cache=FX_CACHE, offline=True, **kwargs)
    return [f for f in report.errors if f.category == "scope"], report


def test_scope_guard_catches_every_shape() -> None:
    print("\nscope: each detectable shape of an Indian security is refused")
    shapes = [
        ("an INF ISIN on a transaction row (Indian mutual fund)",
         {"txns": [{"ticker": "SYNTHMF", "isin": FAKE_INDIAN_FUND_ISIN}],
          "issuers": [{"ticker": "SYNTHMF"}]},
         "SYNTHMF"),
        ("an INE ISIN on a transaction row (Indian equity)",
         {"txns": [{"ticker": "SYNTHEQ", "isin": FAKE_INDIAN_EQUITY_ISIN}],
          "issuers": [{"ticker": "SYNTHEQ"}]},
         "SYNTHEQ"),
        ("an IN ISIN that is neither INE nor INF (government paper)",
         {"txns": [{"ticker": "SYNTHGS", "isin": FAKE_INDIAN_GILT_ISIN}],
          "issuers": [{"ticker": "SYNTHGS"}]},
         "SYNTHGS"),
        ("an ISIN carried only on the issuers.csv row",
         {"txns": [{"ticker": "SYNTHISS"}],
          "issuers": [{"ticker": "SYNTHISS", "isin": FAKE_INDIAN_FUND_ISIN}]},
         "SYNTHISS"),
        ("an INR-denominated row with no ISIN anywhere",
         {"txns": [{"ticker": "SYNTHINR", "currency": "INR"}],
          "issuers": [{"ticker": "SYNTHINR"}]},
         "SYNTHINR"),
        ("a rupee sign in the currency column",
         {"txns": [{"ticker": "SYNTHRS", "currency": "\u20b9"}],
          "issuers": [{"ticker": "SYNTHRS"}]},
         "SYNTHRS"),
        ("an NSE ticker suffix, no ISIN and no currency",
         {"txns": [{"ticker": "SYNTHNSE.NS"}],
          "issuers": [{"ticker": "SYNTHNSE.NS"}]},
         "SYNTHNSE.NS"),
        ("a BSE ticker suffix",
         {"txns": [{"ticker": "SYNTHBSE.BO"}],
          "issuers": [{"ticker": "SYNTHBSE.BO"}]},
         "SYNTHBSE.BO"),
        ("an issuer whose country is INDIA",
         {"txns": [{"ticker": "SYNTHIND"}],
          "issuers": [{"ticker": "SYNTHIND", "country_name": "INDIA"}]},
         "SYNTHIND"),
    ]
    for label, planted, ticker in shapes:
        with tempfile.TemporaryDirectory() as tmp:
            errors, _ = _scope_errors(_plant(tmp, **planted))
            check(f"refused: {label}", bool(errors))
            check(f"  and the message names {ticker}",
                  any(ticker in f.message for f in errors),
                  "; ".join(f.message for f in errors)[:200])


def test_scope_guard_leaves_foreign_holdings_alone() -> None:
    print("\nscope: foreign holdings are untouched")
    from itrprep.prices import PriceStore

    txns = intermediate.read_transactions(os.path.join(SYNTH, "transactions.csv"))
    issuers = intermediate.read_issuers(os.path.join(SYNTH, "issuers.csv"))
    check("the synthetic dataset trips no signal",
          scope.find_indian_securities(txns, issuers) == [])
    for ticker in ("IVV", "JNJ", "CSCO", "AVGO"):
        holdings = [t for t in txns if t.ticker == ticker]
        check(f"{ticker} is still in the fixtures and still clean",
              bool(holdings)
              and scope.find_indian_securities(holdings, issuers) == [])

    report = doctor.run_checks(
        work_paths(SYNTH), years=[2023, 2024, 2025],
        prices=PriceStore(PRICE_CACHE, offline=True), fx_cache=FX_CACHE, offline=True,
    )
    check("doctor raises no scope error on the synthetic dataset",
          not [f for f in report.errors if f.category == "scope"])
    check("and says so in what it checked",
          any("Indian" in line for line in report.checked),
          " | ".join(report.checked))

    # The whole point of keying on structure: these words are all over the names of legitimate
    # foreign funds, and an earlier design that matched them would have failed here.
    with tempfile.TemporaryDirectory() as tmp:
        work = _plant(
            tmp,
            txns=[{"ticker": "SYNTHETF", "isin": FAKE_FOREIGN_ISIN,
                   "currency": "USD",
                   "notes": "Growth option, IDCW reinvestment, Direct Plan"}],
            issuers=[{"ticker": "SYNTHETF", "isin": FAKE_FOREIGN_ISIN,
                      "entity_name": "Invented Global Growth Fund - Direct Plan IDCW"}],
        )
        errors, _ = _scope_errors(work)
        check("a foreign fund whose NAME says Fund, Growth, Direct Plan and IDCW passes",
              not errors, "; ".join(f.message for f in errors)[:200])

    with tempfile.TemporaryDirectory() as tmp:
        work = _plant(tmp, txns=[{"ticker": "SYNTHPH", "isin": "INVALID"}],
                      issuers=[{"ticker": "SYNTHPH"}])
        errors, _ = _scope_errors(work)
        check("a hand-written INVALID placeholder in the isin column is not an ISIN",
              not errors, "; ".join(f.message for f in errors)[:200])

    with tempfile.TemporaryDirectory() as tmp:
        work = _plant(tmp, txns=[{"ticker": "SYNTHBIOT"}],
                      issuers=[{"ticker": "SYNTHBIOT",
                                "country_name": "BRITISH INDIAN OCEAN TERRITORY",
                                "country_code": "22"}])
        errors, _ = _scope_errors(work)
        check("BRITISH INDIAN OCEAN TERRITORY is not India",
              not errors, "; ".join(f.message for f in errors)[:200])


def test_scope_refusal_message_is_actionable() -> None:
    print("\nscope: the refusal explains itself")
    with tempfile.TemporaryDirectory() as tmp:
        work = _plant(tmp, txns=[{"ticker": "SYNTHMF", "isin": FAKE_INDIAN_FUND_ISIN}],
                      issuers=[{"ticker": "SYNTHMF"}])
        errors, _ = _scope_errors(work)
        text = "\n".join(f.message + "\n" + f.hint for f in errors)
    check("it counts the holdings in the singular when there is one",
          "1 holding in this ledger looks like an INDIAN security" in text, text[:160])
    check("it names the ISIN it read", FAKE_INDIAN_FUND_ISIN in text)
    check("it names the file the row came from", "transactions.csv" in text)
    check("it says a mutual fund scheme is what INF means",
          "Indian mutual fund scheme" in text)
    check("it explains that Schedule FA is for assets outside India",
          "OUTSIDE India" in text)
    check("it cites the department's own field name",
          "CountryCodeExcludingIndia" in text)
    check("it says the tool does not handle Indian mutual funds or capital gains at all",
          "does not handle Indian mutual funds or Indian capital gains" in text)
    check("it says what to do instead: Schedule CG, outside this tool",
          "Schedule CG" in text and "outside this tool" in text)
    check("it admits what it cannot see",
          "WILL NOT" in text and "BE CAUGHT" in text)
    check("it names the escape hatch", scope.ALLOW_FLAG in text)
    check("and warns that the flag is not per-row",
          "rather than for" in text)


def test_scope_guard_is_not_bypassable_by_skipping_doctor() -> None:
    print("\nscope: build and threshold refuse too, and the flag is the only way past")
    with tempfile.TemporaryDirectory() as tmp:
        work = _plant(tmp, txns=[{"ticker": "SYNTHMF", "isin": FAKE_INDIAN_FUND_ISIN}],
                      issuers=[{"ticker": "SYNTHMF"}])
        out = os.path.join(tmp, "out")

        def cli(*args):
            return subprocess.run([PYTHON, "-m", "itrprep.cli", *args],
                                  cwd=ROOT, capture_output=True, text=True)

        doc = cli("doctor", "--work", work, "--years", "2025")
        check("doctor exits 1", doc.returncode == 1, f"rc={doc.returncode}")
        check("doctor names the guard",
              "INDIAN" in doc.stdout + doc.stderr)

        built = cli("build", "--work", work, "--year", "2025", "--out", out,
                    "--offline", "--fx-cache", FX_CACHE, "--price-cache", PRICE_CACHE)
        check("build refuses even though doctor was never run", built.returncode != 0,
              f"rc={built.returncode}")
        check("build's refusal is the scope refusal, not a downstream failure",
              scope.ALLOW_FLAG in built.stdout + built.stderr,
              (built.stdout + built.stderr)[-300:])

        thr = cli("threshold", "--work", work, "--year", "2025",
                  "--offline", "--fx-cache", FX_CACHE, "--price-cache", PRICE_CACHE)
        check("threshold refuses as well", thr.returncode != 0, f"rc={thr.returncode}")
        check("threshold's refusal is the scope refusal",
              scope.ALLOW_FLAG in thr.stdout + thr.stderr,
              (thr.stdout + thr.stderr)[-300:])

        ran = cli("run", "--work", work, "--year", "2025", "--out", out,
                  "--offline", "--fx-cache", FX_CACHE, "--price-cache", PRICE_CACHE)
        check("run surfaces it at its first stage", ran.returncode != 0,
              f"rc={ran.returncode}")
        check("and does not reach the build stage first",
              scope.ALLOW_FLAG in ran.stdout + ran.stderr,
              (ran.stdout + ran.stderr)[-300:])

        allowed = cli("doctor", "--work", work, "--years", "2025", scope.ALLOW_FLAG)
        check("with the flag, doctor downgrades it to a warning and exits 0",
              allowed.returncode == 0 and scope.ALLOW_FLAG in allowed.stdout
              and "was given" in allowed.stdout,
              f"rc={allowed.returncode}")
        # The report wraps, so compare against it unwrapped.
        unwrapped = " ".join(allowed.stdout.split())
        check("and the warning still names what is being let through",
              "SYNTHMF" in unwrapped
              and "asserts a foreign holding you do not have" in unwrapped,
              unwrapped[-200:])


def test_scope_guard_survives_a_round_trip() -> None:
    print("\nscope: the isin and currency columns are not dropped on the way through")
    with tempfile.TemporaryDirectory() as tmp:
        work = _plant(tmp, txns=[{"ticker": "SYNTHMF", "isin": FAKE_INDIAN_FUND_ISIN,
                                  "currency": "INR"}],
                      issuers=[{"ticker": "SYNTHMF"}])
        path = os.path.join(work, "transactions.csv")
        txns = intermediate.read_transactions(path)
        planted = [t for t in txns if t.ticker == "SYNTHMF"]
        check("read_transactions keeps the isin",
              bool(planted) and planted[0].isin == FAKE_INDIAN_FUND_ISIN)
        check("read_transactions keeps the currency",
              bool(planted) and planted[0].currency == "INR")

        again = os.path.join(tmp, "rewritten.csv")
        intermediate.write_transactions(again, txns)
        rewritten = [t for t in intermediate.read_transactions(again)
                     if t.ticker == "SYNTHMF"]
        check("write_transactions round-trips both, so `normalize --append` cannot "
              "silently disarm the guard",
              bool(rewritten) and rewritten[0].isin == FAKE_INDIAN_FUND_ISIN
              and rewritten[0].currency == "INR")


# -- header sniffing ---------------------------------------------------------

def test_detection_by_content() -> None:
    print("\ndetection: exports are classified by content, not filename")
    with tempfile.TemporaryDirectory() as tmp:
        # Deliberately misleading names: the E*TRADE file is named as if it were Fidelity.
        etrade = os.path.join(tmp, "fidelity_statement_final.csv")
        shutil.copy(os.path.join(EXPORTS, "etrade_benefit_history.csv"), etrade)
        indmoney = os.path.join(tmp, "Download (3).csv")
        shutil.copy(os.path.join(EXPORTS, "indmoney_transactions.csv"), indmoney)
        fidelity = os.path.join(tmp, "etrade-2024.csv")
        shutil.copy(os.path.join(EXPORTS, "fidelity_espp.csv"), fidelity)

        check("a misleadingly named E*TRADE export is still matched to etrade",
              adapters.detect(etrade).broker == "etrade")
        check("a meaninglessly named INDmoney export is matched to indmoney",
              adapters.detect(indmoney).broker == "indmoney")
        check("a misleadingly named Fidelity export is still matched to fidelity",
              adapters.detect(fidelity).broker == "fidelity")

        detection = adapters.detect(etrade)
        check("the evidence for the match is reported",
              bool(detection.evidence) and detection.score > 0)
        check("the runner-up scores lower, so the match is unambiguous",
              detection.score > detection.runner_up_score)

        junk = os.path.join(tmp, "notes.csv")
        with open(junk, "w") as fh:
            fh.write("some,random,columns\n1,2,3\n")
        unknown = adapters.detect(junk)
        check("an unclassifiable file is refused rather than guessed",
              unknown.broker is None and not unknown.confident)
        check("and it says why", bool(unknown.reason))


def test_xlsx_reading() -> None:
    print("\ndetection: XLSX exports read directly, dates included")
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import make_xlsx_fixture

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "book.xlsx")
        make_xlsx_fixture.build(path)
        rows = adapters.read_table(path)
        flat = [cell for row in rows for cell in row]
        check("the preamble above the header is preserved",
              any("Transaction Report" in c for c in flat))
        check("dates come back as ISO, not Excel serial numbers",
              "2025-01-08" in flat and "45665" not in flat)
        check("an XLSX is classified like any other export",
              adapters.detect(path).broker == "indmoney")
        txns, _ = adapters.normalize(path, "indmoney", "indmoney_us")
        check("and normalizes into transactions", len(txns) == 4)
        kinds = {t.txn_type for t in txns}
        check("buy, sell and dividend rows are all classified",
              kinds == {"BUY", "SELL", "DIVIDEND"}, str(kinds))


# -- schema resolution -------------------------------------------------------

def _fake_schema(directory: str, assessment_year: int) -> str:
    """A file named like the ITD's, with just enough inside to be loadable."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"ITR-2_{assessment_year}_Main_V1.1.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"$schema": "http://json-schema.org/draft-04/schema#",
                   "definitions": {"ScheduleFA": {"type": "object"}}}, fh)
    return path


def test_schema_resolution() -> None:
    """The schema is not in the repo, so finding it must not depend on one box's layout."""
    print("\nschema resolution: flag, environment, then a directory search")
    original_root = validate._REPO_ROOT
    original_env = os.environ.get(validate.SCHEMA_ENV_VAR)
    original_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            elsewhere = os.path.join(tmp, "elsewhere")
            validate._REPO_ROOT = repo
            os.environ.pop(validate.SCHEMA_ENV_VAR, None)
            os.chdir(tmp)

            # Nothing anywhere: a message, not a traceback.
            os.makedirs(repo, exist_ok=True)
            try:
                validate.find_schema()
                check("missing schema raises SchemaError", False, "no exception")
            except validate.SchemaError as exc:
                check("missing schema raises SchemaError", True)
                message = str(exc)
                check("the message names the expected filename",
                      validate.SCHEMA_GLOB in message and "ITR-2_2026_Main" in message,
                      message)
                check("the message says where to download it",
                      "incometax.gov.in" in message, message)
                check("the message lists the directories searched",
                      repo in message, message)
                check("the message offers the env var and the flag",
                      validate.SCHEMA_ENV_VAR in message and "--schema" in message,
                      message)
                check("the message mentions --no-validate as the escape hatch",
                      "--no-validate" in message, message)

            # schemas/ under the repo is found without configuration.
            in_repo = _fake_schema(os.path.join(repo, validate.SCHEMA_DIRNAME), 2026)
            check("a schema in schemas/ is found with no configuration",
                  validate.find_schema() == in_repo, validate.find_schema())

            # Explicit path and env var both win, in the documented order.
            explicit = _fake_schema(elsewhere, 2024)
            check("--schema overrides the search", validate.find_schema(explicit) == explicit)
            os.environ[validate.SCHEMA_ENV_VAR] = explicit
            check("the env var overrides the search", validate.find_schema() == explicit)
            check("--schema still beats the env var",
                  validate.find_schema(in_repo) == in_repo)
            os.environ.pop(validate.SCHEMA_ENV_VAR)

            # A bad explicit path or env var must name the offender, not fall back silently
            # to a different year's schema.
            for label, kwargs, env in (
                ("--schema", {"explicit": os.path.join(tmp, "nope.json")}, None),
                ("$" + validate.SCHEMA_ENV_VAR, {}, os.path.join(tmp, "nope.json")),
            ):
                if env:
                    os.environ[validate.SCHEMA_ENV_VAR] = env
                try:
                    validate.find_schema(**kwargs)
                    check(f"a bad {label} is an error, not a silent fallback", False)
                except validate.SchemaError as exc:
                    check(f"a bad {label} is an error, not a silent fallback",
                          "nope.json" in str(exc), str(exc))
                os.environ.pop(validate.SCHEMA_ENV_VAR, None)

            # Year-aware selection. Calendar 2025 is assessment year 2026-27.
            _fake_schema(os.path.join(repo, validate.SCHEMA_DIRNAME), 2025)
            check("calendar 2025 picks the AY 2026 schema",
                  os.path.basename(validate.find_schema(year=2025))
                  == "ITR-2_2026_Main_V1.1.json")
            check("calendar 2024 picks the AY 2025 schema",
                  os.path.basename(validate.find_schema(year=2024))
                  == "ITR-2_2025_Main_V1.1.json")
            check("with no year hint the newest schema wins",
                  os.path.basename(validate.find_schema())
                  == "ITR-2_2026_Main_V1.1.json")
            try:
                validate.find_schema(year=2019)
                check("a year with no schema is refused rather than substituted", False)
            except validate.SchemaError as exc:
                check("a year with no schema is refused rather than substituted",
                      "2020-21" in str(exc) and "2025, 2026" in str(exc), str(exc))

            # load_schema returns the path it used, so output can say what it validated
            # against rather than leaving the reader to guess.
            schema, used = validate.load_schema(year=2025)
            check("load_schema reports the file it read",
                  used.endswith("ITR-2_2026_Main_V1.1.json") and "definitions" in schema)

            # The searched paths must not be hardcoded to any one machine.
            check("no absolute home directory is baked into the search",
                  not any(d.startswith("/home/") or d.startswith("/Users/")
                          for d in validate.search_dirs()),
                  str(validate.search_dirs()))
    finally:
        validate._REPO_ROOT = original_root
        os.chdir(original_cwd)
        if original_env is None:
            os.environ.pop(validate.SCHEMA_ENV_VAR, None)
        else:
            os.environ[validate.SCHEMA_ENV_VAR] = original_env


def test_build_shouts_when_validation_is_skipped() -> None:
    """An unvalidated build must be impossible to mistake for a validated one."""
    print("\nbuild: a skipped validation is loud, not a quiet line")
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "fa.json")
        env = dict(os.environ)
        env.pop(validate.SCHEMA_ENV_VAR, None)
        proc = subprocess.run(
            [PYTHON, "-m", "itrprep.cli", "build", "--year", "2025",
             "--transactions", os.path.join(SYNTH, "transactions.csv"),
             "--issuers", os.path.join(SYNTH, "issuers.csv"),
             "--accounts", os.path.join(SYNTH, "accounts.csv"),
             "--out", out, "--offline",
             "--schema", os.path.join(tmp, "absent.json")],
            capture_output=True, text=True, cwd=ROOT, env=env,
        )
        check("the build still produces a file", os.path.exists(out))
        check("but says loudly that it is unverified",
              "SCHEMA VALIDATION WAS SKIPPED" in proc.stdout, proc.stdout[-400:])
        check("the warning is banner-delimited, not one quiet line",
              "!!!!!!!!" in proc.stdout)
        check("and it explains how to fix it",
              "incometax.gov.in" in proc.stdout)
        check("the warning is the last thing printed, after the next steps",
              proc.stdout.rstrip().endswith("!" * 78), proc.stdout[-200:])

        proc = subprocess.run(
            [PYTHON, "-m", "itrprep.cli", "build", "--year", "2025",
             "--transactions", os.path.join(SYNTH, "transactions.csv"),
             "--issuers", os.path.join(SYNTH, "issuers.csv"),
             "--accounts", os.path.join(SYNTH, "accounts.csv"),
             "--out", os.path.join(tmp, "fa2.json"), "--offline", "--no-validate"],
            capture_output=True, text=True, cwd=ROOT, env=env,
        )
        check("--no-validate is equally loud",
              "SCHEMA VALIDATION WAS SKIPPED" in proc.stdout, proc.stdout[-400:])


# -- readback verifier -------------------------------------------------------

def _cell(text, value=None):
    return {"text": str(text), "value": str(text if value is None else value)}


def _good_dump():
    """A dump equivalent to a correct import of `_expected()`."""
    return {
        "aoi_flag": "Yes",
        "a3": {"sheet": "TR_FA", "first_row": 10, "block_rows": 2, "rows": [
            {
                "FA_A3_Country": _cell("2-UNITED STATES OF AMERICA"),
                "FA_A3_BankName": _cell("Cisco Systems, Inc."),
                "FA_A3_BankAdd": _cell("170 West Tasman Drive"),
                "FA_A3_ZipCode": _cell("95134"),
                "FA_A3_NatureOfEntity": _cell("Listed Company"),
                "FA_A3_AccOpeningDate": _cell("15/08/2024"),
                "FA_A3_initialvalue": _cell("203583"),
                "FA_A3_PeakBal": _cell("254612"),
                "FA_A3_ClosingBal": _cell("126455"),
                "FA_A3_Totalgrossamount": _cell("0"),
                "FA_A3_Totalgrosproceeds": _cell("127500"),
            },
            {
                "FA_A3_Country": _cell("2-UNITED STATES OF AMERICA"),
                "FA_A3_BankName": _cell("Johnson & Johnson"),
                "FA_A3_BankAdd": _cell("One Johnson & Johnson Plaza"),
                "FA_A3_ZipCode": _cell("08933"),
                "FA_A3_NatureOfEntity": _cell("Listed Company"),
                "FA_A3_AccOpeningDate": _cell("30/06/2023"),
                "FA_A3_initialvalue": _cell("208418"),
                "FA_A3_PeakBal": _cell("348150"),
                "FA_A3_ClosingBal": _cell("333216"),
                "FA_A3_Totalgrossamount": _cell("8504"),
                "FA_A3_Totalgrosproceeds": _cell("0"),
            },
        ]},
        "a2": {"sheet": "TR_FA", "first_row": 38, "block_rows": 1, "rows": [
            {
                "FA_A2_Country": _cell("2-UNITED STATES OF AMERICA"),
                "FA_A2_BankName": _cell("Fidelity Brokerage Services"),
                "FA_A2_BankAdd": _cell("245 Summer Street"),
                "FA_A2_ZipCode": _cell("02210"),
                "FA_A2_ForeignAccountNumber": _cell("SYNTH-FID-0002"),
                "FA_A2_StatusBeneficiary": _cell("OWNER"),
                "FA_A2_AccOpeningDate": _cell("01/02/2023"),
                "FA_A2_PeakBal": _cell("2811228"),
                "FA_A2_ClosingBal": _cell("2552900"),
                "FA_A2_Grossinterest": _cell("8504"),
                "FA_A2_Grossinterest_Nature": _cell("Dividend"),
            },
        ]},
    }


def _expected():
    return {"ITR": {"ITR2": {"ScheduleFA": {
        "DtlsForeignEquityDebtInterest": [
            {
                "CountryName": "UNITED STATES OF AMERICA",
                "CountryCodeExcludingIndia": "2",
                "NameOfEntity": "Cisco Systems, Inc.",
                "AddressOfEntity": "170 West Tasman Drive",
                "ZipCode": "95134",
                "NatureOfEntity": "Listed Company",
                "InterestAcquiringDate": "2024-08-15",
                "InitialValOfInvstmnt": 203583,
                "PeakBalanceDuringPeriod": 254612,
                "ClosingBalance": 126455,
                "TotGrossAmtPaidCredited": 0,
                "TotGrossProceeds": 127500,
            },
            {
                "CountryName": "UNITED STATES OF AMERICA",
                "CountryCodeExcludingIndia": "2",
                "NameOfEntity": "Johnson & Johnson",
                "AddressOfEntity": "One Johnson & Johnson Plaza",
                "ZipCode": "08933",
                "NatureOfEntity": "Listed Company",
                "InterestAcquiringDate": "2023-06-30",
                "InitialValOfInvstmnt": 208418,
                "PeakBalanceDuringPeriod": 348150,
                "ClosingBalance": 333216,
                "TotGrossAmtPaidCredited": 8504,
                "TotGrossProceeds": 0,
            },
        ],
        "DtlsForeignCustodialAcc": [
            {
                "CountryName": "UNITED STATES OF AMERICA",
                "CountryCodeExcludingIndia": "2",
                "FinancialInstName": "Fidelity Brokerage Services",
                "FinancialInstAddress": "245 Summer Street",
                "ZipCode": "02210",
                "AccountNumber": "SYNTH-FID-0002",
                "Status": "OWNER",
                "AccOpenDate": "2023-02-01",
                "PeakBalanceDuringPeriod": 2811228,
                "ClosingBalance": 2552900,
                "GrossAmtPaidCredited": 8504,
                "NatureOfAmount": "D",
            },
        ],
    }}}}


def test_readback_passes_a_good_import() -> None:
    print("\nreadback: a correct import passes")
    report = readback.verify(_good_dump(), _expected())
    check("no mismatches", report.passed,
          "; ".join(f"{m.field}: {m.expected} != {m.got}" for m in report.mismatches))
    check("the AOI flag is checked",
          any("item 19" in c for c in report.checks))
    check("every row is claimed as checked, not a sample",
          any("all 2 row(s)" in c for c in report.checks))
    check("render says PASS", "PASS" in readback.render(report))


def test_readback_catches_truncation() -> None:
    print("\nreadback: a dropped last row is caught (the truncation case)")
    dump = _good_dump()
    dump["a3"]["rows"] = dump["a3"]["rows"][:1]
    report = readback.verify(dump, _expected())
    check("the import is failed", not report.passed)
    check("the row count mismatch is reported",
          any(m.field == "row count" for m in report.mismatches))
    counted = [m for m in report.mismatches if m.field == "row count"]
    check("and it says how many were expected versus found",
          bool(counted) and counted[0].expected == "2" and counted[0].got == "1")

    print("readback: a blanked last row is caught even when the count looks right")
    dump2 = _good_dump()
    dump2["a3"]["rows"][-1] = {k: _cell("") for k in dump2["a3"]["rows"][-1]}
    report2 = readback.verify(dump2, _expected())
    check("a blank final row fails", not report2.passed)


def test_readback_catches_rupee_mismatch() -> None:
    print("\nreadback: every rupee figure is compared, not two sampled rows")
    dump = _good_dump()
    dump["a3"]["rows"][1]["FA_A3_PeakBal"] = _cell("857600")
    report = readback.verify(dump, _expected())
    peak = [m for m in report.mismatches if m.field == "FA_A3_PeakBal"]
    check("a wrong figure in the SECOND row is caught", bool(peak))
    check("the row number is reported", bool(peak) and peak[0].row == 2)
    check("the difference is quantified", bool(peak) and "off by" in peak[0].note)


def test_readback_catches_country_and_date_rendering() -> None:
    print("\nreadback: country and date rendering")
    dump = _good_dump()
    dump["a3"]["rows"][0]["FA_A3_Country"] = _cell("2")
    report = readback.verify(dump, _expected())
    check("a country cell that did not resolve to code-NAME fails",
          any(m.field == "FA_A3_Country" for m in report.mismatches))

    dump2 = _good_dump()
    dump2["a3"]["rows"][0]["FA_A3_AccOpeningDate"] = _cell("45519")
    report2 = readback.verify(dump2, _expected())
    check("a date that arrived as a serial number fails",
          any(m.field == "FA_A3_AccOpeningDate" for m in report2.mismatches))

    dump3 = _good_dump()
    # US-style rendering: the same day, formatted MM/DD/YYYY instead of DD/MM/YYYY.
    dump3["a3"]["rows"][0]["FA_A3_AccOpeningDate"] = _cell("08/15/2024")
    report3 = readback.verify(dump3, _expected())
    check("a month/day transposition fails",
          any(m.field == "FA_A3_AccOpeningDate" for m in report3.mismatches))


def test_readback_catches_zip_leading_zero() -> None:
    print("\nreadback: the leading-zero zip defect")
    dump = _good_dump()
    dump["a2"]["rows"][0]["FA_A2_ZipCode"] = _cell("2210")
    report = readback.verify(dump, _expected())
    zips = [m for m in report.mismatches if m.field == "FA_A2_ZipCode"]
    check("a stripped leading zero is caught", bool(zips))
    check("and diagnosed as a number-format problem",
          bool(zips) and "leading zero" in zips[0].note)


def test_readback_checks_nature_code_expansion() -> None:
    print("\nreadback: nature-of-amount code expansion")
    report = readback.verify(_good_dump(), _expected())
    check("code 'D' matches the label 'Dividend' the utility expands it to",
          not any(m.field == "FA_A2_Grossinterest_Nature" for m in report.mismatches))

    dump = _good_dump()
    dump["a2"]["rows"][0]["FA_A2_Grossinterest_Nature"] = _cell("Interest")
    report2 = readback.verify(dump, _expected())
    check("the wrong label for that code fails",
          any(m.field == "FA_A2_Grossinterest_Nature" for m in report2.mismatches))


def test_readback_requires_aoi_flag() -> None:
    print("\nreadback: Part B-TTI item 19")
    dump = _good_dump()
    dump["aoi_flag"] = ""
    report = readback.verify(dump, _expected())
    check("a missing item 19 fails the import",
          any(m.field == "AOIFlag_1" for m in report.mismatches))


def test_readback_cross_checks_audit_csv() -> None:
    print("\nreadback: the audit CSV cross-check")
    with tempfile.TemporaryDirectory() as tmp:
        audit = os.path.join(tmp, "audit.csv")
        header = ("ticker,lot_id,account_id,acq_kind,acquire_date,initial_qty,"
                  "initial_price_usd,initial_fx,initial_value_inr,peak_date,peak_qty,"
                  "peak_price_usd,peak_fx,peak_fx_date,peak_value_inr,closing_qty,"
                  "closing_price_usd,closing_fx,closing_value_inr,dividends_usd,"
                  "gross_credited_inr,proceeds_usd,gross_proceeds_inr,notes\n")
        rows = [
            "CSCO,L1,etrade_stockplan,,2024-08-15,50,48.53,83.90,203583,"
            "2024-12-16,50,60.05,84.80,2024-12-16,254612,"
            "25,59.16,85.50,126455,0,0,1500,127500,\n",
            "JNJ,L2,fidelity_espp,,2023-06-30,18,140.69,82.30,208418,"
            "2025-10-28,18,218.55,88.50,2025-10-28,348150,"
            "18,208.00,89.00,333216,96,8504,0,0,\n",
        ]
        with open(audit, "w") as fh:
            fh.write(header)
            fh.writelines(rows)

        report = readback.verify(_good_dump(), _expected(), audit)
        check("a consistent audit CSV passes", report.passed,
              "; ".join(f"{m.field}: {m.expected} != {m.got}" for m in report.mismatches))
        check("the cross-check is reported as done",
              any("audit trail" in c for c in report.checks))

        # Now break the JSON so it disagrees with the audit trail it came from. The skew is
        # deliberately small -- a few hundred rupees on a quarter-lakh figure -- because a
        # cross-check that only catches gross errors is not worth having.
        skewed = copy.deepcopy(_expected())
        skewed["ITR"]["ITR2"]["ScheduleFA"][
            "DtlsForeignEquityDebtInterest"][0]["PeakBalanceDuringPeriod"] = 254000
        broken_dump = _good_dump()
        broken_dump["a3"]["rows"][0]["FA_A3_PeakBal"] = _cell("254000")
        report2 = readback.verify(broken_dump, skewed, audit)
        check("a JSON that disagrees with the audit CSV is caught even though the "
              "sheet matches the JSON",
              any(m.table == "audit" for m in report2.mismatches))


def test_import_refuses_to_reuse_a_workbook() -> None:
    print("\nimport: never reuses a working copy")
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import import_to_utility

    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "already_here.xlsm"), "w").write("pretend workbook")
        try:
            import_to_utility.working_copy(tmp, "already_here")
            check("refuses to reuse an existing workbook", False, "no exception raised")
        except import_to_utility.ImportFailed as exc:
            check("refuses to reuse an existing workbook", True)
            check("and explains why re-import is unsafe",
                  "blank rows" in str(exc), str(exc))
        check("a name not yet used is allowed",
              import_to_utility.working_copy(tmp, "fresh").endswith("fresh.xlsm"))


# -- the platform boundary ---------------------------------------------------
#
# The one non-portable step in this tool is the one that drives the department's .xlsm.
# These checks assert where that boundary is and that crossing it fails with an
# explanation rather than with `FileNotFoundError: wslpath`. Every host is described by
# injecting the platform name and a `which`, because a check that only runs on the
# machine it describes proves nothing about the other machines.

def _which(*available: str):
    return lambda name: f"/usr/bin/{name}" if name in available else None


def test_platform_boundary() -> None:
    print("\nplatform: where the Windows requirement starts and stops")
    from itrprep import host

    check("a Windows Python can drive the utility",
          host.detect("win32", _which()) == host.WINDOWS)
    check("WSL with powershell.exe and wslpath can too",
          host.detect("linux", _which("powershell.exe", "wslpath")) == host.WSL)
    check("a Mac cannot", host.detect("darwin", _which()) is None)
    check("nor can a Linux box with no WSL interop",
          host.detect("linux", _which("bash", "python3")) is None)
    check("nor can WSL with only half of the interop present",
          host.detect("linux", _which("powershell.exe")) is None)

    try:
        host.require("darwin", _which())
        check("require() refuses a host with no Excel", False, "no exception raised")
        message = ""
    except host.UnsupportedHost as exc:
        check("require() refuses a host with no Excel", True)
        message = str(exc)

    check("the refusal names the host it ran on", "darwin" in message, message)
    check("it points at the department's macOS Common Offline Utility",
          "Common Offline Utility" in message, message)
    check("it points at a Windows VM as the tested alternative",
          "virtual machine" in message, message)
    check("it says the rest of the tool does not need Windows",
          "Nothing else in this tool needs Windows" in message, message)
    check("it does not claim the macOS route has been tested here",
          "has NOT" in message, message)


def test_only_the_driver_knows_about_windows() -> None:
    print("\nplatform: the package itself is portable")
    import importlib

    modules = sorted(
        os.path.splitext(f)[0] for f in os.listdir(os.path.join(ROOT, "itrprep"))
        if f.endswith(".py") and f != "__init__.py"
    )
    failed = []
    for name in modules:
        try:
            importlib.import_module(f"itrprep.{name}")
        except Exception as exc:                                   # noqa: BLE001
            failed.append(f"{name}: {exc}")
    check(f"all {len(modules)} modules in itrprep/ import on this host",
          not failed, "; ".join(failed))

    # Windows knowledge is allowed in exactly two places: itrprep/host.py, whose whole job
    # is to describe the boundary, and scripts/, which is the driver. Anywhere else and
    # the package stops being importable on a Mac.
    tokens = ("win32com", "pythoncom", "powershell.exe", "wslpath", "Excel.Application")
    leaked = []
    for name in modules:
        if name == "host":
            continue
        with open(os.path.join(ROOT, "itrprep", f"{name}.py"), encoding="utf-8") as fh:
            body = fh.read()
        leaked += [f"{name}.py: {t}" for t in tokens if t in body]
    check("no module in itrprep/ reaches for Windows except host.py",
          not leaked, "; ".join(leaked))


def test_import_command_refuses_a_host_with_no_excel() -> None:
    print("\nplatform: the import step fails loudly rather than obscurely")
    import argparse
    import contextlib
    import io

    from itrprep import cli, host

    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import import_to_utility

    original = host.detect
    host.detect = lambda *_a, **_k: None
    try:
        try:
            import_to_utility.run_import("/no/such/utility.xlsm", "/no/such/fa.json",
                                         2025, "IRRELEVANT")
            check("run_import refuses on a host with no Excel", False, "no exception")
        except host.UnsupportedHost as exc:
            check("run_import refuses on a host with no Excel", True)
            check("and refuses before complaining about missing files",
                  "not found" not in str(exc).splitlines()[0], str(exc))

        args = argparse.Namespace(
            json="/no/such/fa.json", utility="/no/such/utility.xlsm", year=2025,
            audit="", workdir="C:\\temp\\itrprep", name="", label="Non-Business",
            no_save=False, keep_temp=False, timeout=900, verbose=False,
        )
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.cmd_import(args)
        check("`itr-prep import` exits 2 rather than raising", code == 2, str(code))
        check("and prints the platform explanation, not a traceback",
              "Common Offline Utility" in err.getvalue(), err.getvalue()[:200])

        # host.require() gates on Windows Excel being reachable, not installed -- see the
        # note in itrprep/host.py. A WSL box with interop and no Excel gets past it and fails
        # inside COM instead, so the COM error has to explain itself. These run anywhere,
        # because the thing under test is the reading of the transcript rather than COM.
        print("\nplatform: a reachable Windows with no Excel explains itself")
        clsid_error = (
            "New-Object : Retrieving the COM class factory for component with CLSID "
            "{00024500-0000-0000-C000-000000000046} failed due to the following error: "
            "80040154 Class not registered (0x80040154 (REGDB_E_CLASSNOTREG))."
        )
        explained = import_to_utility.explain_no_excel("", clsid_error)
        check("the CLSID class-not-registered error is recognised", bool(explained))
        check("and is explained as Excel not being installed",
              bool(explained) and "Excel does not appear to be installed" in explained,
              (explained or "")[:120])
        check("the explanation names the tested alternative and the macOS route",
              bool(explained) and "Windows 11 VM" in explained
              and "Common Offline Utility" in explained)
        check("and says the JSON is already complete, so the run is not wasted",
              bool(explained) and "already written and complete" in explained)
        check("an unrelated failure is not mislabelled as a missing Excel",
              import_to_utility.explain_no_excel(
                  "", "the utility's ImportScheduleFA macro raised error 13") is None)
    finally:
        host.detect = original


def main() -> int:
    test_doctor_clean()
    test_doctor_catches_example_rows()
    test_doctor_catches_broken_references()
    test_doctor_catches_oversell_and_missing_cash()
    test_doctor_surfaces_splits()
    test_doctor_exit_codes()
    test_scope_guard_catches_every_shape()
    test_scope_guard_leaves_foreign_holdings_alone()
    test_scope_refusal_message_is_actionable()
    test_scope_guard_is_not_bypassable_by_skipping_doctor()
    test_scope_guard_survives_a_round_trip()
    test_detection_by_content()
    test_xlsx_reading()
    test_schema_resolution()
    test_build_shouts_when_validation_is_skipped()
    test_readback_passes_a_good_import()
    test_readback_catches_truncation()
    test_readback_catches_rupee_mismatch()
    test_readback_catches_country_and_date_rendering()
    test_readback_catches_zip_leading_zero()
    test_readback_checks_nature_code_expansion()
    test_readback_requires_aoi_flag()
    test_readback_cross_checks_audit_csv()
    test_import_refuses_to_reuse_a_workbook()
    test_platform_boundary()
    test_only_the_driver_knows_about_windows()
    test_import_command_refuses_a_host_with_no_excel()

    print()
    if failures:
        print(f"FAILED -- {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All doctor / detection / readback checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
