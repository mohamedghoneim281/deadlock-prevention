#!/usr/bin/env bash
# One command for Ubuntu / Debian / Raspberry Pi OS:
#   installs the build tools if missing, creates a private Python environment (.venv),
#   installs the Python packages, then builds, tests, verifies, experiments, benchmarks, plots.
# Safe to run again: it never touches anything outside this folder except the apt install.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

missing=0
for tool in g++ make python3; do
  command -v "$tool" >/dev/null 2>&1 || missing=1
done
python3 -c "import venv, ensurepip" >/dev/null 2>&1 || missing=1

if [ "$missing" = 1 ]; then
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "This script needs apt (Ubuntu, Debian or Raspberry Pi OS). Install g++, make, python3 and python3-venv first."
    exit 1
  fi
  say "Installing build tools (your password will be asked once; typing it shows nothing - that is normal)"
  sudo apt-get update
  sudo apt-get install -y build-essential python3 python3-venv python3-pip
fi

say "Creating the Python environment (.venv) and installing packages"
python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

say "Building the C++ engine and running everything (about 1-3 minutes)"
make reproduce

say "Demo walk-through"
python scripts/demo.py

printf '\n\033[1;32mDONE.\033[0m Read the summary box above (it must say ALL CHECKS PASSED).\n'
echo "Results : $(pwd)/results/RESULTS.md"
echo "Figures : $(pwd)/figures/"
