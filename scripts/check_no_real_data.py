#!/usr/bin/env python3
"""Refuse to let personal or financial data into this repository, or its history.

This guards the one mistake here that a later commit cannot undo. A committed `.env` or a
real PAN is published the moment it is pushed, and deleting it in the next commit changes
nothing: `git log -p` still hands it to anybody who clones. So this checks the working tree
*and* every commit reachable from every ref, and it is deliberately blunt about it.

Run it before you push:

    python scripts/check_no_real_data.py

It exits non-zero and names what it found. CI runs the same script, plus `--self-test`,
which plants each kind of leak in a throwaway repository and asserts it is caught -- because
a hygiene check nobody tests is a hygiene check that quietly stops working, which is exactly
how this repository once ran seven test suites while claiming eight.

What it cannot see is listed at the end of every run, and the honest summary matters more
than the reassuring one: a check that oversells its coverage is worse than no check, because
somebody relies on it.

Nothing here is clever about validation. It does not run the Verhoeff checksum an Aadhaar
number carries, because the point is to catch a leak rather than to confirm one is genuine,
and a transcribed number with a typo in it has still leaked.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

# --- what counts as a placeholder ------------------------------------------------------
#
# The allowlists are short on purpose. Anything PAN-shaped that is not one of these three
# fails, which is the right default: a contributor pasting their own PAN into an example is
# a far likelier accident than a false positive. If you need a new placeholder, add it here
# in the same commit, so the decision is reviewable.

PLACEHOLDER_PANS = {"AAAAA9999A", "ABCDE1234F", "ZZZZZ0000Z"}

# 9000000000 is the filler mobile number in scripts/make_macos_import_test.py's synthetic
# return. It is not a number anybody can be reached on.
PLACEHOLDER_PHONES = {"9000000000"}

PLACEHOLDER_AADHAARS: set[str] = set()

# RFC 2606 and RFC 6761 reserve these precisely so examples can use them. `.invalid` can
# never resolve, which is why the synthetic return uses it.
RESERVED_EMAIL_DOMAINS = {
    "example.invalid",
    "example.com",
    "example.org",
    "example.net",
    "example.edu",
    "invalid",
    "localhost",
    "test",
}

# A broker export, a filled return and the department's utility are all of these shapes, and
# a text scan cannot see inside any of them. So none of them may be tracked at all. This is
# the same list .gitignore refuses, restated as a hard failure for the case where somebody
# adds one with `git add -f`.
RISKY_BINARY_SUFFIXES = {
    ".xlsx", ".xls", ".xlsm", ".xlsb", ".ods", ".csv.gz",
    ".pdf", ".zip", ".7z", ".rar", ".tar", ".tgz", ".gz",
    ".docx", ".doc", ".rtf", ".pst", ".msg", ".p12", ".pfx", ".jks",
}

# Tracked files that are binary but deliberate. Empty, and it should stay that way: every
# entry here is a file this check has agreed not to look inside.
ALLOWED_BINARIES: set[str] = set()

# Columns whose whole purpose is to hold an account number. A fixture is allowed to have
# them -- Table A2 needs them -- but only with an invented value.
ACCOUNT_NUMBER_COLUMNS = {"account_number", "account_no", "accountnumber"}
SYNTHETIC_ACCOUNT_PREFIXES = ("SYNTH-", "TEST-", "SYNTHETIC-")

PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
# Aadhaar is 12 digits and never begins with 0 or 1 (UIDAI reserves those). Twelve
# consecutive digits are rare in a codebase -- there are none in this one, and none anywhere
# in its history -- so the solid form stays narrow without a checksum. The hyphen-grouped
# form is clean here too.
#
# Space-separated 4-4-4 is deliberately NOT matched. It fired on `2023 2024 2025` in
# docs/ROUNDTRIP_RESULT.md, which is a table of assessment years, and a check that flags
# a column of years teaches everybody to ignore it. The gap is stated in COVERAGE rather
# than papered over.
AADHAAR_RE = re.compile(r"\b[2-9](?:[0-9]{11}|[0-9]{3}-[0-9]{4}-[0-9]{4})\b")
# An Indian mobile number: ten digits beginning 6-9, optionally with a +91 or 0 prefix.
# Deliberately not matching every ten-digit run, because a rupee figure is one.
PHONE_RE = re.compile(r"(?:\+?91[ -]?|\b0)?\b([6-9][0-9]{9})\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")

# `.env` in any directory, `.env.anything`, and `anything.env`. The original check tested
# for a file named exactly `.env`, so `.env.local`, `config/.env`, `secrets.env` and
# `creds.env` all passed -- and the last two are not even gitignored by name.
ENV_PATH_RE = re.compile(r"(?:^|/)(?:\.env(?:\.[^/]*)?|[^/]*\.env)$")
ENV_PATH_ALLOWED = re.compile(r"(?:^|/)\.env\.example$")


class Findings:
    """Collects every problem so one run reports all of them, as `doctor` does."""

    def __init__(self):
        self.problems: list[tuple[str, list[str]]] = []
        self.notes: list[str] = []

    def fail(self, headline, detail=()):
        self.problems.append((headline, list(detail)))

    def note(self, text):
        self.notes.append(text)

    @property
    def ok(self):
        return not self.problems


def git(*args, repo=None, binary=False):
    """Run git and return stdout. Text is decoded loosely: a diff may not be UTF-8."""
    out = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=False,
    )
    if out.returncode != 0 and not out.stdout:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.decode(errors='replace')}")
    return out.stdout if binary else out.stdout.decode("utf-8", errors="replace")


def tracked_files(repo=None):
    return [p for p in git("ls-files", "-z", repo=repo).split("\0") if p]


def scan_text(text, where, findings, seen):
    """Look for every leak shape in one blob of text.

    `where` is what to tell the reader -- a path, or a commit. `seen` deduplicates, so a
    PAN that appears in forty commits is reported once with a count rather than forty times.
    """
    for m in PAN_RE.finditer(text):
        if m.group(0) not in PLACEHOLDER_PANS:
            seen.setdefault(("PAN-shaped string", m.group(0)), []).append(where)

    for m in AADHAAR_RE.finditer(text):
        digits = re.sub(r"[ -]", "", m.group(0))
        if digits not in PLACEHOLDER_AADHAARS:
            seen.setdefault(("Aadhaar-shaped number", m.group(0)), []).append(where)

    for m in PHONE_RE.finditer(text):
        if m.group(1) not in PLACEHOLDER_PHONES:
            seen.setdefault(("phone-shaped number", m.group(1)), []).append(where)

    for m in EMAIL_RE.finditer(text):
        domain = m.group(1).lower()
        if domain not in RESERVED_EMAIL_DOMAINS and not domain.endswith(".invalid"):
            seen.setdefault(("email address", m.group(0)), []).append(where)


def report(seen, findings, scope):
    for (kind, value), wheres in sorted(seen.items()):
        first = wheres[0]
        extra = f" (and {len(wheres) - 1} more)" if len(wheres) > 1 else ""
        findings.fail(
            f"a {kind} that is not a known placeholder is in {scope}: {value}",
            [f"first seen in {first}{extra}"],
        )


# --- the checks ------------------------------------------------------------------------

def check_env_files(findings, repo=None):
    """No credential file may be tracked, now or ever.

    `.env` holds document passwords and the PAN and date of birth used to derive them.
    """
    bad = [p for p in tracked_files(repo)
           if ENV_PATH_RE.search(p) and not ENV_PATH_ALLOWED.search(p)]
    if bad:
        findings.fail("a credential file is tracked; .env holds document passwords", bad)

    # A `.env` that was committed and then deleted is still in the history, and still
    # readable. Path names only, so this stays cheap however long the history gets.
    ever = {p for p in git("log", "--all", "--name-only", "--format=", repo=repo).split("\n")
            if p and ENV_PATH_RE.search(p) and not ENV_PATH_ALLOWED.search(p)}
    ever -= set(bad)
    if ever:
        findings.fail(
            "a credential file exists somewhere in the history, so it is still readable",
            sorted(ever) + ["deleting it in a later commit did not remove it; rewrite history"],
        )


def check_tree(findings, repo=None):
    """Every tracked text file, as it stands now."""
    seen = {}
    for path in tracked_files(repo):
        full = os.path.join(repo or ".", path)
        try:
            with open(full, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if b"\0" in raw:
            continue  # handled by check_binaries
        scan_text(raw.decode("utf-8", errors="replace"), path, findings, seen)
    report(seen, findings, "the working tree")


def check_history(findings, repo=None):
    """Every commit reachable from every ref, including commit messages.

    Cost is proportional to total churn rather than to the size of the tree, because a diff
    only carries the lines that changed. On a text-only repository that stays fast; if this
    ever becomes the slow part of CI, narrow it with `git log --since` and say so out loud
    rather than dropping it, since an unscanned commit is an unscanned leak.

    This needs the full history. `actions/checkout` fetches depth 1 by default, which would
    silently reduce this to one commit -- see the fetch-depth: 0 in the workflow.
    """
    depth = git("rev-list", "--all", "--count", repo=repo).strip()
    if git("rev-parse", "--is-shallow-repository", repo=repo).strip() == "true":
        findings.fail(
            "this is a shallow clone, so the history cannot be scanned",
            ["clone with full depth, or set fetch-depth: 0 on actions/checkout"],
        )
        return
    findings.note(f"scanned {depth} commit(s) of history, including commit messages")

    # -U0 drops context lines: unchanged lines are already covered by the tree scan, and
    # this keeps the volume down to what actually changed.
    # %B puts the whole message -- subject and body -- into the stream as ordinary lines, so
    # a PAN pasted into a commit message is scanned like any other text. It is part of what
    # `git log` hands out, and CONTRIBUTING.md already says not to put one there.
    log = git("log", "--all", "-p", "-U0", "--no-color", "--no-textconv",
              "--format=%n=== commit %H%n%B", repo=repo)
    seen = {}
    where = "an early commit"
    for line in log.split("\n"):
        if line.startswith("=== commit ") and len(line) == len("=== commit ") + 40:
            where = f"commit {line[len('=== commit '):][:12]}"
            continue
        # Only added, removed and message lines carry content worth scanning; the +++/---
        # headers carry paths, which check_env_files already covers.
        if line[:3] in ("+++", "---") or line.startswith("@@"):
            continue
        scan_text(line, where, findings, seen)
    report(seen, findings, "the history")


def check_binaries(findings, repo=None):
    """A PAN inside an .xlsx or a PDF is invisible to every text scan above.

    No binary is tracked today, so this is a latch rather than a fix: it fails the moment
    one arrives, instead of quietly reducing the coverage of everything else.
    """
    risky, opaque = [], []
    for path in tracked_files(repo):
        if path in ALLOWED_BINARIES:
            continue
        lowered = path.lower()
        if any(lowered.endswith(sfx) for sfx in RISKY_BINARY_SUFFIXES):
            risky.append(path)
            continue
        full = os.path.join(repo or ".", path)
        try:
            with open(full, "rb") as fh:
                if b"\0" in fh.read(8192):
                    opaque.append(path)
        except OSError:
            continue
    if risky:
        findings.fail(
            "a spreadsheet, PDF or archive is tracked. A broker export, a filled return and "
            "the department's utility are all of these shapes, and nothing above can read "
            "inside one",
            risky,
        )
    if opaque:
        findings.fail(
            "a binary file is tracked, so the scans above cannot see what is in it",
            opaque + ["if it is genuinely needed, add it to ALLOWED_BINARIES here, in the "
                      "same commit, with a reason"],
        )


def check_account_number_columns(findings, repo=None):
    """The one place a real account number would actually land.

    A generic account-number regex would fire on every long integer in the repository and
    train everybody to ignore this check. An `account_number` column in a tracked CSV is
    unambiguous, so that is what gets checked instead.
    """
    bad = []
    for path in tracked_files(repo):
        if not path.lower().endswith(".csv"):
            continue
        full = os.path.join(repo or ".", path)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                header = fh.readline().strip().split(",")
                idxs = [i for i, name in enumerate(header)
                        if name.strip().strip('"').lower() in ACCOUNT_NUMBER_COLUMNS]
                if not idxs:
                    continue
                for lineno, line in enumerate(fh, start=2):
                    cells = next(iter(_split_csv(line)), [])
                    for i in idxs:
                        if i >= len(cells):
                            continue
                        value = cells[i].strip()
                        if not value:
                            continue
                        if not value.upper().startswith(SYNTHETIC_ACCOUNT_PREFIXES):
                            bad.append(f"{path}:{lineno}: account_number={value!r}")
        except OSError:
            continue
    if bad:
        findings.fail(
            "an account_number in a tracked CSV does not use the synthetic convention "
            f"({', '.join(SYNTHETIC_ACCOUNT_PREFIXES)})",
            bad,
        )


def _split_csv(line):
    import csv
    return csv.reader([line])


COVERAGE = """
What this checked:
  - the working tree, and every commit reachable from every ref, for PAN-shaped strings,
    Aadhaar-shaped numbers, Indian mobile numbers and email addresses outside the reserved
    example domains
  - commit messages, which are part of that history
  - credential files -- .env, .env.anything, anything.env, in any directory -- both tracked
    now and anywhere in the history
  - the account_number column of every tracked CSV, against the SYNTH-/TEST- convention
  - that no spreadsheet, PDF, archive or other binary is tracked, since nothing above can
    read inside one

