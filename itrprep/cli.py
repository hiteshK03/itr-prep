"""Command line entry point."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys

from . import (
    __version__,
    adapters,
    doctor,
    emit,
    host,
    intermediate,
    positions,
    rules,
    splits,
    threshold,
    unlock,
    validate,
)
from .fx import FxError, FxRates
from .models import (
    ACCOUNT_COLUMNS,
    CASH_COLUMNS,
    ISSUER_COLUMNS,
    TRANSACTION_COLUMNS,
    DataError,
)
from .prices import PriceError, PriceStore

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
DEFAULT_DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DEFAULT_FX_CACHE = os.path.join(DEFAULT_DATA_DIR, "sbi_ttbuy_usd.csv")
DEFAULT_PRICE_CACHE = os.path.join(DEFAULT_DATA_DIR, "prices")

_SCHEMA_HELP = (
    f"path to the ITD ITR-2 schema. Default: ${validate.SCHEMA_ENV_VAR} if set, else "
    f"the newest {validate.SCHEMA_GLOB} found in ./{validate.SCHEMA_DIRNAME}/ or the "
    f"current directory"
)


def _work_paths(work_dir: str) -> dict[str, str]:
    return {
        "transactions": os.path.join(work_dir, "transactions.csv"),
        "issuers": os.path.join(work_dir, "issuers.csv"),
        "accounts": os.path.join(work_dir, "accounts.csv"),
        "overrides": os.path.join(work_dir, "prices_override.csv"),
        "cash": os.path.join(work_dir, "cash_balances.csv"),
    }


# ---------------------------------------------------------------- init

EXAMPLE_TRANSACTIONS = [
    {
        "account_id": "etrade_stockplan", "ticker": "CSCO", "txn_type": "BUY",
        "date": "2025-02-15", "quantity": "40", "price_usd": "64.87",
        "amount_usd": "2594.80", "tax_withheld_usd": "", "acq_kind": "RSU_VEST",
        "lot_id": "CSCO-VEST-2025Q1",
        "notes": "example row - delete me. RSU vest, price = vest-date FMV",
    },
    {
        "account_id": "etrade_stockplan", "ticker": "CSCO", "txn_type": "SELL",
        "date": "2025-09-10", "quantity": "15", "price_usd": "68.13",
        "amount_usd": "1021.95", "tax_withheld_usd": "", "acq_kind": "",
        "lot_id": "CSCO-VEST-2025Q1",
        "notes": "example row - delete me. lot_id names which lot was sold",
    },
    {
        "account_id": "indmoney_us", "ticker": "IVV", "txn_type": "DIVIDEND",
        "date": "2025-06-27", "quantity": "", "price_usd": "",
        "amount_usd": "71.82", "tax_withheld_usd": "17.96", "acq_kind": "",
        "lot_id": "",
        "notes": "example row - delete me. gross dividend + 25% US withholding",
    },
]

EXAMPLE_ISSUERS = [
    {
        "ticker": "CSCO", "entity_name": "Cisco Systems, Inc.",
        "entity_address": "170 West Tasman Drive, San Jose, California",
        "entity_zip": "95134", "entity_nature": "Listed Company",
        "country_code": "2", "country_name": "UNITED STATES OF AMERICA",
    },
    {
        "ticker": "JNJ", "entity_name": "Johnson & Johnson",
        "entity_address": "One Johnson & Johnson Plaza, New Brunswick, New Jersey",
        "entity_zip": "08933", "entity_nature": "Listed Company",
        "country_code": "2", "country_name": "UNITED STATES OF AMERICA",
    },
    {
        "ticker": "IVV", "entity_name": "iShares Core S&P 500 ETF",
        "entity_address": "400 Howard Street, San Francisco, California",
        "entity_zip": "94105", "entity_nature": "Exchange Traded Fund",
        "country_code": "2", "country_name": "UNITED STATES OF AMERICA",
    },
]

EXAMPLE_ACCOUNTS = [
    {
        "account_id": "etrade_stockplan",
        "institution_name": "Morgan Stanley Smith Barney LLC (E*TRADE)",
        "institution_address": "1585 Broadway, New York, New York",
        "institution_zip": "10036", "account_number": "REPLACE-WITH-REAL",
        "status": "OWNER", "account_open_date": "2022-07-01",
        "country_code": "2", "country_name": "UNITED STATES OF AMERICA",
    },
    {
        "account_id": "fidelity_espp",
        "institution_name": "Fidelity Brokerage Services LLC",
        "institution_address": "245 Summer Street, Boston, Massachusetts",
        "institution_zip": "02210", "account_number": "REPLACE-WITH-REAL",
        "status": "OWNER", "account_open_date": "2023-02-01",
        "country_code": "2", "country_name": "UNITED STATES OF AMERICA",
    },
    {
        "account_id": "indmoney_us",
        "institution_name": "DriveWealth LLC",
        "institution_address": "97 Newkirk Street, Jersey City, New Jersey",
        "institution_zip": "07306", "account_number": "REPLACE-WITH-REAL",
        "status": "OWNER", "account_open_date": "2023-05-01",
        "country_code": "2", "country_name": "UNITED STATES OF AMERICA",
    },
]

EXAMPLE_OVERRIDES = [
    {"ticker": "CSCO", "date": "2025-12-31", "close_usd": "77.03"},
]

EXAMPLE_CASH = [
    {
        "account_id": "indmoney_us", "year": "2025",
        "peak_usd": "1250.00", "peak_date": "2025-07-15", "closing_usd": "310.42",
        "notes": "example row - delete me. Uninvested cash from the broker statement; "
                 "leave peak_date blank to convert the peak at the 31 Dec rate",
    },
]


def cmd_init(args) -> int:
    os.makedirs(args.work, exist_ok=True)
    paths = _work_paths(args.work)
    written = []
    for path, columns, examples in (
        (paths["transactions"], TRANSACTION_COLUMNS, EXAMPLE_TRANSACTIONS),
        (paths["issuers"], ISSUER_COLUMNS, EXAMPLE_ISSUERS),
        (paths["accounts"], ACCOUNT_COLUMNS, EXAMPLE_ACCOUNTS),
        (paths["overrides"], ["ticker", "date", "close_usd"], EXAMPLE_OVERRIDES),
        (paths["cash"], CASH_COLUMNS, EXAMPLE_CASH),
    ):
        if os.path.exists(path) and not args.force:
            print(f"  skipped (exists): {path}")
            continue
        intermediate.write_template(path, columns, examples)
        written.append(path)
        print(f"  wrote: {path}")
    if written:
        print(
            "\nEach template carries example rows marked 'example row - delete me'.\n"
            "Delete them before building, and read the data dictionary in README.md."
        )
    return 0


# ---------------------------------------------------------------- fx

def cmd_fx_update(args) -> int:
    try:
        count, first, last = FxRates.update(args.fx_cache)
    except Exception as exc:
        print(f"FX update failed: {exc}", file=sys.stderr)
        return 1
    print(f"Cached {count} SBI TT-buy rates ({first} to {last}) at {args.fx_cache}")
    return 0


# ---------------------------------------------------------------- normalize

def cmd_normalize(args) -> int:
    try:
        result = adapters.normalize_report(
            args.input,
            args.broker,
            args.account_id,
            default_ticker=args.default_ticker,
            acq_kind=args.acq_kind,
        )
    except DataError as exc:
        print(f"\nCould not normalize {args.input}:\n\n{exc}\n", file=sys.stderr)
        return 1
    transactions, warnings = result.transactions, result.warnings
    print(adapters.render_report(result))

    existing = []
    if args.append and os.path.exists(args.out):
        try:
            existing = intermediate.read_transactions(args.out)
        except DataError:
            existing = []
        # Replacing this account's rows keeps re-runs idempotent instead of duplicating.
        existing = [t for t in existing if t.account_id != args.account_id]

    intermediate.write_transactions(args.out, existing + transactions)
    print(f"\nWrote {len(transactions)} transactions for account "
          f"'{args.account_id}' to {args.out}"
          + (f" (kept {len(existing)} rows from other accounts)" if existing else ""))
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings[:40]:
            print(f"  - {w}")
        if len(warnings) > 40:
            print(f"  ... and {len(warnings) - 40} more")
    print("\nReview the file before building. Sales, vest FMVs and dividend "
          "withholding are the fields most often wrong in broker exports.")
    if result.dropped and not args.allow_dropped_rows:
        _dropped_rows_banner([result])
        return 1
    return 0


def _dropped_rows_banner(results) -> None:
    """Refuse to let a partial import pass for a complete one.

    Loud and terminal on purpose. A Schedule FA missing a vest is a Black Money Act s.43
    exposure of Rs 10,00,000 per assessment year, so a run that could not read part of an
    export must stop the same way an unclassifiable file or an unresolved stock split
    does -- with the rows named, and with an explicit flag as the only way past it.
    """
    dropped = [(r, s, line, why) for r in results for s, line, why in r.dropped]
    print()
    print("!" * 78)
    print(f"!! {len(dropped)} ROW(S) COULD NOT BE IMPORTED -- transactions.csv is "
          f"INCOMPLETE")
    print("!" * 78)
    print()
    for result, section, line, why in dropped[:60]:
        print(f"  {os.path.basename(result.path)} line {line} "
              f"(section at {section.label}):")
        for chunk in doctor._wrap(why, width=68):
            print(f"      {chunk}")
    if len(dropped) > 60:
        print(f"  ... and {len(dropped) - 60} more")
    print()
    print("Every row above is a row the broker exported and this tool did not use. If any")
    print("of them is a vest, an ESPP purchase or a sale, Schedule FA and Schedule CG are")
    print("both understated. Do one of:")
    print()
    print("  - add the missing rows to transactions.csv by hand (README data dictionary),")
    print("  - rename the offending column in the export so the adapter recognises it, or")
    print("  - re-run with --allow-dropped-rows once you have confirmed every row above")
    print("    is genuinely not a transaction (a summary block, a footer, a plan notice).")
    print()
    print("!" * 78)


# ---------------------------------------------------------------- build

def cmd_build(args) -> int:
    # Before anything else: is there a rules registry that reaches the year being filed?
    # Running ahead of it would compute a disclosure against a year of law nobody has
    # checked, so it is a hard error rather than a warning.
    try:
        year_rules, rules_warning = rules.require_for_calendar_year(args.year)
    except rules.RulesError as exc:
        print(f"\nRules registry problem:\n\n{exc}\n", file=sys.stderr)
        return 1
    if rules_warning:
        print(rules_warning, file=sys.stderr)
        print(file=sys.stderr)

    paths = _work_paths(args.work)
    try:
        transactions = intermediate.read_transactions(
            args.transactions or paths["transactions"]
        )
        issuers = intermediate.read_issuers(args.issuers or paths["issuers"])
        accounts = intermediate.read_accounts(args.accounts or paths["accounts"])
        intermediate.cross_check(transactions, issuers, accounts)
        cash_path = args.cash or paths["cash"]
        cash_balances = intermediate.read_cash_balances(cash_path)
    except DataError as exc:
        print(f"\nInput data problem:\n\n{exc}\n", file=sys.stderr)
        return 1

    try:
        fx = FxRates.load(args.fx_cache)
        fx.assert_covers_year(args.year)
    except FxError as exc:
        print(f"\nFX problem:\n\n{exc}\n", file=sys.stderr)
        return 1

    overrides = args.overrides or paths["overrides"]
    prices = PriceStore(
        args.price_cache,
        overrides_path=overrides if os.path.exists(overrides) else None,
        offline=args.offline,
    )

    try:
        transactions, split_scan = splits.apply(
            transactions, prices, args.year, args.split_basis
        )
        lots = positions.build_lots(transactions)
        rows = positions.compute_rows(
            lots, transactions, args.year, prices, fx, peak_basis=args.peak_basis
        )
        cash = positions.value_cash(cash_balances, args.year, fx)
    except (DataError, PriceError) as exc:
        print(f"\nComputation failed:\n\n{exc}\n", file=sys.stderr)
        return 1

    _report_splits(split_scan, args.split_basis)

    if not rows:
        print(
            f"No holding was held at any time during calendar {args.year}, so Schedule "
            f"FA has no rows for that year. Check the year and your transaction dates.",
            file=sys.stderr,
        )
        return 1

    schedule_fa = emit.build_schedule_fa(
        rows, issuers, accounts, args.year, include_a2=not args.no_a2, cash=cash
    )

    merge_into = None
    if args.merge_into:
        with open(args.merge_into, encoding="utf-8") as fh:
            merge_into = json.load(fh)

    if args.format == emit.FORMAT_PREFILL:
        document = emit.to_prefill_format(schedule_fa)
    else:
        document = emit.wrap_itr(schedule_fa, merge_into=merge_into)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    emit.dump_json(document, args.out)

    # ---- validation ----
    schema_errors: list[str] = []
    validated_what = "nothing"
    schema_path = ""
    skip_reason = ""
    if not args.no_validate:
        try:
            schema, schema_path = validate.load_schema(args.schema, year=args.year)
            schema_errors = validate.validate_schedule_fa(schedule_fa, schema)
            validated_what = "ScheduleFA subtree"
            if merge_into is not None and args.format == emit.FORMAT_ITR:
                full_errors = validate.validate_full_document(document, schema)
                schema_errors += full_errors
                validated_what = "full ITR document"
        except validate.SchemaError as exc:
            skip_reason = str(exc)

    report_path = os.path.splitext(args.out)[0] + "_audit.csv"
    _write_audit(report_path, rows, args.year, cash)

    totals = positions.compute_year_totals(
        lots, transactions, args.year, fx, rules=year_rules
    )
    summary_path = os.path.splitext(args.out)[0] + "_other_schedules.txt"
    with open(summary_path, "w", encoding="utf-8") as fh:
        fh.write(emit.summarise_other_schedules(
            totals,
            f"{args.year}-{args.year+1-2000}",
            long_term_months=year_rules.int_field(
                "foreign_share_long_term_holding", "months"
            ),
            year_rules=year_rules,
        ))
        fh.write("\n")

    a3 = schedule_fa.get("DtlsForeignEquityDebtInterest", [])
    a2 = schedule_fa.get("DtlsForeignCustodialAcc", [])
    print(f"Calendar year {args.year}  (1 Jan {args.year} - 31 Dec {args.year})")
    print(f"  Table A3 rows (foreign equity/debt) : {len(a3)}")
    print(f"  Table A2 rows (custodial accounts)  : {len(a2)}")
    print(f"  peak basis                          : {args.peak_basis}")
    print(f"  JSON                                : {args.out}")
    print(f"  audit trail                         : {report_path}")
    print(f"  CG / OS figures                     : {summary_path}")
    if a3:
        print(f"  A3 peak total                       : "
              f"INR {sum(r['PeakBalanceDuringPeriod'] for r in a3):,}")
        print(f"  A3 closing total                    : "
              f"INR {sum(r['ClosingBalance'] for r in a3):,}")
    if cash:
        print(f"  cash added to A2                    : "
              f"INR {sum(c.peak_inr for c in cash.values()):,} peak, "
              f"INR {sum(c.closing_inr for c in cash.values()):,} closing")
    elif not args.no_a2:
        print(f"  cash added to A2                    : none "
              f"(no rows for {args.year} in {cash_path}) -- Table A2 counts securities "
              f"only and understates any account that held uninvested cash")
    if schema_errors:
        print(f"\nSCHEMA VALIDATION FAILED ({validated_what}), "
              f"{len(schema_errors)} error(s):")
        for err in schema_errors[:25]:
            print(f"  - {err}")
        if len(schema_errors) > 25:
            print(f"  ... and {len(schema_errors) - 25} more")
        print("\nDo not import this file until these are fixed.")
        return 1
    next_steps = (
        "\nNext: import into a FRESH copy of the utility (importing twice leaves "
        "undeletable blank rows), and set Part B-TTI item 19 to \"Yes\" so the return "
        "is valid under rule 746."
    )
    if not args.no_validate and not skip_reason:
        print(f"\nSchema validation PASSED against the official ITD schema "
              f"({validated_what}).")
        print(f"  schema: {schema_path}")
        print(next_steps)
        return 0

    # Print the next steps *before* the warning so the warning is the last thing on screen.
    # Loud, because silently-unvalidated output is the failure mode that matters: the file
    # looks finished, imports into the utility without complaint, and is rejected at the
    # portal after the evening's work is done.
    print(next_steps)
    print()
    print("!" * 78)
    print("!! SCHEMA VALIDATION WAS SKIPPED -- THIS OUTPUT IS UNVERIFIED")
    print("!" * 78)
    print()
    if skip_reason:
        print(skip_reason)
    else:
        print("--no-validate was given, so nothing has checked that the ITD will accept "
              "this file.\nRe-run without --no-validate before you file.")
    print()
    print("!" * 78)
    print(f"!! {os.path.basename(args.out)} was written, but nothing has checked that "
          f"the ITD will accept it.")
    print("!" * 78)
    return 0


def _report_splits(scan_result, basis: str | None) -> None:
    """Say what was found even on the success path, so a silent adjustment is visible."""
    if not scan_result:
        return
    for gap in scan_result.unchecked:
        print(f"warning: incomplete split check -- {gap}", file=sys.stderr)
    if not scan_result.affected:
        return
    events = sorted({(e.ticker, e.date, e.label)
                     for exp in scan_result.exposures for e in exp.events})
    print("Stock splits affecting this data:")
    for ticker, day, label in events:
        print(f"  {ticker}: {label} split effective {day}")
    if basis == splits.SPLIT_BASIS_HISTORICAL:
        print(f"  --split-basis historical: {len(scan_result.exposures)} transaction(s) "
              f"restated onto the post-split basis. Check the audit CSV quantities.")
    else:
        print(f"  --split-basis current: quantities taken as already restated; "
              f"{len(scan_result.exposures)} transaction(s) pre-date a split.")


def _write_audit(path: str, rows, year: int, cash=None) -> None:
    """Per-row working, so every number in the JSON can be traced back by hand."""
    columns = [
        "ticker", "lot_id", "account_id", "acq_kind", "acquire_date",
        "initial_qty", "initial_price_usd", "initial_fx", "initial_value_inr",
        "peak_date", "peak_qty", "peak_price_usd", "peak_fx", "peak_fx_date",
        "peak_value_inr",
        "closing_qty", "closing_price_usd", "closing_fx", "closing_value_inr",
        "dividends_usd", "gross_credited_inr",
        "proceeds_usd", "gross_proceeds_inr",
        "notes",
        # Provenance. Every figure on the row traces back to the export row it was read
        # from, so a query years later is answered from this file rather than from a
        # reconstruction of which download the numbers came out of.
        "acquisition_source", "proceeds_sources", "dividend_sources",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for r in sorted(rows, key=lambda x: (x.ticker, x.acquire_date)):
            writer.writerow({
                "ticker": r.ticker, "lot_id": r.lot_id, "account_id": r.account_id,
                "acq_kind": r.acq_kind, "acquire_date": r.acquire_date.isoformat(),
                "initial_qty": r.initial_qty, "initial_price_usd": r.initial_price_usd,
                "initial_fx": r.initial_fx, "initial_value_inr": r.initial_value_inr,
                "peak_date": r.peak_date.isoformat() if r.peak_date else "",
                "peak_qty": r.peak_qty, "peak_price_usd": r.peak_price_usd,
                "peak_fx": r.peak_fx,
                "peak_fx_date": r.peak_fx_date.isoformat() if r.peak_fx_date else "",
                "peak_value_inr": r.peak_value_inr,
                "closing_qty": r.closing_qty,
                "closing_price_usd": r.closing_price_usd,
                "closing_fx": r.closing_fx, "closing_value_inr": r.closing_value_inr,
                "dividends_usd": r.dividends_usd,
                "gross_credited_inr": r.gross_credited_inr,
                "proceeds_usd": r.proceeds_usd,
                "gross_proceeds_inr": r.gross_proceeds_inr,
                "notes": "; ".join(r.notes),
                "acquisition_source": r.source_ref,
                "proceeds_sources": "; ".join(r.proceeds_source_refs),
                "dividend_sources": "; ".join(r.dividend_source_refs),
            })
        # Cash rides in the same audit file: it is part of the Table A2 totals, so it
        # has to be traceable from the same place as the securities behind them.
        for value in sorted((cash or {}).values(), key=lambda c: c.account_id):
            writer.writerow({
                "ticker": "(cash)", "lot_id": "", "account_id": value.account_id,
                "acq_kind": "CASH", "acquire_date": "",
                "peak_date": value.peak_date.isoformat() if value.peak_date else "",
                "peak_qty": value.peak_usd, "peak_price_usd": 1,
                "peak_fx": value.peak_fx, "peak_value_inr": value.peak_inr,
                "closing_qty": value.closing_usd, "closing_price_usd": 1,
                "closing_fx": value.closing_fx, "closing_value_inr": value.closing_inr,
                "notes": "; ".join(value.notes),
                "acquisition_source": value.source_ref,
            })


# ---------------------------------------------------------------- unlock

def cmd_unlock(args) -> int:
    """Decrypt statements without the password being seen by anyone, including an agent.

    Every line this prints is a variable name or a file path. No branch of this function
    can print a credential value: `Credential` withholds it from repr and str, and
    `unlock.scrub` is applied to any message that came back from the decryption path.
    """
    try:
        resolved = unlock.resolve_environment(args.env_file)
    except unlock.UnlockError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    if args.list_credentials:
        print("Credentials visible to itr-prep (values are never shown):")
        print()
        for line in unlock.describe_credentials(resolved):
            print(f"  {line}")
        print()
        print(f"Declare these in {args.env_file}; see .env.example. Any variable named")
        print(f"{unlock.PASSWORD_PREFIX}<LABEL> is tried against every file, so a document")
        print("never needs its password in its filename.")
        return 0

    if not args.input:
        print("\nunlock needs --input: a file, or a folder of them. "
              "Use --list-credentials to check what is declared first.\n",
              file=sys.stderr)
        return 2

    tried = unlock.candidates(resolved)
    declared = [c.name for c in tried if c.name != "(no password)"]
    if not declared:
        print(f"\nNo credential is declared in {args.env_file} or the environment, so only "
              f"unencrypted\nfiles can be copied. Set {unlock.PAN_VAR} and "
              f"{unlock.DOB_VAR}, or a {unlock.PASSWORD_PREFIX}<LABEL> variable. "
              f"See .env.example.\n", file=sys.stderr)

    out_dir = (
        args.out_dir
        or os.environ.get("ITRPREP_UNLOCK_DIR")
        or resolved.get("ITRPREP_UNLOCK_DIR", ("", ""))[0]
        or unlock.DEFAULT_OUT_DIR
    )

    try:
        sources = unlock.collect_inputs(args.input)
    except unlock.UnlockError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1
    if not sources:
        print(f"\nNothing to unlock in {args.input}. Supported: "
              f"{', '.join(unlock.SUPPORTED_SUFFIXES)}\n", file=sys.stderr)
        return 1

    print(f"Credentials in play: {len(declared)} declared "
          f"({', '.join(declared) if declared else 'none'})")
    print(f"Decrypted copies go to {out_dir}, owner-only, mode 0600.")
    print()

    results = [unlock.unlock_file(source, out_dir, tried) for source in sources]
    for result in results:
        name = os.path.basename(result.source)
        if not result.ok:
            print(f"  FAILED  {name}: {result.error}")
        elif result.was_encrypted:
            print(f"  opened  {name}  -> {result.target}   "
                  f"(credential: {result.credential_name})")
        else:
            print(f"  copied  {name}  -> {result.target}   (was not encrypted)")

    failed = [r for r in results if not r.ok]
    print()
    print(f"{len(results) - len(failed)} of {len(results)} available; "
          f"{len(failed)} failed.")
    if failed:
        print()
        print("A failure above names the credential VARIABLES that were tried, never a")
        print(f"value. Correct the value in {args.env_file} and run this again -- do not "
              f"paste a")
        print("password into a terminal, a chat, or a filename.")
    print()
    print("These copies are decrypted personal documents. Delete them when you are done:")
    print(f"  rm -rf {out_dir}")
    return 1 if failed else 0


# ---------------------------------------------------------------- rules

def cmd_rules(args) -> int:
    """Show where every statutory figure came from, without running anything."""
    try:
        registry = rules.load(args.assessment_year or None)
    except rules.RulesError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    print(f"rules/{os.path.basename(registry.path)}")
    print(f"  assessment year   {registry.assessment_year}"
          f"   (FY {registry.financial_year}, "
          f"Schedule FA calendar {registry.calendar_year})")
    print(f"  last verified     {registry.verified_on}")
    print()
    print(registry.source_policy)
    print()

    entries = registry.annual_entries() if args.annual_only else list(
        registry.entries.values()
    )
    for entry in sorted(entries, key=lambda e: (e.review, e.key)):
        flag = "CONTESTED " if entry.contested else ""
        print(f"{entry.key}")
        print(f"  value          {entry.value!r}")
        print(f"  review         {flag}{entry.review}"
              + (f", stated for AY {entry.applies_to}"
                 if entry.applies_to != rules.APPLIES_TO_ALL else ""))
        print(f"  verified       {entry.verified_on}")
        print(f"  authority      {entry.statute}")
        for line in entry.source_lines():
            print(f"  source         {line}")
        if entry.is_annual:
            print(f"  re-check       {entry.check}")
        print()

    annual = registry.annual_entries()
    print(f"{len(registry.entries)} entries, {len(annual)} of them marked annual and "
          f"needing re-verification")
    print("before this registry is used for a later assessment year. The checklist is "
          "docs/ANNUAL-REVIEW.md.")
    return 0


# ---------------------------------------------------------------- import

def cmd_import(args) -> int:
    """Thin wrapper: the COM driver is a standalone script so it stays runnable alone."""
    # Answered here as well as in the driver, so `itr-prep import` on a Mac says what is
    # wrong instead of spawning a subprocess to say it.
    try:
        host.require()
    except host.UnsupportedHost as exc:
        print(f"\nCANNOT IMPORT ON THIS HOST\n\n{exc}\n", file=sys.stderr)
        return 2
    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "import_to_utility.py",
    )
    if not os.path.exists(script):
        print(f"import driver missing: {script}", file=sys.stderr)
        return 2
    argv = [
        sys.executable, script,
        "--json", args.json, "--utility", args.utility, "--year", str(args.year),
        "--workdir", args.workdir, "--timeout", str(args.timeout),
    ]
    if args.audit:
        argv += ["--audit", args.audit]
    if args.label:
        argv += ["--label", args.label]
    if args.name:
        argv += ["--name", args.name]
    if args.no_save:
        argv.append("--no-save")
    if args.keep_temp:
        argv.append("--keep-temp")
    if args.verbose:
        argv.append("--verbose")
    return subprocess.call(argv)


# ---------------------------------------------------------------- run

# Which account in accounts.csv a detected broker belongs to. Matched against
# institution_name, because that is where the broker's identity actually lives -- the
# account_id is a free-form key the user chose.
BROKER_INSTITUTION_HINTS = {
    "etrade": ("e*trade", "etrade", "morgan stanley", "stockplan", "shareworks"),
    "fidelity": ("fidelity",),
    "indmoney": ("drivewealth", "indmoney"),
}

TABLE_SUFFIXES = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm")


def _banner(step: int, total: int, title: str) -> None:
    print()
    print("=" * 78)
    print(f"STAGE {step}/{total}  {title}")
    print("=" * 78)


def _stop(step: int, title: str, detail: str) -> int:
    print()
    print("=" * 78)
    print(f"STOPPED at stage {step} ({title})")
    print("=" * 78)
    print()
    print(detail.rstrip())
    print()
    print("Nothing further was run. Fix the above and re-run the same command; each "
          "stage is idempotent.")
    return 1


def _resolve_account(broker: str, accounts: dict, overrides: dict) -> str | None:
    if broker in overrides:
        return overrides[broker]
    hints = BROKER_INSTITUTION_HINTS.get(broker, ())
    matches = [
        account_id for account_id, account in accounts.items()
        if any(h in account.institution_name.lower() for h in hints)
    ]
    return matches[0] if len(matches) == 1 else None


def cmd_run(args) -> int:
    total = 5
    paths = _work_paths(args.work)
    out_path = args.out or os.path.join("out", f"schedule_fa_{args.year}.json")

    account_overrides = {}
    for pair in args.account or []:
        if "=" not in pair:
            print(f"--account expects BROKER=ACCOUNT_ID, got {pair!r}", file=sys.stderr)
            return 1
        broker, _, account_id = pair.partition("=")
        account_overrides[broker.strip().lower()] = account_id.strip()

    # -- 1: exchange rates ---------------------------------------------------
    _banner(1, total, "SBI exchange rates")
    need_fx = True
    if os.path.exists(args.fx_cache):
        try:
            fx = FxRates.load(args.fx_cache)
            fx.assert_covers_year(args.year)
            need_fx = False
            print(f"Cache already covers {args.year}: {args.fx_cache}")
            print("Skipping the download.")
        except FxError as exc:
            print(f"Cache present but unusable for {args.year}: {exc}")
    else:
        print(f"No cache at {args.fx_cache}.")
    if need_fx:
        if args.offline:
            return _stop(1, "SBI exchange rates",
                         "--offline was requested but the rate cache does not cover "
                         f"{args.year}. Re-run without --offline, or run "
                         "`itr-prep fx-update` once with network access.")
        print("Downloading SBI TT-buy rates...")
        try:
            count, first, last = FxRates.update(args.fx_cache)
        except Exception as exc:  # noqa: BLE001 -- network
            return _stop(1, "SBI exchange rates", f"FX download failed: {exc}")
        print(f"Cached {count} rates ({first} to {last}).")

    # -- 2: normalize the drop folder ---------------------------------------
    _banner(2, total, "broker exports -> transactions.csv")
    if not args.drop:
        print("No --drop folder given, so Stage 1 normalization is skipped.")
        print(f"Using {paths['transactions']} as it stands.")
    else:
        code = _run_normalize_drop(args, paths, account_overrides)
        if code:
            return code

    # -- 3: preflight --------------------------------------------------------
    _banner(3, total, "preflight checks")
    prices = PriceStore(
        args.price_cache,
        overrides_path=(
            paths["overrides"] if os.path.exists(paths["overrides"]) else None
        ),
        offline=args.offline,
    )
    try:
        years = threshold.parse_years(args.years)
    except DataError as exc:
        return _stop(3, "preflight checks", str(exc))
    report = doctor.run_checks(
        paths, years=years, prices=prices, fx_cache=args.fx_cache,
        offline=args.offline,
    )
    print(doctor.render(report, args.work, years))
    if report.errors:
        return _stop(
            3, "preflight checks",
            f"{len(report.errors)} error(s) above must be fixed before the numbers "
            "mean anything. Re-run `itr-prep doctor --work "
            f"{args.work}` after each fix to see the remaining list.",
        )

    # -- 4: threshold report -------------------------------------------------
    _banner(4, total, f"Rs 20 lakh threshold report ({args.years})")
    thr_args = argparse.Namespace(
        years=args.years, work=args.work, transactions="", issuers="", accounts="",
        cash="", overrides="", out=os.path.join(args.work, "threshold_report.txt"),
        peak_basis=args.peak_basis, split_basis=args.split_basis,
        offline=args.offline, fx_cache=args.fx_cache, price_cache=args.price_cache,
    )
    if cmd_threshold(thr_args):
        return _stop(
            4, "threshold report",
            "The threshold report could not be produced. If it stopped on a stock "
            "split, re-run with --split-basis current or --split-basis historical "
            "(the message above says which your data looks like).",
        )

    # -- 5: build ------------------------------------------------------------
    _banner(5, total, f"Schedule FA for calendar {args.year}")
    build_args = argparse.Namespace(
        year=args.year, work=args.work, transactions="", issuers="", accounts="",
        overrides="", cash="", out=out_path, format=args.format,
        merge_into=args.merge_into, peak_basis=args.peak_basis,
        split_basis=args.split_basis, no_a2=args.no_a2, offline=args.offline,
        fx_cache=args.fx_cache, price_cache=args.price_cache, schema=args.schema,
        no_validate=args.no_validate,
    )
    if cmd_build(build_args):
        return _stop(5, "build", "The build failed; see the message above.")

    print()
    print("=" * 78)
    print("PIPELINE COMPLETE")
    print("=" * 78)
    print(f"  Schedule FA JSON   {out_path}")
    print(f"  audit trail        {os.path.splitext(out_path)[0]}_audit.csv")
    print(f"  CG / OS figures    {os.path.splitext(out_path)[0]}_other_schedules.txt")
    print(f"  threshold report   {os.path.join(args.work, 'threshold_report.txt')}")
    print()
    print("Next, import it into the Excel utility:")
    print(f"  itr-prep import --year {args.year} --json {out_path} \\")
    print("                --utility '/mnt/c/path/to/pristine/ITR2_AY_26-27_V1.2.xlsm'")
    return 0


def _run_normalize_drop(args, paths, account_overrides) -> int:
    """Detect and normalize every table in the drop folder."""
    drop = os.path.expanduser(args.drop)
    if not os.path.isdir(drop):
        return _stop(2, "broker exports", f"--drop folder not found: {drop}")

    candidates = sorted(
        os.path.join(drop, name) for name in os.listdir(drop)
        if name.lower().endswith(TABLE_SUFFIXES) and not name.startswith("~$")
    )
    if not candidates:
        return _stop(
            2, "broker exports",
            f"No CSV/TSV/XLSX files in {drop}.\n"
            "Put your E*TRADE, Fidelity and INDmoney exports there. Filenames do not "
            "matter -- each file is classified by its contents.",
        )

    try:
        accounts = intermediate.read_accounts(args.accounts or paths["accounts"])
    except DataError as exc:
        return _stop(2, "broker exports",
                     f"accounts.csv must be readable before exports can be matched to "
                     f"accounts:\n\n{exc}")

    print(f"Scanning {len(candidates)} file(s) in {drop}")
    print("Classification is by header content, never by filename.")
    print()
    detections = [adapters.detect(path) for path in candidates]

    unknown = [d for d in detections if not d.confident]
    print(f"{'file':<34} {'matched':<10} {'score':>5}  evidence")
    print("-" * 78)
    for det in detections:
        name = os.path.basename(det.path)[:33]
        label = det.broker or "UNKNOWN"
        why = "; ".join(det.evidence[:3]) if det.evidence else det.reason
        print(f"{name:<34} {label:<10} {det.score:>5}  {why[:60]}")
    print()

    if unknown:
        detail = "\n".join(
            f"  {os.path.basename(d.path)}: {d.reason}" for d in unknown
        )
        return _stop(
            2, "broker exports",
            f"{len(unknown)} file(s) could not be classified:\n\n{detail}\n\n"
            "Rather than guess -- a misclassified export would silently produce wrong "
            "rows -- normalize these by hand and re-run without them in the folder:\n\n"
            "  itr-prep normalize --broker etrade --input <file> "
            "--account-id <id> --out "
            f"{paths['transactions']} --append\n\n"
            "Non-transaction files (statements, PDFs saved as CSV) should simply be "
            "moved out of the drop folder.",
        )

    by_broker: dict[str, list[str]] = {}
    for det in detections:
        by_broker.setdefault(det.broker, []).append(det.path)

    resolved: list[tuple[str, str, str]] = []
    for broker, files in sorted(by_broker.items()):
        account_id = _resolve_account(broker, accounts, account_overrides)
        if not account_id:
            hits = [
                a.account_id for a in accounts.values()
                if any(h in a.institution_name.lower()
                       for h in BROKER_INSTITUTION_HINTS.get(broker, ()))
            ]
            problem = (
                f"{len(hits)} accounts match" if hits
                else "no account in accounts.csv names that broker"
            )
            return _stop(
                2, "broker exports",
                f"Cannot tell which account the {broker} export belongs to: {problem}.\n\n"
                f"accounts.csv has: "
                + ", ".join(f"{a.account_id} ({a.institution_name})"
                            for a in accounts.values())
                + f"\n\nEither fix institution_name so it names the broker, or say so "
                  f"explicitly:\n\n  --account {broker}=<account_id>",
            )
        for path in files:
            resolved.append((broker, path, account_id))

    # Normalize everything in memory and write once. Two exports can map to the same
    # account -- E*TRADE's Benefit History and its Gains & Losses are the normal case --
    # and writing per file would make the second replace the first's rows.
    fresh: list = []
    warnings: list[str] = []
    results: list = []
    for broker, path, account_id in resolved:
        try:
            result = adapters.normalize_report(path, broker, account_id)
        except DataError as exc:
            return _stop(2, "broker exports",
                         f"{os.path.basename(path)} (matched to {broker}):\n\n{exc}")
        results.append(result)
        print(f"  {os.path.basename(path):<34} {len(result.transactions):>4} rows -> "
              f"{account_id}")
        print(adapters.render_report(result))
        fresh.extend(result.transactions)
        warnings.extend(result.warnings)

    touched = {account_id for _, _, account_id in resolved}
    kept: list = []
    if os.path.exists(paths["transactions"]):
        try:
            existing = intermediate.read_transactions(paths["transactions"])
            kept = [t for t in existing if t.account_id not in touched]
        except DataError:
            kept = []
    intermediate.write_transactions(paths["transactions"], kept + fresh)

    print()
    print(f"Wrote {len(fresh)} transactions for {len(touched)} account(s) to "
          f"{paths['transactions']}"
          + (f", keeping {len(kept)} row(s) for other accounts" if kept else ""))
    if warnings:
        print(f"\n{len(warnings)} adapter warning(s):")
        for warning in warnings[:25]:
            print(f"  - {warning}")
        if len(warnings) > 25:
            print(f"  ... and {len(warnings) - 25} more")
    print("\nReview transactions.csv before trusting the output. Sales, vest FMVs and "
          "dividend withholding are what brokers export most oddly.")
    if any(r.dropped for r in results) and not args.allow_dropped_rows:
        _dropped_rows_banner(results)
        return _stop(
            2, "broker exports",
            "Rows the brokers exported were not imported (listed above). Nothing "
            "downstream was run, because every later stage would silently inherit the "
            "gap.",
        )
    return 0


# ---------------------------------------------------------------- doctor

def cmd_doctor(args) -> int:
    paths = _work_paths(args.work)
    years = None
    if args.years:
        try:
            years = threshold.parse_years(args.years)
        except DataError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    prices = None
    if not args.no_prices:
        overrides = args.overrides or paths["overrides"]
        prices = PriceStore(
            args.price_cache,
            overrides_path=overrides if os.path.exists(overrides) else None,
            offline=args.offline,
        )

    report = doctor.run_checks(
        paths, years=years, prices=prices, fx_cache=args.fx_cache,
        offline=args.offline,
    )
    # run_checks derives the year span from the data when not told; recover it for the
    # summary line so the user sees which years were actually checked.
    effective = years
    if effective is None:
        try:
            txns = intermediate.read_transactions(paths["transactions"])
            effective = sorted({t.date.year for t in txns})
        except DataError:
            effective = []
    print(doctor.render(report, args.work, effective))
    return 1 if report.errors else 0


# ---------------------------------------------------------------- threshold

def cmd_threshold(args) -> int:
    paths = _work_paths(args.work)
    try:
        years = threshold.parse_years(args.years)
        transactions = intermediate.read_transactions(
            args.transactions or paths["transactions"]
        )
        issuers = intermediate.read_issuers(args.issuers or paths["issuers"])
        accounts = intermediate.read_accounts(args.accounts or paths["accounts"])
        intermediate.cross_check(transactions, issuers, accounts)
        cash_balances = intermediate.read_cash_balances(args.cash or paths["cash"])
    except DataError as exc:
        print(f"\nInput data problem:\n\n{exc}\n", file=sys.stderr)
        return 1

    try:
        fx = FxRates.load(args.fx_cache)
        for year in years:
            fx.assert_covers_year(year)
    except FxError as exc:
        print(f"\nFX problem:\n\n{exc}\n", file=sys.stderr)
        return 1

    overrides = args.overrides or paths["overrides"]
    prices = PriceStore(
        args.price_cache,
        overrides_path=overrides if os.path.exists(overrides) else None,
        offline=args.offline,
    )

    try:
        # Splits are checked against the latest year in scope; the scan itself looks at
        # every year the data spans, so one call covers the whole report.
        transactions, split_scan = splits.apply(
            transactions, prices, max(years), args.split_basis
        )
        lots = positions.build_lots(transactions)
        report = threshold.compute(
            lots, transactions, years, prices, fx, accounts,
            cash_balances=cash_balances, peak_basis=args.peak_basis,
        )
    except (DataError, PriceError) as exc:
        print(f"\nComputation failed:\n\n{exc}\n", file=sys.stderr)
        return 1

    _report_splits(split_scan, args.split_basis)

    text = threshold.render(report)
    print(text)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.write("\n")
    csv_path = os.path.splitext(args.out)[0] + "_audit.csv"
    threshold.write_csv(report, csv_path)
    print(f"Written to {args.out}")
    print(f"Audit trail  {csv_path}")
    return 0


# ---------------------------------------------------------------- validate

def cmd_validate(args) -> int:
    with open(args.json, encoding="utf-8") as fh:
        document = json.load(fh)
    try:
        schema, schema_path = validate.load_schema(args.schema, year=args.year)
    except validate.SchemaError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Schema       {schema_path}")

    schedule_fa = (
        document.get("ITR", {}).get("ITR2", {}).get("ScheduleFA")
    )
    if schedule_fa is None:
        print(
            "This file has no ITR.ITR2.ScheduleFA node. If it is in the prefill "
            "(camelCase) format, that shape is not covered by the ITD's ITR-2 schema and "
            "cannot be validated against it.",
            file=sys.stderr,
        )
        return 1

    errors = validate.validate_schedule_fa(schedule_fa, schema)
    scope = "ScheduleFA subtree"
    if set(document.get("ITR", {}).get("ITR2", {})) - {"ScheduleFA"}:
        errors += validate.validate_full_document(document, schema)
        scope = "full ITR document"

    if errors:
        print(f"INVALID ({scope}) -- {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1
    a3 = len(schedule_fa.get("DtlsForeignEquityDebtInterest", []))
    a2 = len(schedule_fa.get("DtlsForeignCustodialAcc", []))
    print(f"VALID ({scope}). Table A3: {a3} rows, Table A2: {a2} rows.")
    return 0


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="itr-prep",
        description="Broker exports -> Schedule FA JSON for the ITD ITR-2 Excel utility.",
    )
    parser.add_argument("--version", action="version", version=f"itr-prep {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="write intermediate CSV templates")
    p_init.add_argument("--work", default="work", help="working directory")
    p_init.add_argument("--force", action="store_true", help="overwrite existing files")
    p_init.set_defaults(func=cmd_init)

    p_fx = sub.add_parser("fx-update", help="download and cache SBI TT-buy rates")
    p_fx.add_argument("--fx-cache", default=DEFAULT_FX_CACHE)
    p_fx.set_defaults(func=cmd_fx_update)

    p_norm = sub.add_parser("normalize", help="broker export -> transactions.csv")
    p_norm.add_argument("--broker", required=True,
                        choices=sorted(adapters.PROFILES))
    p_norm.add_argument("--input", required=True, help="the broker's export file")
    p_norm.add_argument("--account-id", required=True,
                        help="must match an account_id in accounts.csv")
    p_norm.add_argument("--out", default=os.path.join("work", "transactions.csv"))
    p_norm.add_argument("--default-ticker", default="",
                        help="for single-stock plan exports with no symbol column")
    p_norm.add_argument("--acq-kind", default="",
                        choices=["", "RSU_VEST", "ESPP", "OPEN_MARKET", "DRIP", "OTHER"],
                        help="for rows whose own type text does not say. A row typed "
                             "'ESPP Purchase' is read as ESPP whatever this says, since "
                             "one stock-plan export mixes plan types")
    p_norm.add_argument("--append", action="store_true",
                        help="keep rows already in --out for other accounts")
    p_norm.add_argument("--allow-dropped-rows", action="store_true",
                        help="exit 0 even when rows in the export could not be read. "
                             "Only after checking each one is genuinely not a "
                             "transaction -- a dropped vest understates Schedule FA.")
    p_norm.set_defaults(func=cmd_normalize)

    p_build = sub.add_parser("build", help="compute Schedule FA and emit JSON")
    p_build.add_argument("--year", type=int, required=True,
                         help="reporting CALENDAR year, e.g. 2025 for AY 2026-27")
    p_build.add_argument("--work", default="work")
    p_build.add_argument("--transactions", default="")
    p_build.add_argument("--issuers", default="")
    p_build.add_argument("--accounts", default="")
    p_build.add_argument("--overrides", default="")
    p_build.add_argument("--out", required=True, help="output JSON path")
    p_build.add_argument("--format", default=emit.FORMAT_ITR, choices=emit.FORMATS,
                         help="itr = for 'Import Draft/JSON'; prefill = for 'Import "
                              "Prefill'. Default itr.")
    p_build.add_argument("--merge-into", default="",
                         help="inject ScheduleFA into this existing return JSON so one "
                              "import restores everything")
    p_build.add_argument("--peak-basis", default=positions.PEAK_BASIS_USD,
                         choices=positions.PEAK_BASES,
                         help="usd = peak the USD value then convert at that date's TT "
                              "rate (ITD's literal wording, default); inr = maximise the "
                              "INR product directly (more conservative)")
    p_build.add_argument("--cash", default="",
                         help="cash_balances.csv (default <work>/cash_balances.csv)")
    p_build.add_argument("--split-basis", default=None, choices=splits.SPLIT_BASES,
                         help="declare how quantities are stated where a holding spans "
                              "a stock split. current = already restated post-split; "
                              "historical = as printed at the time, restate them. "
                              "Omit and the build STOPS if a split is found.")
    p_build.add_argument("--no-a2", action="store_true",
                         help="omit Table A2 custodial account rows")
    p_build.add_argument("--offline", action="store_true",
                         help="never hit the network; use cached prices and overrides")
    p_build.add_argument("--fx-cache", default=DEFAULT_FX_CACHE)
    p_build.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    p_build.add_argument("--schema", default="", help=_SCHEMA_HELP)
    p_build.add_argument("--no-validate", action="store_true")
    p_build.set_defaults(func=cmd_build)

    p_imp = sub.add_parser(
        "import",
        help="[Windows or WSL only] import the JSON into a fresh copy of the Excel "
             "utility and verify every cell that landed",
    )
    p_imp.add_argument("--json", required=True)
    p_imp.add_argument("--utility", required=True,
                       help="the PRISTINE .xlsm; it is copied, never modified")
    p_imp.add_argument("--year", type=int, required=True)
    p_imp.add_argument("--audit", default="",
                       help="audit CSV (default <json stem>_audit.csv)")
    p_imp.add_argument("--workdir", default="C:\\temp\\itrprep",
                       help="folder for the working copy, as a WINDOWS path; must be an "
                            "Excel Trusted Location or macros will not run")
    p_imp.add_argument("--name", default="")
    p_imp.add_argument("--label", default="Non-Business",
                       help="Purview sensitivity label applied on save; a managed "
                            "tenant blocks Save until one is chosen. Do not pick an "
                            "encrypting label -- the portal cannot read the file.")
    p_imp.add_argument("--no-save", action="store_true")
    p_imp.add_argument("--keep-temp", action="store_true")
    p_imp.add_argument("--timeout", type=int, default=900)
    p_imp.add_argument("--verbose", action="store_true")
    p_imp.set_defaults(func=cmd_import)

    p_run = sub.add_parser(
        "run",
        help="one command: rates, normalize a drop folder, preflight, threshold, build",
    )
    p_run.add_argument("--year", type=int, required=True,
                       help="reporting CALENDAR year, e.g. 2025 for AY 2026-27")
    p_run.add_argument("--drop", default="",
                       help="folder of broker exports; each file is classified by its "
                            "header content, not its filename. Omit to use the "
                            "transactions.csv you already have.")
    p_run.add_argument("--work", default="work")
    p_run.add_argument("--accounts", default="")
    p_run.add_argument("--account", action="append", default=[],
                       metavar="BROKER=ACCOUNT_ID",
                       help="force which account an export belongs to, e.g. "
                            "--account etrade=etrade_stockplan. Repeatable.")
    p_run.add_argument("--allow-dropped-rows", action="store_true",
                       help="continue past rows in an export that could not be read. "
                            "Only after checking each one is genuinely not a "
                            "transaction -- a dropped vest understates Schedule FA.")
    p_run.add_argument("--out", default="",
                       help="output JSON (default out/schedule_fa_<year>.json)")
    p_run.add_argument("--years", default="2022-2025",
                       help="years for the threshold report")
    p_run.add_argument("--format", default=emit.FORMAT_ITR, choices=emit.FORMATS)
    p_run.add_argument("--merge-into", default="")
    p_run.add_argument("--peak-basis", default=positions.PEAK_BASIS_USD,
                       choices=positions.PEAK_BASES)
    p_run.add_argument("--split-basis", default=None, choices=splits.SPLIT_BASES)
    p_run.add_argument("--no-a2", action="store_true")
    p_run.add_argument("--offline", action="store_true")
    p_run.add_argument("--fx-cache", default=DEFAULT_FX_CACHE)
    p_run.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    p_run.add_argument("--schema", default="", help=_SCHEMA_HELP)
    p_run.add_argument("--no-validate", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_doc = sub.add_parser(
        "doctor",
        help="preflight: check work/ and report everything actionable in one pass",
    )
    p_doc.add_argument("--work", default="work")
    p_doc.add_argument("--years", default="",
                       help="years to check coverage for; default is the span of your "
                            "transaction dates")
    p_doc.add_argument("--overrides", default="")
    p_doc.add_argument("--no-prices", action="store_true",
                       help="skip the checks that need price data (splits, price sanity)")
    p_doc.add_argument("--offline", action="store_true")
    p_doc.add_argument("--fx-cache", default=DEFAULT_FX_CACHE)
    p_doc.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    p_doc.set_defaults(func=cmd_doctor)

    p_thr = sub.add_parser(
        "threshold",
        help="aggregate foreign asset value per year vs the Rs 20 lakh s.43 threshold",
    )
    p_thr.add_argument("--years", default="2022-2025",
                       help="calendar years to report, e.g. 2022-2025 or 2023,2025")
    p_thr.add_argument("--work", default="work")
    p_thr.add_argument("--transactions", default="")
    p_thr.add_argument("--issuers", default="")
    p_thr.add_argument("--accounts", default="")
    p_thr.add_argument("--cash", default="")
    p_thr.add_argument("--overrides", default="")
    p_thr.add_argument("--out", default=os.path.join("work", "threshold_report.txt"))
    p_thr.add_argument("--peak-basis", default=positions.PEAK_BASIS_USD,
                       choices=positions.PEAK_BASES,
                       help="basis noted for the Schedule FA rows; the report always "
                            "shows both peak variants regardless")
    p_thr.add_argument("--split-basis", default=None, choices=splits.SPLIT_BASES)
    p_thr.add_argument("--offline", action="store_true")
    p_thr.add_argument("--fx-cache", default=DEFAULT_FX_CACHE)
    p_thr.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    p_thr.set_defaults(func=cmd_threshold)

    p_unlock = sub.add_parser(
        "unlock",
        help="write decrypted copies of password-protected statements, reading the "
             "password from .env so it is never seen or typed",
    )
    p_unlock.add_argument("--input", default="",
                          help="an encrypted file, or a folder of them")
    p_unlock.add_argument("--out-dir", default="",
                          help=f"where decrypted copies go, each mode 0600. Default "
                               f"$ITRPREP_UNLOCK_DIR, else {unlock.DEFAULT_OUT_DIR}")
    p_unlock.add_argument("--env-file", default=unlock.ENV_FILENAME,
                          help=f"credentials file. Default {unlock.ENV_FILENAME}")
    p_unlock.add_argument("--list-credentials", action="store_true",
                          help="show which credential VARIABLES are set, and nothing "
                               "about their values")
    p_unlock.set_defaults(func=cmd_unlock)

    p_rules = sub.add_parser(
        "rules",
        help="print the cited rules registry: every statutory figure and its source",
    )
    p_rules.add_argument("--assessment-year", default="",
                         help="e.g. 2026-27. Default is the newest registry on disk.")
    p_rules.add_argument("--annual-only", action="store_true",
                         help="only the entries that must be re-verified each "
                              "assessment year")
    p_rules.set_defaults(func=cmd_rules)

    p_val = sub.add_parser("validate", help="validate a JSON against the ITD schema")
    p_val.add_argument("--json", required=True)
    p_val.add_argument("--schema", default="", help=_SCHEMA_HELP)
    p_val.add_argument("--year", type=int, default=None,
                       help="reporting calendar year, to pick that year's schema")
    p_val.set_defaults(func=cmd_validate)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
