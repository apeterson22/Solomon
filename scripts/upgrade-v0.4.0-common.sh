#!/usr/bin/env bash
set -Eeuo pipefail
echo 'upgrade-v0.4.0-common.sh is retained for compatibility; running the v1.0.0 migration.' >&2
exec "$(cd "$(dirname "$0")" && pwd)/upgrade-v1.0.0-common.sh" "$@"
