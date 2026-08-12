"""Preflight checks on the working directory.

The point is to report *everything* actionable in one pass. The rest of the pipeline fails
on the first problem it hits, which is right for a build but wrong for preparation: a user
fixing one error at a time across three CSVs and five commands loses an afternoon. So every
check here collects findings instead of raising, and the command exits non-zero only at the
end.

Errors block a build. Warnings do not, but each one is something that will quietly make the
filed return wrong or incomplete if ignored -- an understated Table A2, a dividend with no
withholding, a vest priced nowhere near the market. They are worth reading.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from decimal import Decimal

from . import intermediate, positions, scope, splits
from .fx import FxError, FxRates
from .models import TXN_BUY, TXN_DIVIDEND, TXN_SELL, DataError
from .prices import PriceError

ERROR = "ERROR"
WARN = "WARN"
OK = "OK"

# Text the `init` templates stamp on their example rows. Filing these would disclose
# holdings that do not exist, so their presence is an error rather than a warning.
EXAMPLE_MARKERS = ("example row - delete me", "REPLACE-WITH-REAL")

# A recorded acquisition price this far from the market close on the same day is either a
# data error or a split-basis problem. The band is wide on purpose: an ESPP price carries a
# statutory discount off the lower of two dates and can legitimately sit well under the
# close, and a vest price is a day's FMV that need not equal it.
PRICE_SANE_LOW = Decimal("0.3")
PRICE_SANE_HIGH = Decimal("3.0")

# An employer stock plan vests on a schedule -- monthly, quarterly, or at worst annually.
# So an account holding RSU or ESPP acquisitions should show at least one acquisition per
# year it has been open. Fewer than that means acquisitions are missing, not that the plan
# was idle: an award that never vests produces no rows at all, not two.
STOCK_PLAN_MIN_ACQ_PER_YEAR = Decimal("1.0")
# Below this share of all transaction rows, an employer stock-plan account is suspiciously
# quiet: the README notes it is normally the account contributing the MOST rows.
STOCK_PLAN_TINY_SHARE = Decimal("0.10")
# Only compare shares once there are enough rows for a proportion to mean anything.
MAGNITUDE_MIN_ROWS = 20


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    hint: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    def add(self, severity, category, message, hint="") -> None:
        self.findings.append(Finding(severity, category, message, hint))

    def error(self, category, message, hint="") -> None:
        self.add(ERROR, category, message, hint)

    def warn(self, category, message, hint="") -> None:
        self.add(WARN, category, message, hint)

    def note(self, label: str) -> None:
        self.checked.append(label)

    @property
    def errors(self):
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == WARN]

    @property
    def ok(self) -> bool:
        return not self.errors


def run_checks(paths: dict, years=None, prices=None, fx_cache: str = "",
               offline: bool = False, allow_indian_securities: bool = False) -> Report:
    """Check everything that can be checked without building.

    `paths` carries the same keys `_work_paths` produces. `prices` may be None to skip the
    checks that need a price series (split exposure, price sanity).
    """
    report = Report()

    # -- the files themselves ------------------------------------------------
    transactions = _read_transactions(paths, report)
    issuers = _read(paths, "issuers", intermediate.read_issuers, report)
    accounts = _read(paths, "accounts", intermediate.read_accounts, report)
    cash = _read_cash(paths, report)

    if transactions is None:
        report.error(
            "input", "cannot continue without a readable transactions.csv",
            "run `itr-prep init --work <dir>` and fill it, or fix the errors above",
        )
        return report

    _check_example_rows(paths, transactions, accounts, report)

    if years is None:
        span = sorted({t.date.year for t in transactions})
        years = span or [dt.date.today().year - 1]
    years = sorted(set(years))

    _check_references(transactions, issuers, accounts, report)
    _check_indian_securities(transactions, issuers, allow_indian_securities, report)
    _check_account_magnitude(transactions, accounts, report)
    _check_duplicates(transactions, report)
    _check_dividends(transactions, report)
    _check_lots(transactions, report)
    _check_cash_coverage(transactions, accounts, cash, years, report)
    _check_fx(fx_cache, years, report)

    if prices is not None:
        _check_splits(transactions, prices, years, report)
        _check_price_sanity(transactions, prices, report)
        _check_price_coverage(transactions, prices, years, offline, report)
    else:
        report.warn(
            "prices", "price checks skipped (no price store available)",
            "run doctor without --no-prices to check splits and price sanity",
        )

    return report


# -- readers that collect instead of raising ---------------------------------

def _read_transactions(paths, report):
    path = paths["transactions"]
    if not os.path.exists(path):
        report.error("input", f"transactions.csv not found at {path}",
                     "run `itr-prep init --work <dir>` first")
        return None
    try:
        txns = intermediate.read_transactions(path)
        report.note(f"transactions.csv: {len(txns)} rows")
        return txns
    except DataError as exc:
        report.error("transactions.csv", str(exc))
        return None


def _read(paths, key, reader, report):
    path = paths[key]
    if not os.path.exists(path):
        report.error("input", f"{key}.csv not found at {path}",
                     "run `itr-prep init --work <dir>` first")
        return {}
    try:
        out = reader(path)
        report.note(f"{key}.csv: {len(out)} rows")
        return out
    except DataError as exc:
        report.error(f"{key}.csv", str(exc))
        return {}


def _read_cash(paths, report):
    path = paths.get("cash", "")
    if not path or not os.path.exists(path):
        return {}
    try:
        out = intermediate.read_cash_balances(path)
        report.note(f"cash_balances.csv: {len(out)} rows")
        return out
    except DataError as exc:
        report.error("cash_balances.csv", str(exc))
        return {}


# -- individual checks -------------------------------------------------------

def _check_example_rows(paths, transactions, accounts, report):
    """Runbook step 0.4 is easy to skip, and skipping it files invented holdings."""
    hits: list[str] = []
    for txn in transactions:
        blob = f"{txn.notes} {txn.lot_id}".lower()
        if any(m.lower() in blob for m in EXAMPLE_MARKERS):
            hits.append(f"{os.path.basename(txn.source_file)} line {txn.source_row}")
    for account in accounts.values():
        if any(m.lower() in account.account_number.lower() for m in EXAMPLE_MARKERS):
            hits.append(f"accounts.csv: account {account.account_id} has placeholder "
                        f"account_number {account.account_number!r}")
    # Scan the raw text of the remaining files too: an example row whose marker sits in a
    # column this tool does not model would otherwise slip through.
    for key in ("issuers", "cash"):
        path = paths.get(key, "")
        if not path or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            for lineno, line in enumerate(fh, start=1):
                if any(m.lower() in line.lower() for m in EXAMPLE_MARKERS):
                    hits.append(f"{os.path.basename(path)} line {lineno}")
    if hits:
        report.error(
            "example rows",
            f"{len(hits)} template example row(s) are still present: "
            + "; ".join(hits[:12])
            + ("; ..." if len(hits) > 12 else ""),
            "delete every row marked 'example row - delete me' and replace every "
            "REPLACE-WITH-REAL placeholder. Filing these would disclose holdings and "
            "account numbers that do not exist.",
        )
    else:
        report.note("no template example rows left")


def _check_references(transactions, issuers, accounts, report):
    missing_issuers = sorted({t.ticker for t in transactions} - set(issuers))
    if missing_issuers:
        report.error(
            "issuers.csv",
            "these tickers have no issuer row: " + ", ".join(missing_issuers),
            "every Table A3 row needs the ISSUING COMPANY's name, address, zip and "
            "nature -- Cisco Systems, not E*TRADE",
        )
    missing_accounts = sorted({t.account_id for t in transactions} - set(accounts))
    if missing_accounts:
        report.error(
            "accounts.csv",
            "these account_ids have no account row: " + ", ".join(missing_accounts),
        )
    unused = sorted(set(accounts) - {t.account_id for t in transactions})
    if unused:
        report.warn(
            "accounts.csv",
            "these accounts have no transactions: " + ", ".join(unused),
            "harmless if the account really was empty, but check for a typo in "
            "account_id -- a mismatch silently drops that broker from the return",
        )
    if not missing_issuers and not missing_accounts:
        report.note("every ticker and account_id resolves")


def _check_indian_securities(transactions, issuers, allowed, report):
    """An Indian mutual fund or equity in Schedule FA is a wrong filing, not a stray row.

    Reported here as well as in `intermediate.cross_check` so the user meets it at preflight
    rather than after a build. The full refusal is carried as the message, because every part
    of it -- what was detected, why it cannot be disclosed, what this tool does not do, what
    to do instead, and what the check cannot see -- is needed by whoever is being stopped.
    """
    hits = scope.find_indian_securities(transactions, issuers)
    if not hits:
        report.note("no holding looks like an Indian security")
        return
    if allowed:
        report.warn(
            "scope",
            f"{scope.ALLOW_FLAG} was given, so Indian-looking securities are being "
            f"disclosed in Schedule FA: " + scope.summarise(hits),
            "only correct if every one of these is genuinely a foreign security. An Indian "
            "asset in Schedule FA asserts a foreign holding you do not have.",
        )
        return
    report.error("scope", scope.refusal(hits))


def _check_account_magnitude(transactions, accounts, report):
    """Is any account contributing implausibly little?

    The check that was missing. A multi-section E*TRADE Benefit History was parsed against
    its first section's columns, so every later block was silently discarded and the
    employer stock-plan account arrived with 2 transactions out of 173. Nothing complained:
    the reference check only asks whether an account has *no* rows at all, so a set
    difference over account ids came out empty, and the two rows that did survive were
    individually plausible.

    Two shapes fire here, both anchored to what an employer stock plan cannot help doing:

      - it vests on a schedule, so an account holding RSU or ESPP acquisitions must show
        at least one acquisition per year it has existed;
      - RSU vests are frequent, so an account holding them is normally the largest
        contributor of rows (README, "Supported brokers"), not a rounding error.

    Both are deliberately anchored to stock-plan accounts. A genuinely small retail or
    ESPP-only account trips neither, so this does not fire on the ordinary case of one
    busy account alongside one quiet one.
    """
    if not transactions:
        return
    total_rows = len(transactions)
    by_account: dict[str, list] = {}
    for txn in transactions:
        by_account.setdefault(txn.account_id, []).append(txn)
    last_seen = max(t.date for t in transactions)
    biggest = max(len(v) for v in by_account.values())

    fired = False
    for account_id, rows in sorted(by_account.items()):
        acquisitions = sorted(
            (t for t in rows if t.txn_type == TXN_BUY), key=lambda t: t.date
        )
        kinds = {t.acq_kind for t in acquisitions}
        stock_plan = bool(kinds & {"RSU_VEST", "ESPP"}) or _looks_like_stock_plan(
            account_id, accounts, rows
        )
        if not stock_plan or not acquisitions:
            continue

        opened = _account_start(account_id, accounts, acquisitions[0].date)
        span_years = Decimal(max((last_seen - opened).days, 1)) / Decimal(365)
        rate = Decimal(len(acquisitions)) / span_years
        share = Decimal(len(rows)) / Decimal(total_rows)
        gap = _longest_gap(acquisitions)

        thin_cadence = rate < STOCK_PLAN_MIN_ACQ_PER_YEAR
        tiny_share = (
            "RSU_VEST" in kinds
            and total_rows >= MAGNITUDE_MIN_ROWS
            and share < STOCK_PLAN_TINY_SHARE
            and biggest >= 3 * len(rows)
        )
        if not thin_cadence and not tiny_share:
            continue
        fired = True
        detail = (
            f"account '{account_id}' looks like an employer stock-plan account "
            f"({', '.join(sorted(k for k in kinds if k)) or 'stock-plan institution'}) "
            f"but contributes only {len(acquisitions)} acquisition(s) "
            f"({len(rows)} row(s), {share:.1%} of all {total_rows}) across the "
            f"{span_years:.1f} year(s) since {opened}"
        )
        if gap:
            first, second, days = gap
            detail += (
                f". Its longest run with no acquisition is {first} to {second} "
                f"({days} days)"
            )
        report.warn(
            "account activity", detail,
            "an employer plan vests at least annually, and an RSU account is normally "
            "the LARGEST source of rows -- so this shape usually means acquisitions were "
            "never imported. Re-run normalize and read the per-section census: a "
            "multi-section Benefit History whose later blocks were dropped produces "
            "exactly this. Cross-check the count against Form 12BA item 17 and your "
            "vest schedule before filing; an understated Schedule FA is a Black Money "
            "Act s.43 exposure of Rs 10,00,000 per assessment year.",
        )
    if not fired:
        report.note("every account's row count is consistent with its activity")


def _looks_like_stock_plan(account_id, accounts, rows) -> bool:
    """Fall back to the institution name and the adapter's own row notes.

    Needed because `acq_kind` is blank on rows hand-filled before it was documented, and
    an account whose vests were all dropped may have no RSU row left to recognise it by.
    """
    hints = ("stockplan", "stock plan", "e*trade", "etrade", "morgan stanley",
             "shareworks", "netbenefits", "computershare", "benefit")
    account = accounts.get(account_id) if accounts else None
    haystack = f"{account_id} {account.institution_name if account else ''}".lower()
    if any(h in haystack for h in hints):
        return True
    plan_words = ("vest", "release", "espp", "restricted stock", "lapse",
                  "share deposit", "benefit history")
    return any(
        any(w in (t.notes or "").lower() for w in plan_words) for t in rows
    )


def _account_start(account_id, accounts, first_txn_date):
    """When the account began contributing rows.

    Prefers the declared `account_open_date`: an account open since 2022 with two 2025
    vests is the shape being looked for, and dating the span from its own first surviving
    row would hide exactly that.
    """
    account = accounts.get(account_id) if accounts else None
    raw = (account.account_open_date if account else "").strip()
    if raw:
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            pass
    return first_txn_date


def _longest_gap(acquisitions):
    """The widest window between consecutive acquisitions -- where rows went missing."""
    if len(acquisitions) < 2:
        return None
    worst = None
    for earlier, later in zip(acquisitions, acquisitions[1:]):
        days = (later.date - earlier.date).days
        if worst is None or days > worst[2]:
            worst = (earlier.date, later.date, days)
    return worst


def _check_duplicates(transactions, report):
    """`normalize --append` run twice against a renamed file duplicates its rows."""
    seen: dict[tuple, list[int]] = {}
    for txn in transactions:
        key = (txn.account_id, txn.ticker, txn.txn_type, txn.date,
               txn.quantity, txn.gross_usd)
        seen.setdefault(key, []).append(txn.source_row)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    if dupes:
        detail = "; ".join(
            f"{k[1]} {k[2]} {k[3]} qty={k[4]} on lines {', '.join(map(str, v))}"
            for k, v in list(dupes.items())[:8]
        )
        report.warn(
            "duplicates",
            f"{len(dupes)} transaction(s) appear more than once: {detail}"
            + ("; ..." if len(dupes) > 8 else ""),
            "identical rows can be genuine (two vests of the same size on one day) but "
            "are usually a double import. Duplicates inflate every Schedule FA figure.",
        )
    else:
        report.note("no duplicate transaction rows")


def _check_dividends(transactions, report):
    dividends = [t for t in transactions if t.txn_type == TXN_DIVIDEND]
    if not dividends:
        report.warn(
            "dividends",
            "no dividend rows at all",
            "correct only if none of your holdings paid a dividend. JNJ and most ETFs "
            "do, and a missing dividend understates both Table A3 and Schedule OS.",
        )
        return
    no_tax = [t for t in dividends if t.tax_withheld_usd <= 0]
    if no_tax:
        report.warn(
            "dividends",
            f"{len(no_tax)} of {len(dividends)} dividend row(s) have no withholding tax: "
            + ", ".join(f"{t.ticker} {t.date}" for t in no_tax[:8])
            + ("; ..." if len(no_tax) > 8 else ""),
            "US dividends to an Indian resident are normally withheld at 25% under the "
            "treaty. A zero here loses your Schedule TR foreign tax credit.",
        )
    zero_amount = [t for t in dividends if t.gross_usd <= 0]
    if zero_amount:
        report.error(
            "dividends",
            f"{len(zero_amount)} dividend row(s) have a zero gross amount: "
            + ", ".join(f"line {t.source_row}" for t in zero_amount[:8]),
        )
    if not no_tax and not zero_amount:
        report.note(f"{len(dividends)} dividend rows, all with amount and withholding")


def _check_lots(transactions, report):
    """Does every sale have shares to sell? This is build_lots' hardest failure."""
    try:
        lots = positions.build_lots(transactions)
        sells = [t for t in transactions if t.txn_type == TXN_SELL]
        report.note(
            f"{len(lots)} acquisition lots; {len(sells)} sale(s) all reconcile"
        )
    except DataError as exc:
        report.error("sale reconciliation", str(exc))


