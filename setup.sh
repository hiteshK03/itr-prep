#!/usr/bin/env bash
# One-shot setup: virtualenv, the two runtime dependencies, and a warm FX cache.
#
# Some Ubuntu installs ship without python3-venv or system pip, and sudo is not always
# available to fix that. Where ensurepip is missing, the venv is created without pip and pip
# is bootstrapped into it from get-pip.py.

set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
echo "using $($PYTHON -V)"

if [ ! -x .venv/bin/python ]; then
    echo "creating .venv ..."
    if ! $PYTHON -m venv .venv 2>/dev/null; then
        echo "ensurepip unavailable; creating venv without pip and bootstrapping"
        rm -rf .venv
        $PYTHON -m venv --without-pip .venv
        curl -sSfL -o /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
        .venv/bin/python /tmp/get-pip.py --no-warn-script-location
    fi
fi

echo "installing runtime dependencies ..."
.venv/bin/python -m pip install -q --upgrade -r requirements.txt

if [ "${DEV:-0}" = "1" ]; then
    echo "installing dev dependencies ..."
    .venv/bin/python -m pip install -q -r requirements-dev.txt
fi

echo "caching SBI TT buying rates ..."
.venv/bin/python -m itrprep.cli fx-update

# The suites run offline, but "offline" means "reads a cache", and a fresh clone has none:
# data/ is gitignored because it is derived, and because a real user's cached tickers say
# what they hold. So the self-check printed below used to fail five checks in
# test_doctor_readback.py with "no daily prices for 12 ticker-year(s)" -- the FX cache was
# warmed here and the price cache was not. Walking both synthetic datasets fills it, which
# is what .github/workflows/tests.yml does before its own run.
#
# Not fatal. Prices come from a live third-party source, so a rate limit or an outage here
# costs the self-check and the first offline run, not the tool.
echo "caching the daily closes the self-check reads ..."
WARM_DIR="$(mktemp -d)"
trap 'rm -rf "$WARM_DIR"' EXIT
if .venv/bin/python -m itrprep.cli threshold --work tests/synthetic --years 2022-2025 \
        --out "$WARM_DIR/warm-synthetic.txt" >/dev/null 2>"$WARM_DIR/log" \
   && .venv/bin/python -m itrprep.cli threshold --work tests/synthetic_split --years 2022-2025 \
        --split-basis current --out "$WARM_DIR/warm-split.txt" >/dev/null 2>>"$WARM_DIR/log"; then
    echo "cached daily closes for $(find data/prices -name '*.json' | wc -l | tr -d ' ') ticker-years"
else
    echo "WARNING: could not cache daily closes. The tool still works, but the self-check" >&2
    echo "below will report missing prices, and --offline has nothing to read yet. Re-run" >&2
    echo "./setup.sh once the network is available. What went wrong:" >&2
    sed 's/^/  /' "$WARM_DIR/log" >&2
fi

cat <<'EOF'

Setup complete.

Next:
  .venv/bin/python -m itrprep.cli init --work work
  # fill in work/issuers.csv, work/accounts.csv and work/cash_balances.csv,
  # put your broker exports in one folder, then:
  .venv/bin/python -m itrprep.cli run --year 2025 --drop ~/dl

Self-check (no broker data needed):
  for t in tests/test_*.py; do .venv/bin/python "$t" || break; done

Where every statutory figure comes from, and what needs re-verifying each year:
  .venv/bin/python -m itrprep.cli rules --annual-only

Schema validation needs the ITD's ITR-2 schema, which is not bundled. See schemas/README.md
for the one-line download; without it, build warns loudly that its output is unverified.

Read README.md, especially "six things that will bite you".
EOF
