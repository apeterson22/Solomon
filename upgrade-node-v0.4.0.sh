#!/usr/bin/env bash
set -Eeuo pipefail
echo 'upgrade-node-v0.4.0.sh is retained as a compatibility entry point; upgrading to SolomonPrime v1.0.0.' >&2
exec "$(cd "$(dirname "$0")" && pwd)/upgrade-node-v1.0.0.sh" "$@"
