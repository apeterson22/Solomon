#!/usr/bin/env bash
set -Eeuo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
exec "$SRC/install-job-broker.sh" "$@"
