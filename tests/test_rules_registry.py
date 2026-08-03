"""The rules registry's teeth.

A registry of statutory figures is only worth having if something stops it rotting. A
comment saying "re-verify this each year" gets skipped; a failing test does not. So this
suite is the enforcement half of `rules/AY<year>.json`:

  - every entry in EVERY registry cites an official source, and cites nothing else
  - every entry declares whether it is `stable` or `annual`, consistently with the
    assessment year it is stated for
  - no `annual` entry has been left behind by the registry it lives in
  - the loader refuses to run ahead of the registry, and says so when it runs behind
  - the figures the code actually computes with are the figures in the registry
  - docs/ANNUAL-REVIEW.md still lists every entry that needs re-verifying
  - the change of statute is recorded rather than applied by find-and-replace

"Every registry" is load-bearing rather than tidiness. These checks used to run against
the newest registry alone, which was fine while there was one; adding rules/AY2027-28.json
would have quietly retired the AY 2026-27 file from the suite on the day a second one
appeared.

The last block is the one specific to the change of Act. AY 2026-27 was filed under the
Income-tax Act, 1961 and AY 2027-28 is the first year under the Income-tax Act, 2025, so
the two registries must cite DIFFERENT statutes, each one must go on citing its own, and
every AY 2027-28 entry must record which AY 2026-27 entry it descends from. A future
contributor "fixing" the old registry's section numbers to match the new Act would be
falsifying the record of a filed return, and this is what stops them.

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

from itrprep import emit, positions, rules, threshold
from itrprep.fx import FxRates
from itrprep.models import TXN_BUY, TXN_SELL, Transaction
from itrprep.positions import YearTotals

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

# Which statute each assessment year is governed by. The Income-tax Act, 2025 came into
# force on 1 April 2026 (its own s.1(3)) and repealed the 1961 Act (s.536(1)), but
# s.536(2)(c) keeps the repealed Act applying to proceedings for any tax year beginning
# before that date -- so AY 2026-27 is, permanently, a 1961-Act year.
FIRST_AY_UNDER_THE_2025_ACT = 2027
ACT_1961 = "Income-tax Act, 1961"
ACT_2025 = "Income-tax Act, 2025"

# The vocabulary an `act_transition` block may use. A new value has to be added here
# deliberately, so that "we did not think about it" cannot masquerade as a classification.
ACT_TRANSITION_CHANGES = (
    "renumbered_only",
    "renumbered_and_substantive",
    "unchanged_separate_legislation",
    "new_entry",
)

# Two findings that cost real money if an implementation forgets them, so they live in the
# registry as structured data rather than in a memo. Each names the entry that carries it
# and a phrase that must survive any rewrite of the prose around it.
REQUIRED_TRAPS = {
    "amfi_nav_column": (
        "mf_grandfathering_fmv_basis_unlisted",
        ("Repurchase Price", "Net Asset Value", "4,756"),
    ),
    "specified_mf_overrides_holding_period": (
        "specified_mf_deemed_short_term",
        ("Irrespective", "holding_days", "1 April 2023"),
    ),
}

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


def _raw_entries(path: str) -> dict:
    """The entries as they sit on disk.

    `rules.load` returns typed entries and drops the keys it has no field for, which is
    the right call for the loader and the wrong one here: `act_transition` and
    `implementation_trap` are checked precisely because nothing else reads them.
    """
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get("entries", {})


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
    all_registries = {
        label: rules.load(label, rules_dir=RULES_DIR) for label in sorted(found)
    }
    check("every registry on disk loads",
          len(all_registries) == len(found), f"{len(all_registries)} of {len(found)}")
    for label, loaded in sorted(all_registries.items()):
        print(f"  note  AY {label}: {len(loaded.entries)} entries, "
              f"{len(loaded.annual_entries())} annual")

    # ------------------------------------------------------------ citations
    # The rule india-itr-copilot gets right, and the whole reason a registry beats a
    # constant: an entry with no official source fails, every time, for everyone. Run
    # against every registry, not just the newest -- a filed year's citations have to go
    # on being checkable after a later year has been added.
    print("\n[citations]")
    for label, loaded in sorted(all_registries.items()):
        for key, entry in sorted(loaded.entries.items()):
            tag = f"{label} {key}"
            check(f"{tag}: has at least one source", bool(entry.sources))
            urls = [(s.get("url") or "").strip() for s in entry.sources]
            authorities = [(s.get("authority") or "").strip() for s in entry.sources]
            check(f"{tag}: every source names its authority", all(authorities),
                  str(entry.sources))
            check(f"{tag}: every source has a URL", all(urls), str(urls))
            check(f"{tag}: at least one source is on an official domain",
                  any(any(_host(u).endswith(h) or _host(u) == h
                          for h in rules.OFFICIAL_HOSTS) for u in urls if u),
                  str([_host(u) for u in urls if u]))
            offenders = [
                u for u in urls
                if u and any(bad in _host(u) for bad in SECONDARY_HOSTS)
            ]
            check(f"{tag}: cites no secondary aggregator as authority",
                  not offenders, str(offenders))
            weak = [
                u for u in urls if u and any(bad in u.lower() for bad in NOT_A_CITATION)
            ]
            check(f"{tag}: no source is a search result", not weak, str(weak))
            check(f"{tag}: names the provision it comes from", bool(entry.statute.strip()))
            check(f"{tag}: says what to re-check", bool(entry.check.strip()))
            check(f"{tag}: verified_on is an ISO date", _is_iso_date(entry.verified_on),
                  entry.verified_on)

    # ------------------------------------------------------- review classes
    print("\n[review classes]")
    for label, loaded in sorted(all_registries.items()):
        for key, entry in sorted(loaded.entries.items()):
            tag = f"{label} {key}"
            check(f"{tag}: review class is known", entry.review in rules.REVIEW_CLASSES,
                  entry.review)
            if entry.review == rules.REVIEW_STABLE:
                check(f"{tag}: a stable entry applies to every assessment year",
                      entry.applies_to == rules.APPLIES_TO_ALL,
                      entry.applies_to)
            else:
                check(f"{tag}: an annual entry names the assessment year it is stated for",
                      entry.applies_to != rules.APPLIES_TO_ALL
                      and "-" in entry.applies_to,
                      entry.applies_to)
        loaded_annual = loaded.annual_entries()
        check(f"{label}: has both stable and annual entries",
              bool(loaded_annual) and len(loaded_annual) < len(loaded.entries),
              f"{len(loaded_annual)} annual of {len(loaded.entries)}")
        # A contested entry is a live disagreement, not a footnote. It has to say so
        # where `itr-prep rules` will print it.
        for key, entry in sorted(loaded.entries.items()):
            if entry.contested:
                check(f"{label} {key}: a contested entry explains the disagreement",
                      "CONTESTED" in entry.check.upper(), entry.check[:80])

    # ------------------------------------------------------------ staleness
    # A registry must not have rotted against its own assessment year. This is what fails
    # if an annual entry was copied into a later registry without being re-verified.
    print("\n[staleness]")
    for label, loaded in sorted(all_registries.items()):
        loaded_annual = loaded.annual_entries()
        stale = loaded.stale_for(loaded.assessment_year)
        check(f"{label}: no annual entry is older than the registry it lives in",
              not stale, str([e.key for e in stale]))
        start = int(loaded.assessment_year.split("-")[0])
        later = f"{start + 1}-{(start + 2) % 100:02d}"
        check(f"{label}: every annual entry is reported stale against the following year",
              {e.key for e in loaded.stale_for(later)}
              == {e.key for e in loaded_annual},
              str([e.key for e in loaded.stale_for(later)]))
        check(f"{label}: no stable entry is ever reported stale",
              all(e.review == rules.REVIEW_ANNUAL for e in loaded.stale_for(later)))
        banner = loaded.staleness_warning(later)
        check(f"{label}: the staleness banner names every stale entry",
              all(e.key in banner for e in loaded_annual))
        check(f"{label}: the staleness banner carries each re-check instruction",
              all(e.check[:40] in banner for e in loaded_annual))
        check(f"{label}: there is no banner when nothing is stale",
              loaded.staleness_warning(loaded.assessment_year) == "")

    # --------------------------------------------------------- act transition
    # AY 2026-27 was filed under the Income-tax Act, 1961. AY 2027-28 is the first year
    # under the Income-tax Act, 2025. Both statements have to keep being true in the
    # tree, which means the old registry must go on citing the old Act and the new one
    # must not -- and every new entry must say which old entry it descends from.
    print("\n[act transition]")
    for label, loaded in sorted(all_registries.items()):
        start = int(loaded.assessment_year.split("-")[0])
        governed_by_2025 = start >= FIRST_AY_UNDER_THE_2025_ACT
        blob = " ".join(
            entry.statute + " " + " ".join(entry.source_lines())
            for entry in loaded.entries.values()
        )
        if governed_by_2025:
            check(f"{label}: cites the Income-tax Act, 2025", ACT_2025 in blob)
            check(f"{label}: every entry records its act transition",
                  all("act_transition" in raw
                      for raw in _raw_entries(found[label]).values()),
                  str([k for k, raw in _raw_entries(found[label]).items()
                       if "act_transition" not in raw]))
            raw_entries = _raw_entries(found[label])
            for key, raw in sorted(raw_entries.items()):
                move = raw.get("act_transition") or {}
                check(f"{label} {key}: the transition names old and new provisions",
                      bool((move.get("old") or "").strip())
                      and bool((move.get("new") or "").strip()), str(move))
                check(f"{label} {key}: the transition classifies the change",
                      move.get("change") in ACT_TRANSITION_CHANGES,
                      str(move.get("change")))
        else:
            check(f"{label}: still cites the Income-tax Act, 1961", ACT_1961 in blob,
                  "a filed year must keep citing the Act it was filed under")

    # Nothing may be dropped on the way across. Every AY 2026-27 entry has to be
    # accounted for by name in the successor registry, even if only to be renamed.
    older = all_registries.get("2026-27")
    newer = all_registries.get("2027-28")
    if older and newer:
        descends_from = {
            (raw.get("act_transition") or {}).get("ay2026_27_key")
            for raw in _raw_entries(found["2027-28"]).values()
        }
        orphaned = [k for k in older.entries if k not in descends_from]
        check("every AY 2026-27 entry is accounted for in AY 2027-28",
              not orphaned, str(orphaned))
        renamed = [
            (raw["act_transition"]["ay2026_27_key"], key)
            for key, raw in sorted(_raw_entries(found["2027-28"]).items())
            if (raw.get("act_transition") or {}).get("ay2026_27_key")
            and raw["act_transition"]["ay2026_27_key"] != key
        ]
        print(f"  note  {len(renamed)} entr(ies) renamed across the Act change: "
              f"{', '.join(f'{a} -> {b}' for a, b in renamed) or 'none'}")
        # The Black Money Act is separate legislation and the 2025 Act does not touch it,
        # so its entries must be marked as carried over rather than as renumbered.
        for key in ("black_money_s43_penalty_inr", "black_money_relief_threshold_inr"):
            move = (_raw_entries(found["2027-28"])[key].get("act_transition") or {})
            check(f"{key}: recorded as separate legislation, not renumbered",
                  move.get("change") == "unchanged_separate_legislation",
                  str(move.get("change")))

    # ------------------------------------------------------ encoded traps
    # Two findings that produce a plausible-looking wrong number rather than an error.
    # They belong in the registry as structured data, where an implementer will meet
    # them, rather than in a memo nobody re-reads.
    print("\n[encoded traps]")
    trap_source = _raw_entries(found["2027-28"]) if "2027-28" in found else {}
    for name, (key, phrases) in sorted(REQUIRED_TRAPS.items()):
        raw = trap_source.get(key, {})
        trap = raw.get("implementation_trap") or {}
        check(f"{name}: carried by {key}", trap.get("name") == name, str(trap.get("name")))
        check(f"{name}: says what goes wrong", bool((trap.get("what") or "").strip()))
        check(f"{name}: says what to do instead", bool((trap.get("so") or "").strip()))
        check(f"{name}: is marked as a silent wrong answer",
              trap.get("severity") == "silent_wrong_answer", str(trap.get("severity")))
        body = f"{trap.get('what', '')} {trap.get('so', '')}"
        for phrase in phrases:
            check(f"{name}: still names {phrase!r}", phrase in body)

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

    # The other-schedules summary used to end in four hardcoded lines naming Form 67 and
    # rule 128(9). Printed for a 2025-Act year they would assert repealed provisions, so
    # the paragraph is rendered from the registry -- and this is what stops it being
    # written back as a constant.
    for label, loaded in sorted(all_registries.items()):
        # The paragraph is wrapped, so compare against it unwrapped.
        summary = " ".join(emit.summarise_other_schedules(
            YearTotals(), label, long_term_months=24, year_rules=loaded
        ).split())
        for key in ("foreign_tax_credit_statement_deadline", "form_67_deadline"):
            if key in loaded.entries:
                deadline = loaded.value(key)
                break
        check(f"{label}: the summary names the form from the registry",
              deadline["form"] in summary, summary[-320:])
        check(f"{label}: the summary names the rule from the registry",
              deadline["rule"] in summary, summary[-320:])
        check(f"{label}: the summary states the registry's deadline",
              deadline["date"] in summary, summary[-320:])
    older_summary = " ".join(emit.summarise_other_schedules(
        YearTotals(), "2026-27", 24, year_rules=all_registries.get("2026-27")
    ).split())
    newer_summary = " ".join(emit.summarise_other_schedules(
        YearTotals(), "2027-28", 24, year_rules=all_registries.get("2027-28")
    ).split())
    check("a 1961-Act year's summary still says Form 67 and rule 128",
          "Form No. 67" in older_summary and "128(9)" in older_summary)
    check("a 2025-Act year's summary asserts no repealed provision",
          "Form No. 67" not in newer_summary and "128(9)" not in newer_summary
          and "139(" not in newer_summary, newer_summary[-320:])

    # ------------------------------------------------- the checklist cannot drift
    print("\n[annual review checklist]")
    check("docs/ANNUAL-REVIEW.md exists", os.path.exists(REVIEW_DOC), REVIEW_DOC)
    if os.path.exists(REVIEW_DOC):
        with open(REVIEW_DOC, encoding="utf-8") as fh:
            doc = fh.read()
        for label, loaded in sorted(all_registries.items()):
            loaded_annual = loaded.annual_entries()
            missing = [e.key for e in loaded_annual if e.key not in doc]
            check(f"{label}: every annual entry appears in the checklist",
                  not missing, str(missing))
            check(f"{label}: the checklist names the registry it describes",
                  f"AY{label}.json" in doc)
            undocumented = [
                e.key for e in loaded_annual
                if not any(source.get("url", "") in doc for source in e.sources)
            ]
            check(f"{label}: the checklist carries a source link for every annual entry",
                  not undocumented, str(undocumented))
        # The discontinuity itself has to be explained, not just listed: a reader who
        # meets AY 2027-28 as "this year's refresh" will re-verify the wrong figures
        # against the wrong Act.
        check("the checklist explains the change of Act",
              ACT_2025 in doc and "536" in doc)
        check("the checklist says why the old registry keeps old-Act citations",
              "536(2)(c)" in doc)

    # ------------------------------------------------------- optional: reachability
    if os.environ.get("ITRPREP_CHECK_SOURCE_URLS") == "1":
        print("\n[source URLs reachable]")
        import urllib.error
        import urllib.request
        seen: dict[str, int] = {}
        every_entry = [
            entry for loaded in all_registries.values() for entry in loaded.entries.values()
        ]
        for entry in every_entry:
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
