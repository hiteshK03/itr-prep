# Security

This tool reads a person's brokerage history and produces a tax disclosure from it. The data
is about as sensitive as personal data gets, and the failure modes are not exotic — they are
a filename, a log line and a chat transcript.

## What this tool does with your data

- **Everything runs locally.** There is no server, no account and no telemetry. Nothing about
  your holdings is uploaded anywhere.
- **Two things reach the network,** both by explicit command and both cacheable: SBI
  telegraphic-transfer reference rates from the RBI's published series, and daily closing
  prices from Yahoo's chart endpoint. Prices are requested by ticker and date. Neither request
  carries a quantity, an account identifier, or anything else about you. `--offline` disables
  both and uses only the caches.
- **Your figures stay in `work/` and `out/`,** both gitignored. They are never committed and
  never leave the machine.

## Document passwords

Form 16, CAS statements and some broker exports arrive encrypted. This tool reads the
credential from a gitignored `.env` at the repository root and uses it directly. See the
committed [`.env.example`](.env.example) for every supported variable.

**A password must never leave the process.** That is a design constraint here, not a nicety,
and it is enforced:

- `Credential` withholds its value from `repr()` and `str()`, so an f-string in an error path
  or a container printed while debugging cannot leak it.
- `pypdf` and `msoffcrypto` are handed the password, so their exception text is untrusted by
  construction. Nothing from them is re-raised or chained — a library that quoted the attempt
  back would otherwise put it in a traceback.
- Every failure names the **variable** that did not work, never its value. A wrong
  `ITRPREP_DOB` format is the usual cause, and the error says so without quoting anything.
- `unlock --list-credentials` prints variable names and set/unset only. It does not print the
  PAN or the date of birth either.
- `scrub()` is applied to anything this code prints, as a last line of defence.
- Decrypted copies are written into `work/unlocked/`, mode 0600, in a 0700 directory, so a
  decrypted statement is never briefly world-readable and one `rm -rf` removes all of them.

[`tests/test_unlock_credentials.py`](tests/test_unlock_credentials.py) is the proof. It builds
a genuinely encrypted PDF, fails to open it with the wrong credential, and asserts that the
error text, the formatted traceback and the CLI's combined stdout and stderr contain neither
the correct password nor the wrong one. **Do not weaken those checks.**

### Passwords do not go in filenames

Comparable tools mine the password out of the filename. Do not do that here, and do not add
it as a convenience. A filename ends up in shell history, in `ls` output, in a backup index,
in a screenshot, in a terminal transcript, and in whatever an agent pasted into a chat. A
password in a filename is a password in a dozen places nobody chose.

### If an AI agent is helping you

Its job is to run `itr-prep unlock --input <path>`. It should never see, ask for, or handle the
password; the code resolves the credential itself. The reason this matters more than usual is
that the whole point of this repository is that real financial data flows through
deterministic Python rather than through a model — a document password sitting in a model's
context window would be a direct regression against that, and worse than the filename
approach it replaces.

The wider form of the same principle is that a model may locate and transcribe a figure and
may never subtract, total or reconcile one. [`AGENTS.md`](AGENTS.md) states it and
[`docs/AI-ASSISTANCE.md`](docs/AI-ASSISTANCE.md) explains where a model is and is not safe on
a real filing.

## Never commit real data

Treat this repository as published, whatever its current visibility. A commit is the one
mistake here that a later commit cannot undo.

- No PAN, no account numbers, no real holdings, quantities, prices or dates.
- Fixtures use invented data. The established placeholders are tickers like `CSCO` and grant
  numbers like `RU100001`.
- `work/`, `out/`, `.env` and decrypted documents are gitignored. `.env.example` is the one
  credential file that is committed and it carries placeholders only, which
  `tests/test_unlock_credentials.py` checks.
- If you have committed real data by accident, treat it as published: rotate anything
  credential-shaped and rewrite history rather than deleting in a later commit.

## Supply chain

Runtime dependencies are `requests` and `jsonschema`. `itr-prep unlock` additionally needs
`pypdf` and `msoffcrypto-tool`, kept in a separate `requirements-unlock.txt` so a base install
carries neither. The reasoning behind not adopting the same-niche PyPI packages that appeared
alongside this tool is in the README's Supply chain section; the short version is that a
disclosure you may have to defend years later should not depend on a remote API or on
brand-new packages.

The ITD's ITR-2 JSON schema and the Excel utility are not redistributed here. Download them
from the department yourself; `schemas/README.md` has the command.

## Reporting a vulnerability

Open a GitHub issue for anything that is not itself sensitive — a path that could leak a
credential, a permissions mistake, an output that contains more than it should. If the report
would itself disclose personal data, say so in the issue without the detail and a private
channel will be arranged.

Please do not report findings about the Income Tax Department's portal, schema or utility
here. Those are the department's systems, not this tool's.
