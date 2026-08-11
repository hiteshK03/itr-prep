"""Which machines can drive the ITD's Excel utility, and how to say so plainly.

Everything else in this package is plain Python and runs anywhere: parsing broker exports,
lot matching, specified-date FX conversion, split restatement, the threshold report, schema
validation and emitting Schedule FA JSON. Exactly one step is not portable -- `itr-prep
import`, which drives the department's `.xlsm` utility -- and this module is the single
place that knows it.

The requirement is not "Windows" in the `sys.platform` sense. The tested host is Ubuntu
under WSL2 driving Excel on the Windows side through `powershell.exe`, and that reports
itself as Linux. So what is detected is the *capability* -- a reachable Windows Excel --
rather than the name of the operating system.

Why the utility cannot simply be run somewhere else is a fact about the utility, not a
choice made here: its VBA binds Windows CryptoAPI through `Declare PtrSafe ... Lib
"Advapi32"` and builds Windows-only COM objects (`Scripting.Dictionary` over a thousand
times, `MSXML2.DOMDocument`, `Scripting.FileSystemObject`), none of which exist in Excel
for Mac. See the README's "Where this runs".

**Where this boundary stops, deliberately.** `require()` gates on Windows Excel being
*reachable*, not on Excel being *installed*. A WSL box with interop and no Excel therefore
passes here and fails later, inside COM. That is not an oversight, but it is a real gap:
the only way to ask whether Excel is installed is to build `Excel.Application`, which is
the import step itself, and a pre-flight probe would add a second COM path -- with its own
timeouts, its own zombie Excel processes and its own failure modes -- to gate a path this
project can only test on one host. So the answer is downstream instead:
`scripts/import_to_utility.py:explain_no_excel` recognises the `80040154 Class not
registered` signature and turns it into the same plain explanation `explain()` gives,
rather than leaving the reader with a raw CLSID.
"""

from __future__ import annotations

import shutil
import sys

WINDOWS = "windows"
WSL = "wsl"


class UnsupportedHost(RuntimeError):
    """This machine cannot reach an Excel that could run the utility."""


def detect(platform_name: str | None = None, which=None) -> str | None:
    """`WINDOWS`, `WSL`, or None when no Windows Excel is reachable.

    Both arguments are injectable so the behaviour on every host can be asserted from
    any host -- a check that only runs on the machine it describes proves nothing.
    """
    platform_name = sys.platform if platform_name is None else platform_name
    which = shutil.which if which is None else which
    if platform_name.startswith("win") or platform_name == "cygwin":
        return WINDOWS
    # WSL interop: `powershell.exe` launches the Windows-side shell and `wslpath`
    # translates the paths it will be handed. Without both, there is nothing to drive.
    if which("powershell.exe") and which("wslpath"):
        return WSL
    return None


def explain(platform_name: str | None = None) -> str:
    """Why the import step will not run here, and what to do instead."""
    platform_name = sys.platform if platform_name is None else platform_name
    return (
        "`itr-prep import` drives the Income Tax Department's ITR-2 utility, which is an\n"
        "Excel workbook whose macros only run under Excel for Windows.\n\n"
        f"This host reports itself as `{platform_name}`, and no Windows Excel is reachable\n"
        "from it: this is neither a Windows Python nor a WSL shell with `powershell.exe`\n"
        "and `wslpath` on PATH.\n\n"
        "Nothing else in this tool needs Windows. `run`, `build`, `doctor`, `threshold`\n"
        "and `validate` are plain Python, and the Schedule FA JSON and audit CSV they\n"
        "produce are already complete. Only the last step -- putting them into the\n"
        "department's workbook -- is tied to a platform.\n\n"
        "Two ways to file that JSON from here:\n\n"
        "  1. The department's Common Offline Utility for macOS, which covers ITR-2 and\n"
        "     takes a prepared JSON through \"Import draft ITR filled in Online mode or\n"
        "     import JSON generated from Excel/HTML utility\". It validates and generates\n"
        "     the upload file itself, so no Excel is involved. This project has NOT\n"
        "     tested it -- check every Schedule FA row in the utility before filing.\n\n"
        "  2. Windows 11 in a virtual machine, where `itr-prep import` runs unchanged.\n"
        "     That is the tested path; only the host changes.\n\n"
        "The README's \"Where this runs\" section has both, and says which parts of each\n"
        "are established and which are not."
    )


def require(platform_name: str | None = None, which=None) -> str:
    """Return the host kind, or raise `UnsupportedHost` explaining why there is none."""
    kind = detect(platform_name, which)
    if kind is None:
        raise UnsupportedHost(explain(platform_name))
    return kind
