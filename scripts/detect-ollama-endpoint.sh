#!/usr/bin/env bash
set -Eeuo pipefail

# Print one healthy local Ollama base URL and nothing else. Detection is
# read-only: no service/config changes are made here.
healthy(){
  local url="${1%/}"
  [[ "$url" =~ ^https?://(127\.0\.0\.1|localhost|0\.0\.0\.0|\[::\])(:[0-9]+)?$ ]] || return 1
  # Normalize wildcard bind addresses to loopback for the client endpoint.
  url="${url/http:\/\/0.0.0.0/http:\/\/127.0.0.1}"
  url="${url/http:\/\/\[::\]/http:\/\/127.0.0.1}"
  curl -fsS --connect-timeout 1 --max-time 3 "$url/api/tags" >/dev/null 2>&1 || return 1
  printf '%s\n' "$url"
}

normalize_host(){
  local value="$1"
  value="${value#OLLAMA_HOST=}"
  value="${value%\"}"; value="${value#\"}"
  value="${value%\'}"; value="${value#\'}"
  [[ -n "$value" ]] || return 1
  [[ "$value" =~ ^https?:// ]] || value="http://$value"
  printf '%s\n' "${value%/}"
}

# Explicit override wins when healthy.
if [[ -n "${SOLOMON_OLLAMA_URL:-}" ]]; then
  candidate="$(normalize_host "$SOLOMON_OLLAMA_URL" || true)"
  [[ -n "$candidate" ]] && healthy "$candidate" && exit 0
fi

# Preserve a healthy endpoint already stored in SolomonPrime config.
if [[ -r /etc/solomonprime/config.yaml ]]; then
  candidate="$(python3 - <<'PY' 2>/dev/null || true
import yaml
try:
    d=yaml.safe_load(open('/etc/solomonprime/config.yaml')) or {}
    print(d.get('ollama_endpoint') or '')
except Exception:
    pass
PY
)"
  candidate="$(normalize_host "$candidate" || true)"
  [[ -n "$candidate" ]] && healthy "$candidate" && exit 0
fi

# Respect the actual systemd unit environment. This catches custom ports such
# as pwrgmr's OLLAMA_HOST=0.0.0.0:11436 without rewriting that service.
if systemctl show ollama.service -p LoadState --value 2>/dev/null | grep -qx loaded; then
  envline="$(systemctl show ollama.service -p Environment --value 2>/dev/null || true)"
  host="$(printf '%s\n' "$envline" | tr ' ' '\n' | sed -n 's/^OLLAMA_HOST=//p' | tail -1)"
  candidate="$(normalize_host "$host" || true)"
  [[ -n "$candidate" ]] && healthy "$candidate" && exit 0
fi

# Probe the standard port plus any TCP listen ports owned by the Ollama PID.
ports=(11434 11436)
pid="$(systemctl show ollama.service -p MainPID --value 2>/dev/null || true)"
if [[ "$pid" =~ ^[1-9][0-9]*$ ]]; then
  while read -r port; do
    [[ "$port" =~ ^[0-9]+$ ]] && ports+=("$port")
  done < <(ss -ltnp 2>/dev/null | awk -v p="pid=$pid," '$0 ~ p {n=split($4,a,":"); print a[n]}' | sort -un)
fi
for port in "${ports[@]}"; do
  healthy "http://127.0.0.1:$port" && exit 0
done

exit 1