What it cannot check, and what still needs a human:
  - an account number, a holding or a figure written in prose with no distinguishing shape.
    A number is only recognisable as yours if it looks like an identifier.
  - an Aadhaar number written in space-separated 4-4-4 groups. That pattern is
    indistinguishable from a column of years, so only the solid and hyphen-grouped forms
    are matched.
  - a real name, an address, or a screenshot's contents.
  - whether an invented figure is genuinely invented. Nothing can tell.
  - anything in a ref this clone does not have.
""".strip()


def run_checks(repo=None):
    findings = Findings()
    check_env_files(findings, repo)
    check_binaries(findings, repo)
    check_account_number_columns(findings, repo)
    check_tree(findings, repo)
    check_history(findings, repo)
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true",
                    help="plant each kind of leak in a throwaway repository and assert it "
                         "is caught, then check this repository as usual")
    ap.add_argument("--repo", default=None, help="repository to check. Default: cwd")
    args = ap.parse_args(argv)

    if args.self_test and not self_test():
        return 1

    findings = run_checks(args.repo)
    for note in findings.notes:
        print(f"  {note}")
    if findings.ok:
        print("\nNo personal or financial data found in the tree or its history.")
        print(COVERAGE)
        return 0
    print(f"\nFAILED -- {len(findings.problems)} problem(s):\n")
    for headline, detail in findings.problems:
        print(f"  {headline}")
        for line in detail:
            print(f"      {line}")
    print("\nIf any of this is real, treat it as published: rotate anything credential-shaped")
    print("and rewrite the history. Deleting it in a later commit does nothing.")
    print(COVERAGE)
    return 1


# --- self-test -------------------------------------------------------------------------

def _plant(repo, path, content, message):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(content)
    git("add", "-f", path, repo=repo)
    git("-c", "user.email=self-test@example.invalid", "-c", "user.name=self test",
        "commit", "-q", "-m", message, repo=repo)


def _fresh_repo(tmp, name):
    repo = os.path.join(tmp, name)
    os.makedirs(repo)
    git("init", "-q", "-b", "main", repo=repo)
    _plant(repo, "README.md", "# nothing to see\n", "Initial commit")
    return repo


def _headlines(findings):
    return " | ".join(h for h, _ in findings.problems)


def self_test():
    """Plant every leak shape this is supposed to catch, and one that must not fire."""
    cases = [
        ("a PAN in the tree", "notes.md", "my PAN is ABCPQ1234R\n", "PAN-shaped"),
        ("an Aadhaar in the tree", "notes.md", "uid 234567890123\n", "Aadhaar-shaped"),
        ("a hyphen-grouped Aadhaar", "notes.md", "uid 2345-6789-0123\n", "Aadhaar-shaped"),
        ("a phone number in the tree", "notes.md", "call 9812345678\n", "phone-shaped"),
        ("an email in the tree", "notes.md", "me@gmail.com\n", "email address"),
        ("a tracked .env", ".env", "PAN=AAAAA9999A\n", "credential file is tracked"),
        ("a tracked .env.local", ".env.local", "X=1\n", "credential file is tracked"),
        ("a tracked config/.env", "config/.env", "X=1\n", "credential file is tracked"),
        ("a tracked secrets.env", "secrets.env", "X=1\n", "credential file is tracked"),
        ("a tracked creds.env", "creds.env", "X=1\n", "credential file is tracked"),
        ("a real account number in a CSV",
         "fixture.csv", "account_id,account_number\nx,Z12345678\n", "account_number"),
    ]
    failures = []
    tmp = tempfile.mkdtemp(prefix="itrprep-hygiene-")
    try:
        for label, path, content, expected in cases:
            repo = _fresh_repo(tmp, re.sub(r"\W+", "_", label))
            _plant(repo, path, content, "Add a file")
            found = _headlines(run_checks(repo))
            if expected not in found:
                failures.append(f"{label}: not caught (expected {expected!r}, got {found!r})")

        # The one that matters most: a leak that was committed and then deleted is still
        # in the history, and this check exists because the old one passed on exactly that.
        repo = _fresh_repo(tmp, "deleted_from_tree")
        _plant(repo, "leak.md", "PAN ABCPQ1234R\n", "Add a note")
        os.remove(os.path.join(repo, "leak.md"))
        git("rm", "-q", "leak.md", repo=repo)
        git("-c", "user.email=self-test@example.invalid", "-c", "user.name=self test",
            "commit", "-q", "-m", "Remove the note", repo=repo)
        found = _headlines(run_checks(repo))
        if "PAN-shaped" not in found:
            failures.append(f"a PAN only in history: not caught (got {found!r})")
        if "history" not in found:
            failures.append("a PAN only in history: not attributed to the history")

        # A PAN in a commit message and nowhere else.
        repo = _fresh_repo(tmp, "in_commit_message")
        _plant(repo, "ok.md", "nothing\n", "Fix the return for ABCPQ1234R")
        if "PAN-shaped" not in _headlines(run_checks(repo)):
            failures.append("a PAN in a commit message: not caught")

        # A tracked xlsx, which no text scan can read.
        repo = _fresh_repo(tmp, "tracked_xlsx")
        _plant(repo, "export.xlsx", "PK\x03\x04 not really\n", "Add an export")
        if "spreadsheet, PDF or archive" not in _headlines(run_checks(repo)):
            failures.append("a tracked .xlsx: not caught")

        # And the negative case. A repository carrying only the documented placeholders,
        # the filler mobile number and a reserved-domain address must pass, or the check is
        # noise and everybody learns to ignore it.
        repo = _fresh_repo(tmp, "placeholders_only")
        _plant(repo, "example.md",
               "PAN AAAAA9999A ABCDE1234F ZZZZZ0000Z\nmobile 9000000000\n"
               "mail synthetic.test@example.invalid\n"
               # The false positive that shaped the Aadhaar pattern: a table of years.
               "| 2023 2024 2025 |\n", "Add the documented placeholders")
        _plant(repo, ".env.example", "PAN=AAAAA9999A\n", "Add the template")
        _plant(repo, "accounts.csv", "account_id,account_number\nx,SYNTH-ET-0001\n",
               "Add a fixture")
        findings = run_checks(repo)
        if not findings.ok:
            failures.append(f"documented placeholders wrongly failed: {_headlines(findings)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("SELF-TEST FAILED:")
        for line in failures:
            print(f"  - {line}")
        return False
    print(f"  self-test: {len(cases) + 3} planted leaks caught, placeholders not flagged")
    return True


if __name__ == "__main__":
    sys.exit(main())
