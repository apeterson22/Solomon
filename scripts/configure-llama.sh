#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 1; }
APP_USER="${SOLOMON_USER:-${SUDO_USER:-solomonprime}}"
MODEL="${SOLOMON_MODEL_PATH:-}"
PORT="${SOLOMON_LLAMA_PORT:-8081}"
CTX="${SOLOMON_LLAMA_CTX:-8192}"
BIN="${SOLOMON_LLAMA_BIN:-/opt/llama.cpp/build/bin/llama-server}"
KEYFILE="${SOLOMON_LLAMA_KEY_FILE:-/etc/solomonprime/llama-api.key}"
SERVICE="${SOLOMON_LLAMA_SERVICE:-solomon-llama.service}"
UNIT="/etc/systemd/system/$SERVICE"
BACKUP="${UNIT}.bak.$(date +%Y%m%dT%H%M%S)"

[[ -x "$BIN" ]] || { echo "Missing $BIN"; exit 2; }
[[ -n "$MODEL" && -r "$MODEL" ]] || { echo "Set SOLOMON_MODEL_PATH to a readable GGUF model"; exit 2; }
id "$APP_USER" >/dev/null || { echo "Missing user $APP_USER"; exit 2; }
install -d -m 0755 /etc/solomonprime /usr/local/libexec
if [[ ! -s "$KEYFILE" ]]; then openssl rand -hex 32 >"$KEYFILE"; chmod 640 "$KEYFILE"; chown root:"$APP_USER" "$KEYFILE"; fi
if [[ -f "$UNIT" ]]; then cp -a "$UNIT" "$BACKUP"; fi

cat >/usr/local/libexec/solomon-llama-preflight <<PREFLIGHT
#!/usr/bin/env bash
set -euo pipefail
[[ -r "$MODEL" ]]
'$BIN' --version >/dev/null
PREFLIGHT
chmod 755 /usr/local/libexec/solomon-llama-preflight

cat >"$UNIT" <<UNITFILE
[Unit]
Description=SolomonPrime local llama.cpp inference
After=network.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
SupplementaryGroups=video render
ExecStartPre=/usr/local/libexec/solomon-llama-preflight
ExecStart=
ExecStart=$BIN \\
  --model $MODEL \\
  --host 0.0.0.0 \\
  --port $PORT \\
  --ctx-size $CTX \\
  --parallel 1 \\
  --cache-type-k q8_0 \\
  --cache-type-v q8_0 \\
  --flash-attn auto \\
  --api-key-file $KEYFILE \\
  --cors-origins localhost \\
  --metrics \\
  --no-webui
Restart=on-failure
RestartSec=5
TimeoutStartSec=300
LimitNOFILE=1048576
User=$APP_USER
Group=$APP_USER

[Install]
WantedBy=multi-user.target
UNITFILE

systemctl stop "$SERVICE" 2>/dev/null || true
if ss -ltnp 2>/dev/null | grep -q ":$PORT "; then
  echo "Port $PORT is still occupied after stopping $SERVICE. Refusing to kill an unknown process."
  ss -ltnp | grep ":$PORT " || true
  [[ -f "$BACKUP" ]] && cp -a "$BACKUP" "$UNIT" || rm -f "$UNIT"
  systemctl daemon-reload
  exit 3
fi
systemctl daemon-reload
systemctl reset-failed "$SERVICE" || true
systemctl enable "$SERVICE" >/dev/null 2>&1 || true
systemctl start "$SERVICE"
KEY="$(cat "$KEYFILE")"
ok=0
for _ in $(seq 1 180); do
  if curl -fsS -H "Authorization: Bearer $KEY" "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
if [[ $ok -ne 1 ]]; then
  echo "llama.cpp failed health check; rolling back this unit."
  journalctl -u "$SERVICE" -n 100 --no-pager || true
  systemctl stop "$SERVICE" || true
  [[ -f "$BACKUP" ]] && cp -a "$BACKUP" "$UNIT" || rm -f "$UNIT"
  systemctl daemon-reload
  systemctl start "$SERVICE" || true
  exit 4
fi

echo "llama.cpp healthy on port $PORT"
sudo -u "$APP_USER" "$BIN" --list-devices || true
curl -fsS -H "Authorization: Bearer $KEY" "http://127.0.0.1:$PORT/v1/models" | head -c 1000; echo