def _check_cash_coverage(transactions, accounts, cash, years, report):
    active: dict[int, set[str]] = {}
    for year in years:
        dec31 = dt.date(year, 12, 31)
        active[year] = {
            t.account_id for t in transactions if t.date <= dec31
        }
    gaps = []
    for year in years:
        for account_id in sorted(active.get(year, ())):
            if (account_id, year) not in cash:
                gaps.append(f"{account_id}/{year}")
    if gaps:
        report.warn(
            "cash_balances.csv",
            f"no cash balance for {len(gaps)} account-year(s): "
            + ", ".join(gaps[:12]) + ("; ..." if len(gaps) > 12 else ""),
            "Table A2 will count securities only for these, understating the account by "
            "whatever uninvested cash it held. Read the peak and 31 Dec cash off the "
            "broker statement and add a row per account per year.",
        )
    elif cash:
        report.note("every active account-year has a cash balance")


def _check_fx(fx_cache, years, report):
    if not fx_cache or not os.path.exists(fx_cache):
        report.error(
            "fx cache", f"no SBI rate cache at {fx_cache or '(unset)'}",
            "run `itr-prep fx-update`",
        )
        return
    try:
        fx = FxRates.load(fx_cache)
    except FxError as exc:
        report.error("fx cache", str(exc), "run `itr-prep fx-update`")
        return
    bad = []
    for year in years:
        try:
            fx.assert_covers_year(year)
        except FxError as exc:
            bad.append(str(exc))
    if bad:
        for message in bad:
            report.error("fx cache", message, "run `itr-prep fx-update`")
    else:
        report.note(f"SBI TT-buy rates cover {min(years)}-{max(years)}")


