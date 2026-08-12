"""What this tool may disclose, and what it must refuse to disclose.

Schedule FA is a disclosure of assets located **outside** India. An Indian mutual fund unit
and a share in an Indian company are Indian assets wherever they happen to be held, so
neither belongs in Table A2 or Table A3 -- and the department's own field name says so: it is
`CountryCodeExcludingIndia`, and its enum has no code for India.

Why this is a refusal rather than a note in the README
------------------------------------------------------
The README has said since the first commit that Indian mutual funds are out of scope, and
nothing enforced it. Put one in `transactions.csv` and the pipeline treated it as a foreign
equity holding in a foreign custodial account and disclosed it in Schedule FA: no error, no
warning, a complete and plausible-looking return asserting a foreign asset the filer does not
hold. The author of the tool himself believed for a while that mutual funds were supported,
which is the clearest possible evidence that a public user will make the same mistake.

So this refuses, in the same way the rest of the codebase refuses: an unrecognisable broker
file, an unresolved stock split and a dropped export row all stop the run rather than printing
something a reader can scroll past. A warning on a path whose consequence is a wrong filing
would be out of character here.

What it keys on, and deliberately does not
------------------------------------------
Only **structural** signals, because foreign-domiciled funds and ETFs legitimately belong in
Schedule FA and must keep working -- `IVV` is an iShares ETF and is in the synthetic fixtures:

  - an ISIN whose country prefix is `IN`. ISIN is `ISO-3166 country + 9 characters`, so `IN`
    is India's numbering agency and nothing else's. `INE` is an Indian company's equity and
    `INF` an Indian mutual fund scheme; the other third letters are government and state
    paper. Twelve alphanumeric characters are required, so a hand-written placeholder like
    `INVALID` in the column is not mistaken for one.
  - an INR-denominated row. Every money column in the intermediate schema is named `*_usd`;
    a row priced in rupees is not the kind of holding this tool computes.
  - an NSE or BSE ticker suffix -- `RELIANCE.NS`, `500325.BO` -- which is how every data
    source this tool could plausibly meet names an Indian listing.
  - an issuer whose country is India. No false positive is possible: Schedule FA has no
    country code for India, so an issuer row that says INDIA is either an Indian security or
    a wrong country, and both are worth stopping.

It does **not** look at scheme names. "Fund", "Growth", "Direct Plan" and "IDCW" all appear
in the names of legitimate foreign holdings, and matching on them would break the demo while
catching nothing structural.

The limit that matters: **ISIN is absent from many broker exports**, and `currency` and
`exchange` are not columns anything in this tool produces. An Indian holding entered as a
bare ticker with no ISIN will NOT be caught. That is stated in the refusal itself rather than
only here, because the person who needs to know it is the person being refused -- or, worse,
the person who is not.
"""

from __future__ import annotations

from dataclasses import dataclass

# The escape hatch, following the `--allow-dropped-rows` idiom. Named here so the message and
# the argument parser cannot drift apart.
ALLOW_FLAG = "--allow-indian-securities"

# ISIN: two-letter ISO 3166 country code, then nine characters. India's prefix is IN.
ISIN_COUNTRY_INDIA = "IN"
ISIN_LENGTH = 12
ISIN_INDIAN_KINDS = {
    "INE": "an Indian company's equity",
    "INF": "an Indian mutual fund scheme",
}
ISIN_INDIAN_OTHER = "an Indian security"

# What a `currency` cell says when the row is in rupees. Kept tight: a currency that is
# neither USD nor INR is a different problem and is not this guard's business.
INR_TOKENS = frozenset({"INR", "RS", "RS.", "RUPEE", "RUPEES", "\u20b9"})

# Yahoo/Google-style venue suffixes. These are the only forms an Indian listing arrives in.
INDIAN_EXCHANGE_SUFFIXES = {
    ".NS": "the NSE",
    ".NSE": "the NSE",
    ".BO": "the BSE",
    ".BSE": "the BSE",
}

# Matched against the whole normalised country name, never as a substring: BRITISH INDIAN
# OCEAN TERRITORY is in the ITD's country list and is not India.
INDIA_COUNTRY_NAME = "INDIA"


@dataclass
class Hit:
    """One structural reason to believe one ticker is an Indian security."""

    ticker: str
    signal: str
    where: str


def _isin_hit(raw: str, ticker: str, where: str) -> Hit | None:
    isin = (raw or "").strip().upper().replace(" ", "").replace("-", "")
    if len(isin) != ISIN_LENGTH or not isin.isalnum():
        return None
    if not isin.startswith(ISIN_COUNTRY_INDIA):
        return None
    kind = ISIN_INDIAN_KINDS.get(isin[:3], ISIN_INDIAN_OTHER)
    return Hit(
        ticker,
        f"ISIN {isin} is issued under India's ISIN prefix IN, and {isin[:3]} is {kind}",
        where,
    )


def _currency_hit(raw: str, ticker: str, where: str) -> Hit | None:
    token = (raw or "").strip().upper()
    if token not in INR_TOKENS:
        return None
    return Hit(ticker, f"the row is denominated in {token}, not a foreign currency", where)


