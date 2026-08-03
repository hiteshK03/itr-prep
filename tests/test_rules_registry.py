"""The rules registry's teeth.

A registry of statutory figures is only worth having if something stops it rotting. A
comment saying "re-verify this each year" gets skipped; a failing test does not. So this
suite is the enforcement half of `rules/AY<year>.json`:

  - every entry cites an official source, and cites nothing else
  - every entry declares whether it is `stable` or `annual`, consistently with the
    assessment year it is stated for
  - no `annual` entry has been left behind by the registry it lives in
  - the loader refuses to run ahead of the registry, and says so when it runs behind
  - the figures the code actually computes with are the figures in the registry
  - docs/ANNUAL-REVIEW.md still lists every entry that needs re-verifying

The last two are the ones that catch real drift: a constant reintroduced at a call site,
or an entry added to the registry and never added to the checklist.

Network checks are opt-in, because every other suite here runs offline:

    ITRPREP_CHECK_SOURCE_URLS=1 .venv/bin/python tests/test_rules_registry.py

Run:  .venv/bin/python tests/test_rules_registry.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import positions, rules, threshold
from itrprep.fx import FxRates
from itrprep.models import TXN_BUY, TXN_SELL, Transaction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_DIR = os.path.join(ROOT, "rules")
REVIEW_DOC = os.path.join(ROOT, "docs", "ANNUAL-REVIEW.md")
FX_CACHE = os.path.join(ROOT, "data", "sbi_ttbuy_usd.csv")

# Aggregators. Useful for finding a provision, never the authority for one. This is
# file-itr's contributing standard, enforced rather than requested.
SECONDARY_HOSTS = (
    "cleartax", "taxguru", "taxmann", "quicko", "caclubindia", "taxscan",
    "indiafilings", "bankbazaar", "policybazaar", "groww", "zerodha", "vested",
    "taxontips", "taxcorner", "cacult", "kpmg", "ey.com", "pwc", "deloitte",
    "wikipedia", "linkedin", "medium.com", "blogspot",
)

# A search page is not a citation: it is a promise that a citation exists somewhere.
NOT_A_CITATION = ("/search", "?q=", "?s=", "google.", "bing.", "duckduckgo")

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(f"{label}{(' -- ' + detail) if detail else ''}")
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


def _host(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].lower()


def _is_iso_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        return False
    return True


def main() -> int:
    # ------------------------------------------------------------ the files
    print("\n[registry files]")
    found = rules.available(RULES_DIR)
    check("at least one registry is present", bool(found), RULES_DIR)
    if not found:
        print("\nFAILED -- nothing to check.")
        return 1

    for label, path in sorted(found.items()):
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        check(f"{os.path.basename(path)} declares the assessment year in its name",
              raw.get("assessment_year") == label,
              f"file says {raw.get('assessment_year')!r}, name says {label!r}")
        start = int(label.split("-")[0])
        check(f"{label}: the Schedule FA calendar year is one behind the AY start",
              raw.get("schedule_fa_calendar_year") == start - 1,
              str(raw.get("schedule_fa_calendar_year")))
        check(f"{label}: financial year is consistent with the assessment year",
              raw.get("financial_year") == f"{start - 1}-{start % 100:02d}",
              str(raw.get("financial_year")))
        check(f"{label}: verified_on is an ISO date",
              _is_iso_date(raw.get("verified_on", "")),
              str(raw.get("verified_on")))
        check(f"{label}: verified_on is not in the future",
              _is_iso_date(raw.get("verified_on", ""))
              and dt.date.fromisoformat(raw["verified_on"]) <= dt.date.today(),
              str(raw.get("verified_on")))
        check(f"{label}: states its source policy",
              bool((raw.get("_source_policy") or "").strip()))

    registry = rules.load(rules_dir=RULES_DIR)
    print(f"  note  newest registry is AY {registry.assessment_year}, "
          f"{len(registry.entries)} entries")

    # ------------------------------------------------------------ citations
    # The rule india-itr-copilot gets right, and the whole reason a registry beats a
    # constant: an entry with no official source fails, every time, for everyone.
    print("\n[citations]")
    for key, entry in sorted(registry.entries.items()):
        check(f"{key}: has at least one source", bool(entry.sources))
        urls = [(s.get("url") or "").strip() for s in entry.sources]
        authorities = [(s.get("authority") or "").strip() for s in entry.sources]
        check(f"{key}: every source names its authority", all(authorities),
              str(entry.sources))
        check(f"{key}: every source has a URL", all(urls), str(urls))
        check(f"{key}: at least one source is on an official domain",
              any(any(_host(u).endswith(h) or _host(u) == h
                      for h in rules.OFFICIAL_HOSTS) for u in urls if u),
              str([_host(u) for u in urls if u]))
        offenders = [
            u for u in urls
            if u and any(bad in _host(u) for bad in SECONDARY_HOSTS)
        ]
        check(f"{key}: cites no secondary aggregator as authority",
              not offenders, str(offenders))
        weak = [u for u in urls if u and any(bad in u.lower() for bad in NOT_A_CITATION)]
        check(f"{key}: no source is a search result", not weak, str(weak))
        check(f"{key}: names the provision it comes from", bool(entry.statute.strip()))
        check(f"{key}: says what to re-check", bool(entry.check.strip()))
        check(f"{key}: verified_on is an ISO date", _is_iso_date(entry.verified_on),
              entry.verified_on)

    # ------------------------------------------------------- review classes
    print("\n[review classes]")
    for key, entry in sorted(registry.entries.items()):
        check(f"{key}: review class is known", entry.review in rules.REVIEW_CLASSES,
              entry.review)
        if entry.review == rules.REVIEW_STABLE:
            check(f"{key}: a stable entry applies to every assessment year",
                  entry.applies_to == rules.APPLIES_TO_ALL,
                  entry.applies_to)
        else:
            check(f"{key}: an annual entry names the assessment year it is stated for",
                  entry.applies_to != rules.APPLIES_TO_ALL
                  and "-" in entry.applies_to,
                  entry.applies_to)
    annual = registry.annual_entries()
    check("the registry has both stable and annual entries",
          bool(annual) and len(annual) < len(registry.entries),
          f"{len(annual)} annual of {len(registry.entries)}")

    # ------------------------------------------------------------ staleness
    # The registry must not have rotted against its own assessment year. Once a later
    # registry is added, this is what fails if an annual entry was copied across
    # without being re-verified.
    print("\n[staleness]")
    stale = registry.stale_for(registry.assessment_year)
    check("no annual entry is older than the registry it lives in",
          not stale, str([e.key for e in stale]))
    later = f"{int(registry.assessment_year.split('-')[0]) + 1}-" \
            f"{(int(registry.assessment_year.split('-')[0]) + 2) % 100:02d}"
    check("every annual entry is reported stale against the following year",
          {e.key for e in registry.stale_for(later)} == {e.key for e in annual},
          str([e.key for e in registry.stale_for(later)]))
    check("no stable entry is ever reported stale",
          all(e.review == rules.REVIEW_ANNUAL for e in registry.stale_for(later)))
    banner = registry.staleness_warning(later)
    check("the staleness banner names every stale entry",
          all(e.key in banner for e in annual))
    check("the staleness banner carries each entry's re-check instruction",
          all(e.check[:40] in banner for e in annual))
    check("there is no banner when nothing is stale",
          registry.staleness_warning(registry.assessment_year) == "")

    # ------------------------------------------------------------- coverage
    # "Silently computing AY 2027-28 against AY 2026-27 rates" is the failure this
    # prevents, so it is a hard error and not a warning.
    print("\n[coverage]")
    newest_start = int(registry.assessment_year.split("-")[0])
    ahead_year = newest_start  # calendar year whose AY is one past the newest registry
    try:
        rules.require_for_calendar_year(ahead_year, rules_dir=RULES_DIR)
        check("filing past the newest registry is refused", False, "no error raised")
    except rules.RulesError as exc:
        check("filing past the newest registry is refused", True)
        check("the refusal names the assessment year that is missing",
              rules.assessment_year_for(ahead_year) in str(exc), str(exc)[:120])
        check("the refusal points at the review checklist",
              "ANNUAL-REVIEW" in str(exc))

    covered, warning = rules.require_for_calendar_year(
        registry.calendar_year, rules_dir=RULES_DIR
    )
    check("the covered year loads its own registry",
          covered.assessment_year == registry.assessment_year)
    check("the covered year needs no warning", warning == "")

    behind, behind_warning = rules.require_for_calendar_year(
        registry.calendar_year - 2, rules_dir=RULES_DIR
    )
    check("a prior year still runs", behind.assessment_year == registry.assessment_year)
    check("a prior year says which assessment year its figures are stated for",
          registry.assessment_year in behind_warning, behind_warning[:120])

    try:
        rules.load("1999-00", rules_dir=RULES_DIR)
        check("an unknown assessment year is refused", False, "no error raised")
    except rules.RulesError:
        check("an unknown assessment year is refused", True)

    try:
        rules.load(rules_dir=os.path.join(ROOT, "does-not-exist"))
        check("a missing registry directory is refused", False, "no error raised")
    except rules.RulesError as exc:
        check("a missing registry directory is refused", True)
        check("the refusal explains that nothing is computed from memory",
              "memory" in str(exc).lower())

    # ------------------------------------------- the code agrees with the registry
    # A figure is only really in the registry if the arithmetic reads it from there.
    print("\n[the code reads the registry]")
    check("the threshold report's relief figure is the registry's",
          threshold.threshold_inr()
          == registry.int_value("black_money_relief_threshold_inr"),
          f"{threshold.threshold_inr()} vs "
          f"{registry.int_value('black_money_relief_threshold_inr')}")
    check("the threshold report's penalty figure is the registry's",
          threshold.penalty_inr()
          == registry.int_value("black_money_s43_penalty_inr"),
          f"{threshold.penalty_inr()} vs "
          f"{registry.int_value('black_money_s43_penalty_inr')}")

    # The holding period is asserted through the computation rather than by reading the
    # constant back, so a literal reintroduced at the comparison would still fail.
    days = registry.int_field("foreign_share_long_term_holding", "days")
    fx = FxRates.load(FX_CACHE)
    for label, offset, expect_long in (
        ("one day inside the long-term threshold", days + 1, True),
        ("exactly on the threshold is still short term", days, False),
    ):
        buy = dt.date(2023, 6, 1)
        sell = buy + dt.timedelta(days=offset)
        txns = [
            Transaction("a", "ZZZ", TXN_BUY, buy,
                        quantity=Decimal(1), price_usd=Decimal(100)),
            Transaction("a", "ZZZ", TXN_SELL, sell,
                        quantity=Decimal(1), price_usd=Decimal(150)),
        ]
        fy_start = sell.year if sell.month >= 4 else sell.year - 1
        totals = positions.compute_year_totals(
            positions.build_lots(txns), txns, fy_start, fx, rules=registry
        )
        got_long = totals.ltcg_proceeds_inr > 0
        check(f"the split honours the registry: {label}", got_long == expect_long,
              f"ltcg {totals.ltcg_proceeds_inr}, stcg {totals.stcg_proceeds_inr}")

    check("the months and days in the holding-period entry agree",
          registry.int_field("foreign_share_long_term_holding", "months") * 30 <= days
          <= registry.int_field("foreign_share_long_term_holding", "months") * 31,
          f"{registry.value('foreign_share_long_term_holding')}")

    try:
        registry.value("no_such_entry")
        check("reading an absent entry is refused", False, "no error raised")
    except rules.RulesError as exc:
        check("reading an absent entry is refused", True)
        check("the refusal says to add it cited rather than hardcode it",
              "hardcoding" in str(exc))

    # ------------------------------------------------- the checklist cannot drift
    print("\n[annual review checklist]")
    check("docs/ANNUAL-REVIEW.md exists", os.path.exists(REVIEW_DOC), REVIEW_DOC)
    if os.path.exists(REVIEW_DOC):
        with open(REVIEW_DOC, encoding="utf-8") as fh:
            doc = fh.read()
        missing = [e.key for e in annual if e.key not in doc]
        check("every annual entry appears in the checklist", not missing, str(missing))
        check("the checklist names the registry it describes",
              f"AY{registry.assessment_year}.json" in doc)
        undocumented = [
            key for key, entry in registry.entries.items()
            if entry.review == rules.REVIEW_ANNUAL
            and not any(url.get("url", "") in doc for url in entry.sources)
        ]
        check("the checklist carries a source link for every annual entry",
              not undocumented, str(undocumented))

    # ------------------------------------------------------- optional: reachability
    if os.environ.get("ITRPREP_CHECK_SOURCE_URLS") == "1":
        print("\n[source URLs reachable]")
        import urllib.error
        import urllib.request
        seen: dict[str, int] = {}
        for entry in registry.entries.values():
            for source in entry.sources:
                url = (source.get("url") or "").strip()
                if not url or url in seen:
                    continue
                request = urllib.request.Request(
                    url, method="HEAD",
                    headers={"User-Agent": "Mozilla/5.0 (itr-prep source check)"},
                )
                try:
                    with urllib.request.urlopen(request, timeout=30) as response:
                        seen[url] = response.status
                except urllib.error.HTTPError as exc:
                    seen[url] = exc.code
                except Exception:  # noqa: BLE001 -- network, TLS, DNS, anything
                    seen[url] = 0
        for url, status in sorted(seen.items()):
            # 403 is what incometaxindia.gov.in returns to any non-browser client, so
            # it says nothing about whether the page exists. 404 and 410 do.
            gone = status in (404, 410)
            check(f"{_host(url)} does not report the page gone ({status})", not gone, url)
    else:
        print("\n[source URLs reachable]")
        print("  SKIP  set ITRPREP_CHECK_SOURCE_URLS=1 to HEAD every cited URL")

    print()
    if failures:
        print(f"FAILED -- {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All rules registry checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
