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
