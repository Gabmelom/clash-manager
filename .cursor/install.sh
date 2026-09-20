#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap: ensure a Python venv toolchain and install
# the project (with dev extras) in editable mode. Safe to run repeatedly.
set -euo pipefail

# ensurepip (python3-venv) is required to create virtual environments and is not
# present on every base image. Install it only when missing.
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends python3-venv
fi

python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e '.[dev]'