def _check_splits(transactions, prices, years, report):
    """Surface the basis decision now, not halfway through a build."""
    try:
        scan = splits.scan(transactions, prices, max(years))
    except Exception as exc:  # noqa: BLE001 -- advisory
        report.warn("splits", f"could not check for splits: {exc}")
        return
    for gap in scan.unchecked:
        report.warn("splits", f"incomplete split check -- {gap}")
    if not scan.affected:
        report.note("no stock split affects any holding")
        return
    events = sorted({(e.ticker, e.date, e.label)
                     for exp in scan.exposures for e in exp.events})
    votes = {e.verdict for e in scan.exposures if e.verdict != "unknown"}
    guess = votes.pop() if len(votes) == 1 else "historical"
    report.warn(
        "splits",
        "split(s) affect your holdings: "
        + "; ".join(f"{t} {lbl} on {d}" for t, d, lbl in events)
        + f" ({len(scan.exposures)} transaction(s) pre-date a split)",
        f"the build will STOP until you pass --split-basis. On the evidence your rows "
        f"look like '{guess}'. Confirm against a broker statement dated after the split: "
        f"if its share count matches your CSV you are on 'current'. Getting this wrong "
        f"is a factor-of-the-split-ratio error, not a rounding one.",
    )


def _check_price_sanity(transactions, prices, report):
    odd = []
    zero = []
    for txn in transactions:
        if txn.txn_type not in (TXN_BUY, TXN_SELL):
            continue
        if txn.price_usd <= 0:
            zero.append(txn)
            continue
        try:
            close, _ = prices.series(txn.ticker, txn.date.year).close_on(txn.date)
        except (PriceError, Exception):  # noqa: BLE001 -- advisory only
            continue
        if close <= 0:
            continue
        ratio = txn.price_usd / close
        if ratio < PRICE_SANE_LOW or ratio > PRICE_SANE_HIGH:
            odd.append((txn, close, ratio))
    if zero:
        report.error(
            "prices",
            f"{len(zero)} acquisition/sale row(s) have a zero or missing price: "
            + ", ".join(f"{t.ticker} {t.date} line {t.source_row}" for t in zero[:8]),
            "a vest must carry its vest-date fair market value and an ESPP purchase its "
            "actual purchase price -- these are the cost basis and cannot be blank",
        )
    if odd:
        report.warn(
            "prices",
            f"{len(odd)} row(s) priced far from that day's market close: "
            + "; ".join(
                f"{t.ticker} {t.date} recorded {t.price_usd} vs close {c} "
                f"({r:.2f}x)" for t, c, r in odd[:8]
            )
            + ("; ..." if len(odd) > 8 else ""),
            "check these against the statement. A clean multiple like 10x usually means a "
            "split basis problem; an odd ratio usually means a currency or per-lot/"
            "per-share mix-up.",
        )
    if not zero and not odd:
        report.note("every recorded price is close to that day's market close")


