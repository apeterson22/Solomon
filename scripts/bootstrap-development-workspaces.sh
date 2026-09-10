#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${SOLOMON_USER:-$(systemctl show solomonprime -p User --value 2>/dev/null || true)}"
APP_USER="${APP_USER:-${SUDO_USER:-solomonprime}}"
DEV_ROOT=/apps/solomonprime-development

install -d -o "$APP_USER" -g "$(id -gn "$APP_USER")" -m 0750 "$DEV_ROOT"
if [[ ! -d "$DEV_ROOT/solomonprime/.git" ]]; then
  install -d -o "$APP_USER" -g "$(id -gn "$APP_USER")" -m 0750 "$DEV_ROOT/solomonprime"
  rsync -a --delete --exclude '.venv' --exclude 'dist' --exclude '*.zip' --exclude '*.tar.gz' \
    "$SRC/" "$DEV_ROOT/solomonprime/"
  runuser -u "$APP_USER" -- git -C "$DEV_ROOT/solomonprime" init -b development
  runuser -u "$APP_USER" -- git -C "$DEV_ROOT/solomonprime" add .
  runuser -u "$APP_USER" -- git -C "$DEV_ROOT/solomonprime" \
    -c user.name=SolomonPrime -c user.email=local-only@solomonprime.invalid commit -m 'Local v1.0.0 development baseline'
else
  echo 'Existing SolomonPrime development repository preserved.'
fi

if [[ ! -d "$DEV_ROOT/tricorder-prime/.git" ]]; then
  install -d -o "$APP_USER" -g "$(id -gn "$APP_USER")" -m 0750 "$DEV_ROOT/tricorder-prime"
  rsync -a --delete "$SRC/mobile/tricorder-prime/" "$DEV_ROOT/tricorder-prime/"
  runuser -u "$APP_USER" -- git -C "$DEV_ROOT/tricorder-prime" init -b development
  runuser -u "$APP_USER" -- git -C "$DEV_ROOT/tricorder-prime" add .
  runuser -u "$APP_USER" -- git -C "$DEV_ROOT/tricorder-prime" \
    -c user.name=SolomonPrime -c user.email=local-only@solomonprime.invalid commit -m 'Tricorder v1.0.0 integration baseline'
else
  echo 'Existing Tricorder development repository preserved.'
fi
chown -R "$APP_USER:$(id -gn "$APP_USER")" "$DEV_ROOT"
echo "Development workspaces ready at $DEV_ROOT; no remote was configured and no secrets were copied."
