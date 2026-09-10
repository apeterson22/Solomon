#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
install -d -o root -g root -m 0755 /apps/solomonprime-build
python3 -m venv /apps/solomonprime-build/.venv
/apps/solomonprime-build/.venv/bin/pip install -r "$ROOT/requirements-tested.txt"
chown -R root:root /apps/solomonprime-build
chmod -R go-w /apps/solomonprime-build
