"""Opening password-protected statements, without the password ever being seen.

Why this exists
---------------
Form 16 and several broker and depository statements arrive encrypted. The obvious fix --
what comparable tools do -- is to mine the password out of the filename. That is worse than
it looks: a filename is in shell history, in `ls` output, in a backup index, in a
screenshot, in a terminal transcript and in whatever an agent pasted into a chat. A password
in a filename is a password in a dozen places nobody chose.

So credentials are declared once in a gitignored `.env` at the repository root and read
**by this code**. The user's job is to run `itr-prep unlock`; resolving the credential is not
their job and is emphatically not an agent's job.

The rule this module exists to keep
-----------------------------------
**A password must never leave this process.** Not into a log line, not into an exception
message, not into a traceback, not into a listing or a verbose mode, and not into a command
line that something else constructs. So:

- `Credential` withholds its value from `repr()` and `str()`, which is where secrets
  usually escape -- an f-string in an error path, or a container printed while debugging.
- Every failure names the **variables tried**, never their values.
- Exceptions from `pypdf` and `msoffcrypto` are swallowed rather than re-raised or chained.
  They are given the password, so their message text is untrusted by construction: a
  library that helpfully quoted the attempted password back would otherwise put it in a
  traceback. Nothing from them reaches the caller except the fact of failure.
- `scrub()` is the last line of defence, applied to anything this module prints.

`tests/test_unlock_credentials.py` asserts all of it, including that a failed unlock's
output contains neither the right password nor the wrong one.

Derivation, not enumeration
---------------------------
Most of these documents are not protected by an arbitrary secret but by a formula. The
e-filing portal's own convention, which most payroll providers follow for Form 16, is the
PAN in lower case followed by the date of birth as DDMMYYYY. Supply `ITRPREP_PAN` and
`ITRPREP_DOB` once and the candidates are derived, so a password per file is not needed.
india-itr-copilot's `unlock_documents.py` is where the convention was read from; the
filename mining that sits next to it there is deliberately not reproduced.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass

ENV_FILENAME = ".env"
PAN_VAR = "ITRPREP_PAN"
DOB_VAR = "ITRPREP_DOB"

# Literal passwords. One variable per document class, e.g. ITRPREP_PW_FORM16,
# ITRPREP_PW_ETRADE, ITRPREP_PW_FIDELITY. Every one of them is tried against every file --
# which is why the file does not have to be named after its password.
PASSWORD_PREFIX = "ITRPREP_PW_"

DEFAULT_OUT_DIR = os.path.join("work", "unlocked")

SUPPORTED_SUFFIXES = (".pdf", ".xlsx", ".xlsm", ".xls")

_PAN_RE = re.compile(r"^[A-Za-z]{5}[0-9]{4}[A-Za-z]$")
_DOB_RE = re.compile(r"^[0-9]{8}$")


class UnlockError(Exception):
    """Raised for anything that goes wrong. Never carries a credential value."""


@dataclass(frozen=True)
class Credential:
    """A named secret whose value does not print.

    `name` is safe to log and is the only thing the user is ever told. The value is
    reachable only by asking for it explicitly, which makes an accidental leak through an
    f-string, a `print(locals())` or a repr'd list impossible rather than unlikely.
    """

    name: str
    _value: str
    origin: str = ""

    def __repr__(self) -> str:  # noqa: D105
        return f"<Credential {self.name} from {self.origin or 'environment'} (value withheld)>"

    def __str__(self) -> str:  # noqa: D105
        return self.__repr__()

    def reveal(self) -> str:
        """The value. The only way to get it, and it is called in exactly two places."""
        return self._value


# ----------------------------------------------------------------- .env reading

def read_env_file(path: str) -> dict[str, str]:
    """Parse a `.env` file. Deliberately small: KEY=VALUE, `#` comments, optional quotes.

    No interpolation, no multi-line values, no shell semantics. A credential file is not a
    place for a language.
    """
    values: dict[str, str] = {}
    if not path or not os.path.exists(path):
        return values
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise UnlockError(f"could not read {path}: {exc.strerror}") from None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def resolve_environment(
    env_path: str | None = None, environ: dict[str, str] | None = None
) -> dict[str, tuple[str, str]]:
    """Every ITRPREP_* variable in play, as name -> (value, where it came from).

    The real process environment wins over the file, which is the usual dotenv contract
    and lets a one-off run override without editing anything.
    """
    environ = os.environ if environ is None else environ
    path = ENV_FILENAME if env_path is None else env_path
    merged: dict[str, tuple[str, str]] = {}
    for key, value in read_env_file(path).items():
        if key.startswith("ITRPREP_"):
            merged[key] = (value, path)
    for key, value in environ.items():
        if key.startswith("ITRPREP_"):
            merged[key] = (value, "environment")
    return merged


def describe_credentials(resolved: dict[str, tuple[str, str]]) -> list[str]:
    """Names, origins and whether each is set. Never a value. Safe to print anywhere."""
    lines: list[str] = []
    pan_set = bool(resolved.get(PAN_VAR, ("", ""))[0].strip())
    dob_raw = resolved.get(DOB_VAR, ("", ""))[0].strip()
    lines.append(
        f"{PAN_VAR:<24} {'set' if pan_set else 'NOT SET'}"
        + (f"   (from {resolved[PAN_VAR][1]})" if pan_set else "")
    )
    lines.append(
        f"{DOB_VAR:<24} {'set' if dob_raw else 'NOT SET'}"
        + (f"   (from {resolved[DOB_VAR][1]})" if dob_raw else "")
    )
    if pan_set and not _PAN_RE.match(resolved[PAN_VAR][0].strip()):
        lines.append(f"  ! {PAN_VAR} is not shaped like a PAN (AAAAA9999A)")
    if dob_raw and not _DOB_RE.match(dob_raw):
        lines.append(f"  ! {DOB_VAR} is not DDMMYYYY (8 digits)")
    literals = sorted(k for k in resolved if k.startswith(PASSWORD_PREFIX))
    if literals:
        for key in literals:
            state = "set" if resolved[key][0] else "SET BUT EMPTY"
            lines.append(f"{key:<24} {state}   (from {resolved[key][1]})")
    else:
        lines.append(f"{PASSWORD_PREFIX}*{'':<15} none declared")
    return lines


# ------------------------------------------------------------- candidate building

def candidates(resolved: dict[str, tuple[str, str]]) -> list[Credential]:
    """Every credential to try, in order, each one named.

    Literal passwords first, because a user who declared one meant it. Then the derived
    portal convention. Then the empty password, which is what an owner-password-only PDF
    opens with.

    Nothing here looks at the filename. That is the point of the module.
    """
    out: list[Credential] = []
    seen: set[str] = set()

    def add(name: str, value: str, origin: str) -> None:
        if value in seen:
            return
        seen.add(value)
        out.append(Credential(name=name, _value=value, origin=origin))

    for key in sorted(k for k in resolved if k.startswith(PASSWORD_PREFIX)):
        value, origin = resolved[key]
        if value:
            add(key, value, origin)

    pan = resolved.get(PAN_VAR, ("", ""))[0].strip()
    dob = resolved.get(DOB_VAR, ("", ""))[0].strip()
    origin = resolved.get(PAN_VAR, ("", "environment"))[1]
    if pan and dob:
        # The e-filing portal's convention, and what most payroll providers use for
        # Form 16: PAN in lower case, then the date of birth as DDMMYYYY.
        add(f"{PAN_VAR}+{DOB_VAR} (lowercase PAN + DDMMYYYY)", pan.lower() + dob, origin)
        add(f"{PAN_VAR}+{DOB_VAR} (uppercase PAN + DDMMYYYY)", pan.upper() + dob, origin)
    if pan:
        add(f"{PAN_VAR} (lowercase)", pan.lower(), origin)
        add(f"{PAN_VAR} (uppercase)", pan.upper(), origin)
    if dob:
        add(DOB_VAR, dob, resolved.get(DOB_VAR, ("", "environment"))[1])

    add("(no password)", "", "built in")
    return out


def scrub(text: str, tried: list[Credential]) -> str:
    """Remove any credential value from text about to be shown to a human.

    Belt and braces. Nothing in this module is supposed to put a value into a string in
    the first place; this is what makes that a guarantee rather than an intention.
    """
    for credential in tried:
        value = credential.reveal()
        if value:
            text = text.replace(value, f"<{credential.name} withheld>")
    return text


# ------------------------------------------------------------------- unlocking

def _decrypt_pdf(source: str, target: str, tried: list[Credential]) -> Credential | None:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        raise UnlockError(
            "PDF support needs pypdf, which is not a base dependency of this tool:\n"
            "    .venv/bin/python -m pip install -r requirements-unlock.txt"
        ) from None

    try:
        reader = PdfReader(source)
    except Exception:  # noqa: BLE001 -- message text is untrusted, see the module docstring
        raise UnlockError("could not be read as a PDF at all") from None

    if not reader.is_encrypted:
        shutil.copyfile(source, target)
        return None

    for credential in tried:
        try:
            if reader.decrypt(credential.reveal()):
                break
        except Exception:  # noqa: BLE001 -- a library given the password; never re-raised
            continue
    else:
        raise UnlockError(_no_credential_worked(tried))

    writer = PdfWriter()
    try:
        for page in reader.pages:
            writer.add_page(page)
        with open(target, "wb") as fh:
            writer.write(fh)
    except Exception:  # noqa: BLE001
        raise UnlockError("decrypted, but the pages could not be rewritten") from None
    return credential


def _decrypt_office(source: str, target: str, tried: list[Credential]) -> Credential | None:
    with open(source, "rb") as fh:
        magic = fh.read(4)
    if magic == b"PK\x03\x04":
        # A plain zip: an unencrypted xlsx/xlsm. Copy it and say so.
        shutil.copyfile(source, target)
        return None

    try:
        import msoffcrypto
    except ImportError:
        raise UnlockError(
            "spreadsheet support needs msoffcrypto-tool, which is not a base dependency:\n"
            "    .venv/bin/python -m pip install -r requirements-unlock.txt"
        ) from None

    for credential in tried:
        try:
            with open(source, "rb") as fh:
                office = msoffcrypto.OfficeFile(fh)
                office.load_key(password=credential.reveal())
                with open(target, "wb") as out:
                    office.decrypt(out)
            return credential
        except Exception:  # noqa: BLE001 -- given the password; nothing propagates
            if os.path.exists(target):
                os.unlink(target)
            continue
    raise UnlockError(_no_credential_worked(tried))


def _no_credential_worked(tried: list[Credential]) -> str:
    """The failure message. Names variables; contains no value, by construction."""
    names = [c.name for c in tried if c.name != "(no password)"]
    if not names:
        return (
            f"encrypted, and no credential is declared. Put the password in {ENV_FILENAME} "
            f"as {PASSWORD_PREFIX}<LABEL>=..., or set {PAN_VAR} and {DOB_VAR} so it can be "
            f"derived. See .env.example."
        )
    return (
        "encrypted, and none of the declared credentials opened it. Tried, in order: "
        + "; ".join(names)
        + f". Check the values in {ENV_FILENAME} -- and note that a wrong "
        f"{DOB_VAR} format (it must be DDMMYYYY) is the usual cause."
    )


def prepare_out_dir(out_dir: str) -> None:
    """Create the output directory, owner-only.

    A separate directory rather than writing beside the encrypted original: one gitignore
    entry covers it, and `rm -rf` on one path removes every decrypted copy.
    """
    os.makedirs(out_dir, exist_ok=True)
    try:
        os.chmod(out_dir, 0o700)
    except OSError:
        pass  # some filesystems, and Windows ACLs, do not take a mode


@dataclass
class Result:
    """What happened to one file. `credential_name` is a name, never a value."""

    source: str
    target: str = ""
    credential_name: str = ""
    was_encrypted: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def unlock_file(
    source: str, out_dir: str, tried: list[Credential]
) -> Result:
    """Write a decrypted copy of one file into `out_dir`, mode 0600."""
    suffix = os.path.splitext(source)[1].lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return Result(source, error=f"unsupported type {suffix or '(none)'}")

    prepare_out_dir(out_dir)
    target = os.path.join(out_dir, os.path.basename(source))
    # Create the destination owner-only BEFORE anything is written into it, so a
    # decrypted statement is never briefly world-readable.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)

    try:
        if suffix == ".pdf":
            used = _decrypt_pdf(source, target, tried)
        else:
            used = _decrypt_office(source, target, tried)
    except UnlockError as exc:
        if os.path.exists(target):
            os.unlink(target)
        return Result(source, error=scrub(str(exc), tried))
    except Exception as exc:  # noqa: BLE001 -- never let a library's text through raw
        if os.path.exists(target):
            os.unlink(target)
        return Result(source, error=scrub(f"{type(exc).__name__}", tried))

    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return Result(
        source=source,
        target=target,
        credential_name=used.name if used else "",
        was_encrypted=used is not None,
    )


def collect_inputs(path: str) -> list[str]:
    """The files to work on: one file, or the supported files directly inside a folder."""
    if os.path.isfile(path):
        return [path]
    if not os.path.isdir(path):
        raise UnlockError(f"no such file or directory: {path}")
    return sorted(
        os.path.join(path, name)
        for name in os.listdir(path)
        if os.path.isfile(os.path.join(path, name))
        and os.path.splitext(name)[1].lower() in SUPPORTED_SUFFIXES
    )
