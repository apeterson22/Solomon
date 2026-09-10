#!/usr/bin/env bash
set -Eeuo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
exec "$SRC/scripts/upgrade-v1.0.0-common.sh" node
