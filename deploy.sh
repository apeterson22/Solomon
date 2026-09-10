#!/usr/bin/env bash
set -Eeuo pipefail
ROLE="${1:-}"
MODE="${2:-upgrade}"
[[ "$ROLE" == controller || "$ROLE" == node ]] || { echo 'Usage: sudo ./deploy.sh controller|node [install|upgrade]' >&2; exit 2; }
[[ "$MODE" == install || "$MODE" == upgrade ]] || { echo 'Mode must be install or upgrade' >&2; exit 2; }
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PIP_CONSTRAINT="$ROOT/requirements-tested.txt"
if [[ "$ROOT" == /apps/solomonprime/app || "$ROOT" == /apps/solomonprime/app/* ]]; then
  echo 'Extract the release outside the live application directory before deploying.' >&2; exit 2
fi
if [[ "$MODE" == install ]]; then
  if [[ -e /etc/solomonprime/config.yaml ]]; then
    echo 'Existing configuration found. Use upgrade; install refuses to overwrite it.' >&2; exit 2
  fi
  if [[ "$ROLE" == controller ]]; then
    "$ROOT/install-controller.sh"
  else
    "$ROOT/install-node.sh"
  fi
  exec "$ROOT/scripts/upgrade-v1.0.0-common.sh" "$ROLE"
else
  if [[ "$ROLE" == controller ]]; then exec "$ROOT/upgrade-v1.0.0.sh"; else exec "$ROOT/upgrade-node-v1.0.0.sh"; fi
fi
