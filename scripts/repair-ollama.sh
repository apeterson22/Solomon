#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
APP_USER="${SOLOMON_USER:-$(systemctl show solomonprime -p User --value 2>/dev/null || true)}"
APP_USER="${APP_USER:-${SUDO_USER:-solomonprime}}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

find_bin(){
  local candidate user_path
  user_path="$(runuser -u "$APP_USER" -- sh -lc 'command -v ollama' 2>/dev/null || true)"
  for candidate in "${SOLOMON_OLLAMA_BIN:-}" "$user_path" /usr/local/bin/ollama /usr/bin/ollama /snap/bin/ollama; do
    [[ -n "$candidate" && -x "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

# Never force a healthy custom Ollama service back to 11434. Discover its
# actual local endpoint first and preserve it.
if OLLAMA_URL="$($SCRIPT_DIR/detect-ollama-endpoint.sh 2>/dev/null)"; then
  echo "Ollama endpoint: $OLLAMA_URL"
  echo 'Ollama daemon is already healthy.'
  exit 0
fi
OLLAMA_URL="${SOLOMON_OLLAMA_URL:-http://127.0.0.1:11434}"
echo "Ollama endpoint: $OLLAMA_URL"

BIN="$(find_bin)" || {
  echo 'No existing Ollama executable was found. This repair does not download unreviewed software.' >&2
  echo 'Install Ollama from its official distribution, then rerun this script.' >&2
  exit 2
}
echo "Using existing executable: $BIN"

if [[ "$(systemctl show ollama.service -p LoadState --value 2>/dev/null || true)" == loaded ]]; then
  # Preserve existing unit and custom environment. Merely ensure it is active.
  systemctl enable --now ollama.service
else
  install -d -o "$APP_USER" -g "$(id -gn "$APP_USER")" -m 0750 /var/lib/ollama
  install -d -m 0755 /etc/systemd/system
  cat >/etc/systemd/system/ollama.service <<UNIT
[Unit]
Description=Ollama local model service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$(id -gn "$APP_USER")
Environment=HOME=/var/lib/ollama
Environment=OLLAMA_HOST=127.0.0.1:11434
ExecStart=$BIN serve
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/lib/ollama

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now ollama.service
fi

for _ in $(seq 1 30); do
  if detected="$($SCRIPT_DIR/detect-ollama-endpoint.sh 2>/dev/null)"; then
    echo "Ollama daemon recovered successfully at $detected"
    exit 0
  fi
  sleep 1
done
systemctl status ollama.service --no-pager -l || true
journalctl -u ollama.service -n 60 --no-pager || true
echo 'Ollama did not become healthy; no models were changed.' >&2
exit 3
