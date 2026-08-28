"""The cited rules registry: every statutory figure, date and convention in one place.

Why this exists
---------------
A disclosure schedule is an assertion about the law as much as about the taxpayer's
holdings. A threshold hardcoded in a module is a claim nobody can check and nobody
remembers to re-check, and the ones that matter here have already moved: the Black Money
Act relief threshold replaced a Rs 5,00,000 bank-balance carve-out in 2024, and the
foreign tax credit statement changed its form, its rule and its deadline basis when the
Income-tax Act, 2025 came into force. So the figures live in `rules/AY<year>.json`, each
with an official source, and this module is the only way code reaches them.

There is one registry per assessment year and they are not interchangeable: AY 2026-27 is
decided under the Income-tax Act, 1961 and AY 2027-28 onwards under the Income-tax Act,
2025, which renumbered almost every provision. Each entry in the later registry records the
earlier provision it descends from. See `docs/ANNUAL-REVIEW.md`.

What the code actually reads, and what it does not
--------------------------------------------------
A registry that prints every entry identically invites a reader -- including the author of
this tool, who made exactly this mistake about mutual funds -- to assume that anything in it
is implemented. Most of it is not. So every entry also declares a `code_status`, and
`itr-prep rules` groups its output by it rather than burying it in a field list:

  `read_by_code`             computing code reads this value out of the registry.
  `hardcoded_at_call_site`   the entry describes what the code really does, but the code
                             does not read the entry to do it.
  `not_read`                 nothing reads it and nothing acts on it. A latent gap, recorded
                             deliberately rather than deleted.
  `research_only`            cited research with no code behind it at all.

`tests/test_rules_registry.py` greps the package for every key: a `read_by_code` entry whose
key appears nowhere in `itrprep/` fails, and so does an entry in any of the other three
classes whose key appears there. The classification would rot within one refactor otherwise.

Three things are enforced rather than documented, because a note in a file gets skipped:

  1. **Coverage.** Building a filing for an assessment year later than any registry we
     have is a hard error. Computing AY 2027-28 against AY 2026-27 figures is exactly the
     silent failure this exists to prevent -- and those two are under different Acts, so
     it would not even be a matter of a stale rate.

  2. **Staleness.** Every entry declares a review class. `annual` means a Finance Act or a
     notification can move it, so an `annual` entry stated for an earlier assessment year
     than the one being filed is reported loudly at runtime and fails
     `tests/test_rules_registry.py`. `stable` means fixed by statute -- a settled
     convention or a historical date -- and carries `applies_to: "all"`.

  3. **Classification.** Every entry declares a `code_status` from the closed set above.
     A new entry cannot be added without deciding which one it is, so "nobody thought about
     it" cannot pass for "implemented".

Runtime warns and the test suite fails, deliberately. A contributor or CI run should be
stopped dead by a registry that has rotted; someone mid-filing should not be, because
Schedule FA itself is arithmetic on their own broker data and does not depend on a rate.
What they get instead is a banner they cannot miss.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

REVIEW_STABLE = "stable"
REVIEW_ANNUAL = "annual"
REVIEW_CLASSES = (REVIEW_STABLE, REVIEW_ANNUAL)

APPLIES_TO_ALL = "all"

# How much of the code stands behind an entry. Ordered from "the arithmetic depends on this"
# to "nothing here touches it", which is the order `itr-prep rules` prints its groups in.
CODE_READ = "read_by_code"
CODE_HARDCODED = "hardcoded_at_call_site"
CODE_NOT_READ = "not_read"
CODE_RESEARCH = "research_only"
CODE_STATUSES = (CODE_READ, CODE_HARDCODED, CODE_NOT_READ, CODE_RESEARCH)

# Only the first class may be referenced from itrprep/. The other three are defined by the
# absence of a reference, which is what makes the drift test in tests/test_rules_registry.py
# possible at all.
CODE_STATUS_READS_THE_REGISTRY = (CODE_READ,)

CODE_STATUS_HEADINGS = {
    CODE_READ: "READ BY CODE -- the arithmetic reads these values out of the registry",
    CODE_HARDCODED: (
        "HARDCODED AT THE CALL SITE -- these describe what the code really does, but "
        "the code does not read them"
    ),
    CODE_NOT_READ: (
        "NOT READ -- nothing reads these and nothing acts on them. Recorded gaps, not "
        "behaviour"
    ),
    CODE_RESEARCH: (
        "RESEARCH ONLY -- cited law with NO CODE BEHIND IT. Nothing here computes any of it"
    ),
}

# Primary sources only. A rate, a limit or a date is cited to the Act, to a CBDT
# notification or circular, or to the department's own site -- never to an aggregator.
# file-itr's contributing guide holds itself to this and it is the right standard.
OFFICIAL_HOSTS = (
    "incometax.gov.in",
    "incometaxindia.gov.in",
    "indiabudget.gov.in",
    "egazette.gov.in",
    "indiacode.nic.in",
    "indiacode.gov.in",
)

RULES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules"
)

_AY_FILE_RE = re.compile(r"^AY(\d{4})-(\d{2})\.json$")


class RulesError(Exception):
    """Raised when the registry is missing, malformed, or does not reach far enough."""


def assessment_year_for(calendar_year: int) -> str:
    """The assessment year whose Schedule FA reports `calendar_year`.

    Calendar 2025 sits inside previous year 2025-26, which is assessed in AY 2026-27.
    """
    return f"{calendar_year + 1}-{(calendar_year + 2) % 100:02d}"


def _ay_sort_key(label: str) -> int:
    """Sortable form of an assessment year label, for "which registry is newest"."""
    try:
        return int(label.split("-")[0])
    except (ValueError, IndexError) as exc:
        raise RulesError(f"{label!r} is not an assessment year label like 2026-27") from exc


def available(rules_dir: str = RULES_DIR) -> dict[str, str]:
    """Assessment year label -> registry path, for every registry on disk."""
    found: dict[str, str] = {}
    if not os.path.isdir(rules_dir):
        return found
    for name in sorted(os.listdir(rules_dir)):
        match = _AY_FILE_RE.match(name)
        if match:
            found[f"{match.group(1)}-{match.group(2)}"] = os.path.join(rules_dir, name)
    return found


@dataclass
class Entry:
    """One cited value."""

    key: str
    value: object
    review: str
    code_status: str
    applies_to: str
    verified_on: str
    statute: str
    check: str
    sources: list
    contested: bool = False

    @property
    def is_annual(self) -> bool:
        return self.review == REVIEW_ANNUAL

    @property
    def reads_the_registry(self) -> bool:
        """Is computing code supposed to reach this entry through `itrprep/rules.py`?"""
        return self.code_status in CODE_STATUS_READS_THE_REGISTRY

    def source_lines(self) -> list[str]:
        return [
            f"{s.get('authority', '')} -- {s.get('url', '')}".strip(" -")
            for s in self.sources
        ]


class Rules:
    """One assessment year's registry, loaded and checked for shape."""

    def __init__(self, path: str, document: dict):
        self.path = path
        self.assessment_year = document.get("assessment_year", "")
        self.financial_year = document.get("financial_year", "")
        self.calendar_year = document.get("schedule_fa_calendar_year")
        self.verified_on = document.get("verified_on", "")
        self.source_policy = document.get("_source_policy", "")
        if not self.assessment_year:
            raise RulesError(f"{path}: no assessment_year")
        raw = document.get("entries")
        if not isinstance(raw, dict) or not raw:
            raise RulesError(f"{path}: no entries")
        self.entries: dict[str, Entry] = {}
        for key, body in raw.items():
            if not isinstance(body, dict):
                raise RulesError(f"{path}: entry {key!r} is not an object")
            review = body.get("review", "")
            if review not in REVIEW_CLASSES:
                raise RulesError(
                    f"{path}: entry {key!r} has review {review!r}; expected one of "
                    f"{REVIEW_CLASSES}"
                )
            if "value" not in body:
                raise RulesError(f"{path}: entry {key!r} has no value")
            code_status = body.get("code_status", "")
            if code_status not in CODE_STATUSES:
                raise RulesError(
                    f"{path}: entry {key!r} has code_status {code_status!r}; expected one "
                    f"of {CODE_STATUSES}. Every entry has to say how much of the code "
                    f"stands behind it, so that a reader of `itr-prep rules` can tell "
                    f"cited research from implemented behaviour."
                )
            self.entries[key] = Entry(
                key=key,
                value=body["value"],
                review=review,
                code_status=code_status,
                applies_to=body.get("applies_to", ""),
                verified_on=body.get("verified_on", ""),
                statute=body.get("statute", ""),
                check=body.get("check", ""),
                sources=body.get("sources", []) or [],
                contested=bool(body.get("contested", False)),
            )

    # ------------------------------------------------------------------ reading

    def entry(self, key: str) -> Entry:
        try:
            return self.entries[key]
        except KeyError as exc:
            raise RulesError(
                f"{self.path} has no entry {key!r}. Nothing computes from a figure that "
                f"is not in the registry with a source -- add it, cited, rather than "
                f"hardcoding it at the call site."
            ) from exc

    def value(self, key: str):
        return self.entry(key).value

    def int_value(self, key: str) -> int:
        raw = self.value(key)
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise RulesError(f"{self.path}: entry {key!r} is not an integer: {raw!r}")
        return raw

    def int_field(self, key: str, field_name: str) -> int:
        """One integer out of an entry whose value is an object."""
        raw = self.value(key)
        if not isinstance(raw, dict) or field_name not in raw:
            raise RulesError(
                f"{self.path}: entry {key!r} has no {field_name!r} field: {raw!r}"
            )
        got = raw[field_name]
        if not isinstance(got, int) or isinstance(got, bool):
            raise RulesError(
                f"{self.path}: entry {key!r} field {field_name!r} is not an integer: "
                f"{got!r}"
            )
        return got

    def annual_entries(self) -> list[Entry]:
        return [e for e in self.entries.values() if e.is_annual]

    def by_code_status(self, entries=None) -> list[tuple[str, list[Entry]]]:
        """`CODE_STATUSES` order, each with its entries by key. Empty classes are kept.

        An empty group is printed rather than skipped: "no entry in this registry is read by
        code" is itself worth seeing, and a class that silently disappears from the output is
        a class nobody notices has emptied.
        """
        pool = list(self.entries.values() if entries is None else entries)
        return [
            (status, sorted((e for e in pool if e.code_status == status),
                            key=lambda e: e.key))
            for status in CODE_STATUSES
        ]

    # ------------------------------------------------------------- staleness

    def stale_for(self, assessment_year: str) -> list[Entry]:
        """`annual` entries stated for an assessment year earlier than the one asked for.

        `stable` entries carry `applies_to: "all"` and are never stale by this test --
        they are settled conventions and historical dates, not Finance Act figures.
        """
        want = _ay_sort_key(assessment_year)
        stale = []
        for entry in self.annual_entries():
            if entry.applies_to == APPLIES_TO_ALL:
                continue
            if _ay_sort_key(entry.applies_to) < want:
                stale.append(entry)
        return stale

    def staleness_warning(self, assessment_year: str) -> str:
        """A banner naming every stale entry, or "" when there is nothing to say."""
        stale = self.stale_for(assessment_year)
        if not stale:
            return ""
        width = 79
        lines = [
            "!" * width,
            f"REGISTRY IS OLDER THAN THE YEAR YOU ARE FILING: AY {assessment_year}",
            "",
            f"{os.path.basename(self.path)} states these figures for an earlier",
            "assessment year. Each is set or revised by a Finance Act, so each may have",
            "moved. RE-VERIFY THEM AGAINST AN OFFICIAL SOURCE BEFORE FILING:",
            "",
        ]
        for entry in stale:
            lines.append(f"  {entry.key}  (stated for AY {entry.applies_to})")
            lines.append(f"      {entry.check}")
        lines += [
            "",
            "docs/ANNUAL-REVIEW.md is the checklist. Write a new rules/AY<year>.json",
            "rather than editing this one, so the year you filed stays reproducible.",
            "!" * width,
        ]
        return "\n".join(lines)


