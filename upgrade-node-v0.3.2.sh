#!/usr/bin/env bash
set -Eeuo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
exec "$SRC/scripts/upgrade-v0.3.2-common.sh" node
