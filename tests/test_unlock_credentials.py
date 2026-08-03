"""The credential handling's teeth: prove a password cannot escape the process.

The design claim in `itrprep/unlock.py` is that a document password read from `.env` never
reaches a log line, an error message, a traceback, a listing or a command line. A claim like
that is worth nothing unasserted, so this suite tries to make it fail:

  - build a genuinely encrypted PDF and a genuinely encrypted workbook with known
    passwords, then fail to open them with wrong ones, and search everything that comes
    back -- the error text, stdout, stderr, the repr of every object involved -- for both
    the right password and the wrong one;
  - check the failure still says something useful, by naming the variables it tried;
  - check `--list-credentials` reports names and set/unset only;
  - check no candidate is ever derived from a filename, which is the pattern this module
    exists to replace;
  - check decrypted output lands 0600 in an owner-only directory that git ignores.

The PDF and workbook round-trips need the optional unlock extras. Without them those blocks
skip and the rest still runs, but CI installs them so they always run there.

Run:  .venv/bin/python tests/test_unlock_credentials.py
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrprep import unlock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Invented. Shaped like the real thing and belonging to nobody.
FAKE_PAN = "ABCDE1234F"
FAKE_DOB = "02031985"

# The secret the tests try to make leak. Distinctive enough that a substring search for it
# cannot produce a false pass, and containing characters that break naive formatting.
SECRET = "Zq7!x%s{Kv}9_LEAKCANARY"
WRONG_SECRET = "Wr0ng!p%s{Kv}9_ALSOSECRET"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        failures.append(f"{label}{(' -- ' + detail) if detail else ''}")
        print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))


def _has(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def _write_encrypted_pdf(path: str, password: str) -> bool:
    """A real one-page encrypted PDF. Returns False if pypdf is not installed."""
    if not _has("pypdf"):
        return False
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(password)
    with open(path, "wb") as fh:
        writer.write(fh)
    return True


def _write_plain_pdf(path: str) -> bool:
    if not _has("pypdf"):
        return False
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as fh:
        writer.write(fh)
    return True


def _leaks(text: str) -> list[str]:
    """Any secret found in text. This is the assertion the whole suite is built around."""
    found = []
    for secret in (SECRET, WRONG_SECRET):
        if secret in text:
            found.append(secret)
    return found


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="itrprep-unlock-")
    try:
        return run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(tmp: str) -> int:
    # -------------------------------------------------------------- .env parsing
    print("\n[.env parsing]")
    env_path = os.path.join(tmp, ".env")
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write(
            "# a comment\n"
            "\n"
            f"ITRPREP_PAN={FAKE_PAN}\n"
            f"export ITRPREP_DOB={FAKE_DOB}\n"
            f'ITRPREP_PW_FORM16="{SECRET}"\n'
            "ITRPREP_PW_EMPTY=\n"
            "NOT_OURS=ignored\n"
            "malformed line without equals\n"
            "ITRPREP_PW_EQUALS=has=equals=inside\n"
        )
    parsed = unlock.read_env_file(env_path)
    check("reads a plain assignment", parsed.get("ITRPREP_PAN") == FAKE_PAN)
    check("strips an export prefix", parsed.get("ITRPREP_DOB") == FAKE_DOB)
    check("strips surrounding quotes", parsed.get("ITRPREP_PW_FORM16") == SECRET)
    check("keeps an empty value distinguishable", parsed.get("ITRPREP_PW_EMPTY") == "")
    check("keeps = inside a value",
          parsed.get("ITRPREP_PW_EQUALS") == "has=equals=inside")
    check("skips a malformed line", "malformed line without equals" not in parsed)
    check("a missing file is not an error", unlock.read_env_file(
        os.path.join(tmp, "nope")) == {})

    resolved = unlock.resolve_environment(env_path, environ={})
    check("only ITRPREP_* variables are taken from the file",
          "NOT_OURS" not in resolved, str(sorted(resolved)))
    check("each variable records where it came from",
          resolved["ITRPREP_PAN"][1] == env_path)
    overridden = unlock.resolve_environment(
        env_path, environ={"ITRPREP_PAN": "ZZZZZ0000Z"}
    )
    check("the real environment overrides the file",
          overridden["ITRPREP_PAN"] == ("ZZZZZ0000Z", "environment"))

    # ------------------------------------------------- Credential withholds its value
    # This is where secrets normally escape: an f-string in an error path, or a list of
    # objects printed while debugging.
    print("\n[Credential withholds its value]")
    credential = unlock.Credential(name="ITRPREP_PW_FORM16", _value=SECRET, origin=env_path)
    check("repr does not contain the value", not _leaks(repr(credential)),
          repr(credential))
    check("str does not contain the value", not _leaks(str(credential)))
    check("an f-string does not contain the value", not _leaks(f"{credential}"))
    # noqa UP031: percent formatting is the thing under test here, not a style choice.
    # It reaches __str__ by a different path from an f-string, and a password that
    # escapes through `"%s" % credential` in some forgotten log line is exactly the
    # accident this suite exists to rule out.
    check("%s formatting does not contain the value",
          not _leaks("%s" % credential))  # noqa: UP031
    check("a list repr does not contain the value", not _leaks(repr([credential])))
    check("a dict repr does not contain the value",
          not _leaks(repr({"c": credential})))
    check("the value is still reachable deliberately", credential.reveal() == SECRET)
    check("repr names the variable, which is what the user needs",
          "ITRPREP_PW_FORM16" in repr(credential))

    # ------------------------------------------------------ candidates, and derivation
    print("\n[candidates]")
    cands = unlock.candidates(resolved)
    names = [c.name for c in cands]
    values = [c.reveal() for c in cands]
    check("a declared literal is tried", SECRET in values)
    check("an empty ITRPREP_PW_ variable is not tried as a password",
          values.count("") == 1, str(values.count("")))
    check("the portal convention is derived: lowercase PAN + DDMMYYYY",
          FAKE_PAN.lower() + FAKE_DOB in values)
    check("the uppercase variant is also tried",
          FAKE_PAN.upper() + FAKE_DOB in values)
    check("PAN alone is tried", FAKE_PAN.lower() in values)
    check("DOB alone is tried", FAKE_DOB in values)
    check("the empty password is tried last", values[-1] == "")
    check("literals are tried before derived candidates",
          values.index(SECRET) < values.index(FAKE_PAN.lower() + FAKE_DOB))
    check("every candidate is named", all(n for n in names))
    check("candidates are unique by value", len(values) == len(set(values)))
    check("the candidate list itself does not print any value",
          not _leaks(repr(cands)))

    # NO FILENAME MINING. The pattern this module exists to replace.
    print("\n[no password is ever taken from a filename]")
    bare = unlock.candidates(unlock.resolve_environment(
        os.path.join(tmp, "no-such-env"), environ={}
    ))
    check("with nothing declared, only the empty password is a candidate",
          [c.reveal() for c in bare] == [""], str([c.name for c in bare]))
    check("a filename is never a source of candidates",
          SECRET not in [c.reveal() for c in bare])
    if _has("pypdf"):
        # The strongest form of the assertion: a file literally named after its own
        # password still does not open when nothing is declared.
        named = os.path.join(tmp, f"form16_{SECRET}.pdf")
        _write_encrypted_pdf(named, SECRET)
        attempt = unlock.unlock_file(named, os.path.join(tmp, "unlocked-fn"), bare)
        check("a file named after its own password still does not open",
              not attempt.ok, attempt.error)
        check("and that refusal does not echo the filename's secret",
              not _leaks(attempt.error), attempt.error)
        os.unlink(named)

    # ---------------------------------------------------------- describe_credentials
    print("\n[--list-credentials shows names only]")
    described = "\n".join(unlock.describe_credentials(resolved))
    check("no value appears in the listing", not _leaks(described), described)
    check("the PAN value itself does not appear either", FAKE_PAN not in described,
          described)
    check("the DOB value does not appear either", FAKE_DOB not in described)
    check("it names each variable", "ITRPREP_PW_FORM16" in described
          and unlock.PAN_VAR in described)
    check("it says whether each is set", "set" in described)
    check("it flags a variable that is set but empty",
          "SET BUT EMPTY" in described, described)
    malformed = unlock.describe_credentials({
        unlock.PAN_VAR: ("not-a-pan", "x"), unlock.DOB_VAR: ("2-3-85", "x"),
    })
    check("it warns when PAN is the wrong shape",
          any("not shaped like a PAN" in line for line in malformed))
    check("it warns when DOB is not DDMMYYYY",
          any("DDMMYYYY" in line for line in malformed))
    check("even the malformed listing shows no value",
          "not-a-pan" not in "\n".join(malformed))

    # ------------------------------------------------------------------- scrub
    print("\n[scrub is the last line of defence]")
    check("scrub removes a value that reached a string",
          not _leaks(unlock.scrub(f"boom: {SECRET}", cands)))
    check("scrub names the variable in its place",
          "ITRPREP_PW_FORM16" in unlock.scrub(f"boom: {SECRET}", cands))
    check("scrub leaves other text alone",
          "keep this" in unlock.scrub("keep this", cands))

    if not _has("pypdf"):
        print("\n[encrypted PDF]")
        print("  SKIP  pypdf not installed: pip install -r requirements-unlock.txt")
    else:
        # ------------------------------------------------ a failed unlock leaks nothing
        # The check the whole design turns on.
        print("\n[a failed unlock leaks nothing]")
        locked = os.path.join(tmp, "statement.pdf")
        _write_encrypted_pdf(locked, SECRET)
        wrong_env = os.path.join(tmp, ".env.wrong")
        with open(wrong_env, "w", encoding="utf-8") as fh:
            fh.write(f"ITRPREP_PW_FORM16={WRONG_SECRET}\nITRPREP_PAN={FAKE_PAN}\n"
                     f"ITRPREP_DOB={FAKE_DOB}\n")
        wrong_resolved = unlock.resolve_environment(wrong_env, environ={})
        wrong_cands = unlock.candidates(wrong_resolved)
        out_dir = os.path.join(tmp, "unlocked")

        result = unlock.unlock_file(locked, out_dir, wrong_cands)
        check("the wrong credential does not open the file", not result.ok)
        check("the error text contains no secret", not _leaks(result.error),
              result.error)
        check("the error names the variables that were tried",
              "ITRPREP_PW_FORM16" in result.error, result.error)
        check("the error suggests the usual cause without quoting a value",
              "DDMMYYYY" in result.error)
        check("the whole Result repr contains no secret", not _leaks(repr(result)))
        check("no partial output is left behind on failure",
              not os.path.exists(os.path.join(out_dir, "statement.pdf")))

        # A traceback is the other realistic leak path: an exception chained from a
        # library that was handed the password.
        try:
            raise unlock.UnlockError(result.error)
        except unlock.UnlockError:
            tb = traceback.format_exc()
        check("a traceback of the failure contains no secret", not _leaks(tb))

        # And the command as a user actually runs it, stdout and stderr together.
        proc = subprocess.run(
            [sys.executable, "-m", "itrprep.cli", "unlock", "--input", locked,
             "--env-file", wrong_env, "--out-dir", out_dir],
            capture_output=True, text=True, cwd=ROOT,
        )
        combined = proc.stdout + proc.stderr
        check("the CLI reports the failure", proc.returncode == 1, str(proc.returncode))
        check("nothing the CLI prints contains a secret", not _leaks(combined),
              combined[-400:])
        check("the CLI names the credential variable it tried",
              "ITRPREP_PW_FORM16" in combined)
        check("the CLI tells the user not to paste the password anywhere",
              "filename" in combined and "chat" in combined)

        # --list-credentials, the mode most likely to be run in front of someone.
        proc = subprocess.run(
            [sys.executable, "-m", "itrprep.cli", "unlock", "--list-credentials",
             "--env-file", wrong_env],
            capture_output=True, text=True, cwd=ROOT,
        )
        listing = proc.stdout + proc.stderr
        check("--list-credentials succeeds", proc.returncode == 0)
        check("--list-credentials prints no secret", not _leaks(listing), listing[-300:])
        check("--list-credentials prints no PAN or DOB value",
              FAKE_PAN not in listing and FAKE_DOB not in listing, listing[-300:])
        check("--list-credentials names the variables",
              "ITRPREP_PW_FORM16" in listing and unlock.PAN_VAR in listing)

        # -------------------------------------------------- a successful unlock
        print("\n[a successful unlock]")
        right_env = os.path.join(tmp, ".env.right")
        with open(right_env, "w", encoding="utf-8") as fh:
            fh.write(f"ITRPREP_PW_FORM16={SECRET}\n")
        right_cands = unlock.candidates(
            unlock.resolve_environment(right_env, environ={})
        )
        good = unlock.unlock_file(locked, out_dir, right_cands)
        check("the declared credential opens the file", good.ok, good.error)
        check("it reports which variable worked",
              good.credential_name == "ITRPREP_PW_FORM16", good.credential_name)
        check("it does not report the value", not _leaks(repr(good)))
        check("the decrypted copy exists", os.path.exists(good.target))
        check("the decrypted copy is in the dedicated directory",
              os.path.dirname(good.target) == out_dir)
        mode = stat.S_IMODE(os.stat(good.target).st_mode)
        check("the decrypted copy is mode 0600", mode == 0o600, oct(mode))
        dir_mode = stat.S_IMODE(os.stat(out_dir).st_mode)
        check("the output directory is owner-only", dir_mode == 0o700, oct(dir_mode))
        from pypdf import PdfReader
        check("the decrypted copy opens with no password",
              not PdfReader(good.target).is_encrypted)

        # Derivation, end to end: no literal password declared at all.
        derived_pw = FAKE_PAN.lower() + FAKE_DOB
        derived_pdf = os.path.join(tmp, "form16.pdf")
        _write_encrypted_pdf(derived_pdf, derived_pw)
        derive_env = os.path.join(tmp, ".env.derive")
        with open(derive_env, "w", encoding="utf-8") as fh:
            fh.write(f"ITRPREP_PAN={FAKE_PAN}\nITRPREP_DOB={FAKE_DOB}\n")
        derived = unlock.unlock_file(
            derived_pdf, out_dir,
            unlock.candidates(unlock.resolve_environment(derive_env, environ={})),
        )
        check("PAN plus date of birth opens a Form 16 with no password declared",
              derived.ok, derived.error)
        check("it reports the derivation by name, not by value",
              unlock.PAN_VAR in derived.credential_name
              and derived_pw not in derived.credential_name,
              derived.credential_name)

        # An unencrypted file should pass straight through, and say so.
        plain = os.path.join(tmp, "plain.pdf")
        _write_plain_pdf(plain)
        passed = unlock.unlock_file(plain, out_dir, right_cands)
        check("an unencrypted PDF is copied rather than failing", passed.ok,
              passed.error)
        check("an unencrypted PDF is reported as not encrypted",
              not passed.was_encrypted)
        check("the copy is still mode 0600",
              stat.S_IMODE(os.stat(passed.target).st_mode) == 0o600)

        # No credential declared at all, against an encrypted file.
        naked = unlock.unlock_file(locked, out_dir, bare)
        check("with nothing declared an encrypted file fails cleanly", not naked.ok)
        check("that failure explains what to declare",
              unlock.PASSWORD_PREFIX in naked.error and ".env.example" in naked.error,
              naked.error)
        check("that failure contains no secret", not _leaks(naked.error))

    if not _has("msoffcrypto"):
        print("\n[encrypted workbook]")
        print("  SKIP  msoffcrypto-tool not installed")
    else:
        print("\n[encrypted workbook]")
        # A file that is not a zip and not a real OLE container: msoffcrypto must fail,
        # and that failure must still not leak.
        fake = os.path.join(tmp, "broker.xlsx")
        with open(fake, "wb") as fh:
            fh.write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512)
        res = unlock.unlock_file(fake, os.path.join(tmp, "unlocked2"), cands)
        check("a workbook that cannot be opened fails cleanly", not res.ok)
        check("that failure contains no secret", not _leaks(res.error), res.error)
        check("no partial workbook is left behind",
              not os.path.exists(os.path.join(tmp, "unlocked2", "broker.xlsx")))

        plain_zip = os.path.join(tmp, "plain.xlsx")
        with open(plain_zip, "wb") as fh:
            fh.write(b"PK\x03\x04" + b"\x00" * 64)
        res = unlock.unlock_file(plain_zip, os.path.join(tmp, "unlocked2"), cands)
        check("an unencrypted workbook is copied through", res.ok, res.error)
        check("an unencrypted workbook is reported as not encrypted",
              not res.was_encrypted)

    # ------------------------------------------------------------ repo hygiene
    print("\n[repo hygiene]")
    with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as fh:
        ignore = fh.read()
    check(".env is gitignored", "\n.env\n" in ignore)
    check(".env.example is explicitly un-ignored", "!.env.example" in ignore)
    check("the unlock output directory is covered", "\nwork/\n" in ignore)
    check(".env.example is committed", os.path.exists(os.path.join(ROOT, ".env.example")))
    with open(os.path.join(ROOT, ".env.example"), encoding="utf-8") as fh:
        example = fh.read()
    check("the template documents the derived variables",
          unlock.PAN_VAR in example and unlock.DOB_VAR in example)
    check("the template documents the literal-password convention",
          unlock.PASSWORD_PREFIX in example)
    check("the template says an agent must not handle the password",
          "agent" in example.lower())
    check("the template contains no real-looking secret",
          "ITRPREP_PW_FORM16=" not in example.replace("# ITRPREP_PW_FORM16=", ""),
          "an uncommented literal password would be committed")

    proc = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"],
        capture_output=True, text=True, cwd=ROOT,
    )
    check(".env is not tracked by git", proc.returncode != 0, proc.stdout)

    print()
    if failures:
        print(f"FAILED -- {len(failures)} check(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All unlock / credential checks passed. No secret reached any output path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