def _read(path: str) -> Rules:
    try:
        with open(path, encoding="utf-8") as fh:
            document = json.load(fh)
    except OSError as exc:
        raise RulesError(f"could not read the rules registry {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RulesError(f"{path} is not valid JSON: {exc}") from exc
    return Rules(path, document)


def load(assessment_year: str | None = None, rules_dir: str = RULES_DIR) -> Rules:
    """The registry for `assessment_year`, or the newest one on disk.

    Loading the newest is the right default for anything that reports on the law as it
    now stands -- the threshold report tests years already filed against today's penalty
    provision, because that is the provision that would be applied to them.
    """
    found = available(rules_dir)
    if not found:
        raise RulesError(
            f"no rules registry found in {rules_dir}. This tool computes nothing from "
            f"memory: every statutory figure comes from rules/AY<year>.json with an "
            f"official source. See docs/ANNUAL-REVIEW.md."
        )
    if assessment_year is None:
        newest = max(found, key=_ay_sort_key)
        return _read(found[newest])
    if assessment_year not in found:
        raise RulesError(
            f"no rules registry for AY {assessment_year}. Present: "
            f"{', '.join(sorted(found, key=_ay_sort_key))}."
        )
    return _read(found[assessment_year])


def require_for_calendar_year(
    calendar_year: int, rules_dir: str = RULES_DIR
) -> tuple[Rules, str]:
    """The registry to use when filing `calendar_year`, and any warning to print.

    Refuses outright to run ahead of the registry: filing an assessment year later than
    any registry on disk would mean computing against figures nobody has checked for it.
    Running *behind* the newest registry is allowed -- prior-year updated returns are a
    documented workflow -- but says so, since the figures it is about to use are stated
    for a later year, and from AY 2027-28 possibly under a different Act.
    """
    want = assessment_year_for(calendar_year)
    found = available(rules_dir)
    if not found:
        raise RulesError(
            f"no rules registry found in {rules_dir}; cannot file AY {want}."
        )
    if want in found:
        rules = _read(found[want])
        return rules, rules.staleness_warning(want)

    newest = max(found, key=_ay_sort_key)
    if _ay_sort_key(want) > _ay_sort_key(newest):
        raise RulesError(
            f"the rules registry stops at AY {newest}, but --year {calendar_year} files "
            f"AY {want}.\n"
            f"Every statutory figure this tool uses is cited in rules/AY<year>.json, and "
            f"there is no file for AY {want}. Filing it against AY {newest}'s figures "
            f"would compute a disclosure against a year of law nobody has checked.\n"
            f"Re-verify each entry marked 'annual' against an official source and write "
            f"rules/AY{want}.json. docs/ANNUAL-REVIEW.md is the checklist."
        )

    rules = _read(found[newest])
    width = 79
    warning = "\n".join([
        "-" * width,
        f"NOTE: filing AY {want}, but the registry on disk covers AY {newest}.",
        f"There is no rules/AY{want}.json. The statutory figures used below are stated",
        f"for AY {newest}. For a prior-year updated return that is usually what you",
        "want -- the penalty and threshold provisions applied to it are the ones in force",
        "now -- but it is a choice, not a default. Check the figures the report prints",
        "against the law as it stood if that matters to your position: AY 2026-27 and",
        "earlier are decided under the Income-tax Act, 1961 and later years under the",
        "Income-tax Act, 2025, which renumbered almost every provision.",
        "-" * width,
    ])
    return rules, warning