def _check_price_coverage(transactions, prices, years, offline, report):
    tickers = sorted({t.ticker for t in transactions})
    missing = []
    for ticker in tickers:
        for year in years:
            try:
                prices.series(ticker, year)
            except PriceError:
                missing.append(f"{ticker} {year}")
    if missing:
        severity = report.error if offline else report.warn
        severity(
            "price cache",
            f"no daily prices for {len(missing)} ticker-year(s): "
            + ", ".join(missing[:12]) + ("; ..." if len(missing) > 12 else ""),
            "run once with network access to warm the cache, or add rows to "
            "prices_override.csv (ticker,date,close_usd)",
        )
    else:
        report.note(
            f"daily prices cached for {len(tickers)} ticker(s) across "
            f"{min(years)}-{max(years)}"
        )


# -- rendering ---------------------------------------------------------------

def render(report: Report, work_dir: str, years) -> str:
    lines = [
        "=" * 78,
        f"PREFLIGHT CHECK -- {work_dir}",
        "=" * 78,
        "",
    ]
    if report.checked:
        lines.append("Checked:")
        lines += [f"  ok    {c}" for c in report.checked]
        lines.append("")

    if report.errors:
        lines.append(f"ERRORS ({len(report.errors)}) -- these block a build:")
        lines.append("")
        lines += _render_findings(report.errors)

    if report.warnings:
        lines.append(f"WARNINGS ({len(report.warnings)}) -- the build will run, "
                     f"but read these:")
        lines.append("")
        lines += _render_findings(report.warnings)

    lines.append("=" * 78)
    span = f"{min(years)}-{max(years)}" if years else "?"
    if report.errors:
        lines.append(f"NOT READY -- {len(report.errors)} error(s), "
                     f"{len(report.warnings)} warning(s). Fix the errors and re-run.")
    elif report.warnings:
        lines.append(f"READY TO BUILD (years {span}) -- 0 errors, "
                     f"{len(report.warnings)} warning(s) worth reading first.")
    else:
        lines.append(f"READY TO BUILD (years {span}) -- all checks clean.")
    lines.append("=" * 78)
    return "\n".join(lines)


def _render_findings(findings):
    lines: list[str] = []
    for finding in findings:
        lines.append(f"  [{finding.category}]")
        for chunk in _wrap(finding.message):
            lines.append(f"    {chunk}" if chunk else "")
        if finding.hint:
            hint = _wrap(finding.hint, width=68)
            lines.append(f"    -> {hint[0]}")
            lines += [f"       {chunk}" if chunk else "" for chunk in hint[1:]]
        lines.append("")
    return lines


def _wrap(text: str, width: int = 72):
    """Wrap to `width`, keeping the line breaks and per-line indentation already there.

    Almost every finding is one paragraph of words and comes out exactly as it always did.
    The scope refusal is not: it is an evidence list followed by several paragraphs and a
    bulleted list, and reflowing all of that into one run of words would destroy the part a
    reader most needs to act on.
    """
    out: list[str] = []
    for raw in str(text).split("\n"):
        stripped = raw.strip()
        if not stripped:
            out.append("")
            continue
        indent = raw[: len(raw) - len(raw.lstrip())]
        line = ""
        for word in stripped.split():
            if line and len(indent) + len(line) + 1 + len(word) > width:
                out.append(indent + line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            out.append(indent + line)
    return out or [""]
