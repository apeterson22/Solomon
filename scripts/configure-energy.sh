#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="$(systemctl show solomonprime -p User --value)"
APP_GROUP="$(id -gn "$APP_USER")"
install -o "$APP_USER" -g "$APP_GROUP" -m 0640 "$SRC/config/energy.yaml" /var/lib/solomonprime/energy.yaml
if ! command -v pdftotext >/dev/null 2>&1; then
  echo 'Warning: pdftotext is absent; TED will use the configured rate, but automatic Chickasaw PDF refresh is unavailable.' >&2
fi
systemctl restart solomonprime
for _ in $(seq 1 90); do
  curl -fsS http://127.0.0.1:8765/health >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:8765/health >/dev/null || { journalctl -u solomonprime -n 120 --no-pager; exit 3; }
sleep 2
KEY="$(cat /etc/solomonprime/api.key)"
curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/energy/status | jq