def _exchange_hit(ticker: str, where: str) -> Hit | None:
    upper = (ticker or "").strip().upper()
    for suffix, venue in sorted(INDIAN_EXCHANGE_SUFFIXES.items()):
        if upper.endswith(suffix):
            return Hit(ticker, f"the ticker carries {suffix}, which names {venue}", where)
    return None


def find_indian_securities(transactions, issuers) -> list[Hit]:
    """Every structural reason to think a holding in this ledger is an Indian security.

    Issuer rows are only examined for tickers that actually appear in `transactions`. An
    unused issuer row cannot reach the output, and refusing a build over one would be
    stricter than the problem.
    """
    hits: list[Hit] = []
    for txn in transactions or ():
        where = txn.source_ref or "transactions.csv"
        for hit in (
            _isin_hit(getattr(txn, "isin", ""), txn.ticker, where),
            _currency_hit(getattr(txn, "currency", ""), txn.ticker, where),
            _exchange_hit(txn.ticker, where),
        ):
            if hit:
                hits.append(hit)

    used = {t.ticker for t in transactions or ()}
    for ticker, issuer in sorted((issuers or {}).items()):
        if ticker not in used:
            continue
        where = f"the issuers.csv row for {ticker}"
        hit = _isin_hit(getattr(issuer, "isin", ""), ticker, where)
        if hit:
            hits.append(hit)
        if (issuer.country_name or "").strip().upper() == INDIA_COUNTRY_NAME:
            hits.append(Hit(
                ticker,
                "the issuer's country is INDIA, and Schedule FA has no country code for "
                "India",
                where,
            ))
    return hits


def summarise(hits: list[Hit]) -> str:
    """One line per ticker, naming every signal and where it was read, for a one-line report."""
    return "; ".join(
        f"{ticker} ({len(group)} signal(s): "
        + ", ".join(sorted({h.signal.split(',')[0] for h in group}))
        + ")"
        for ticker, group in _by_ticker(hits)
    )


def _by_ticker(hits: list[Hit]):
    grouped: dict[str, list[Hit]] = {}
    for hit in hits:
        grouped.setdefault(hit.ticker, []).append(hit)
    return sorted(grouped.items())


def detail_lines(hits: list[Hit]) -> list[str]:
    """The per-ticker evidence block, indented, one signal per line."""
    lines: list[str] = []
    for ticker, group in _by_ticker(hits):
        lines.append(f"  {ticker}")
        for hit in group:
            lines.append(f"      {hit.signal}")
            lines.append(f"        read from {hit.where}")
    return lines


def refusal(hits: list[Hit]) -> str:
    """Why this stops, what still works, and what to do instead.

    Written to be read by somebody mid-filing who has just been told no. It says what was
    detected and on which rows, why an Indian security cannot go in Schedule FA at all, that
    this tool does not compute Indian mutual funds or Indian capital gains and so has nothing
    better to offer them, what to do with those holdings instead, what this check cannot see,
    and the flag to pass if the detection is wrong.
    """
    tickers = [t for t, _ in _by_ticker(hits)]
    one = len(tickers) == 1
    return "\n".join([
        f"{len(tickers)} holding in this ledger looks like an INDIAN security,"
        if one else
        f"{len(tickers)} holdings in this ledger look like INDIAN securities,",
        "which Schedule FA cannot disclose.",
        "",
        *detail_lines(hits),
        "",
        "Schedule FA discloses assets located OUTSIDE India. An Indian mutual",
        "fund unit and a share in an Indian company are Indian assets wherever",
        "they are held, so neither belongs in Table A2 or Table A3. Disclosing",
        "one there does not merely add a spurious row: it asserts to the",
        "department that you hold a foreign asset you do not hold. The",
        "department's own field is named CountryCodeExcludingIndia, and its enum",
        "has no code for India.",
        "",
        "This tool does not handle Indian mutual funds or Indian capital gains",
        "AT ALL, so it has nothing better to offer these rows. There is no NAV",
        "source here, no equity-oriented classification, no grandfathering to",
        "31 January 2018 and no Specified Mutual Fund test. rules/AY2027-28.json",
        "carries the cited law for them and no code reads it.",
        "",
        "Do this instead:",
        "",
        "  - delete the rows above from transactions.csv, and their issuers.csv",
        "    rows;",
        "  - compute your Indian holdings' gains from a registrar or broker",
        "    capital-gains statement and enter them in Schedule CG yourself,",
        "    outside this tool;",
        "  - keep only foreign holdings here, and this will build.",
        "",
        "What this check can and cannot see. It keys on structural signals only:",
        "an ISIN whose country prefix is IN, an INR-denominated row, an NSE or",
        "BSE ticker suffix, and an issuer whose country is INDIA. It deliberately",
        "does NOT read scheme names, because Fund, Growth, Direct Plan and IDCW",
        "all appear in the names of legitimate foreign holdings. So an Indian",
        "holding entered as a bare ticker with no ISIN and no currency WILL NOT",
        "BE CAUGHT. This lowers the chance of the mistake; it does not move the",
        "responsibility for what you file.",
        "",
        "If one of these is genuinely a FOREIGN security that trips the check,",
        f"re-run with {ALLOW_FLAG}. Confirm it first, and note",
        "that the flag turns the check off for every row above rather than for",
        "the one you had in mind.",
    ])
