#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
command -v docker >/dev/null || { echo 'Docker is not installed; skipping Open WebUI Admin link.' >&2; exit 0; }
docker inspect open-webui >/dev/null 2>&1 || { echo 'Open WebUI container is not installed; skipping Admin link.' >&2; exit 0; }
ENV_FILE=/etc/solomonprime/open-webui.env

# RC4 can adopt an existing SolomonPrime-compatible Open WebUI deployment even
# when earlier installs did not leave an env-file behind. Copy the container's
# effective environment into a root-only file, then let the existing guarded
# integration logic modify only SolomonPrime-owned keys. No container is
# recreated unless it uses the expected persistent open-webui volume.
if [[ ! -s "$ENV_FILE" ]]; then
  install -d -m 0755 /etc/solomonprime
  TMP_ADOPT="$(mktemp)"
  python3 - "$TMP_ADOPT" <<'PYENV'
import json, subprocess, sys
out=sys.argv[1]
data=json.loads(subprocess.check_output(['docker','inspect','open-webui'], text=True))[0]
env=data.get('Config',{}).get('Env') or []
with open(out,'w',encoding='utf-8') as f:
    for item in env:
        if '\n' in item or '\r' in item or '=' not in item:
            continue
        f.write(item+'\n')
PYENV
  install -o root -g root -m 0600 "$TMP_ADOPT" "$ENV_FILE"
  rm -f "$TMP_ADOPT"
  echo "Adopted existing Open WebUI environment into $ENV_FILE"
fi

ADMIN_URL="${SOLOMON_ADMIN_URL:-}"
if [[ -z "$ADMIN_URL" ]]; then
  # Multi-homed controllers can have direct worker, LAN, Wi-Fi and Tailscale
  # addresses. The default-route source is the address normal LAN clients can
  # generally reach; enumeration order is not a routing decision.
  LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++)if($i=="src"){print $(i+1);exit}}')"
  [[ -n "$LAN_IP" ]] || LAN_IP="$(ip -o -4 addr show scope global | awk '$2 !~ /docker|virbr|br-|veth|tailscale/ {split($4,a,"/"); print a[1]; exit}')"
  [[ -n "$LAN_IP" ]] || LAN_IP=127.0.0.1
  ADMIN_URL="http://$LAN_IP:8765/admin"
fi
[[ "$ADMIN_URL" =~ ^https?://[^[:space:]]+/admin$ ]] || { echo 'SOLOMON_ADMIN_URL must be an http(s) URL ending in /admin' >&2; exit 2; }
BANNERS="$(jq -cn --arg url "$ADMIN_URL" '[{"id":"solomonprime-admin-v040","type":"info","title":"SolomonPrime Operator Console","content":("<a href=\""+$url+"\" target=\"_blank\" rel=\"noopener\">Open Admin workspace</a> for fleet, models, calendars, voice, edge/RF, TED, configuration, and documentation."),"dismissible":false,"timestamp":1788480000},{"id":"solomonprime-routing-v040","type":"info","title":"Live system tools require a SolomonPrime model","content":"Direct provider models cannot query SolomonPrime fleet state. Select SolomonPrime for orchestrated local tools and governed cross-model review.","dismissible":true,"timestamp":1788566400}]')"

TMP="$(mktemp)"
OLD=''
ROLLBACK_REQUIRED=false
cleanup(){
  rc=$?
  rm -f "$TMP"
  if [[ $rc -ne 0 && "$ROLLBACK_REQUIRED" == true && -n "$OLD" ]] && docker inspect "$OLD" >/dev/null 2>&1; then
    docker rm -f open-webui >/dev/null 2>&1 || true
    docker rename "$OLD" open-webui >/dev/null 2>&1 || true
    docker start open-webui >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
grep -Ev '^(WEBUI_BANNERS|DEFAULT_MODELS|MODEL_ORDER_LIST)=' "$ENV_FILE" >"$TMP" || true
printf 'WEBUI_BANNERS=%s\n' "$BANNERS" >>"$TMP"
printf '%s\n' 'DEFAULT_MODELS=solomonprime' 'MODEL_ORDER_LIST=["solomonprime","solomonprime-local","solomonprime-reviewed"]' >>"$TMP"
install -o root -g root -m 0600 "$TMP" "$ENV_FILE"

# This deployment is owned by SolomonPrime and was created with this named
# volume. Refuse to recreate an unrelated/custom container.
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/app/backend/data"}}{{.Name}}{{end}}{{end}}' open-webui | grep -qx 'open-webui' || {
  echo 'Open WebUI does not use the expected persistent volume; env updated but container was not recreated.' >&2
  exit 0
}
IMAGE="${SOLOMON_OPENWEBUI_IMAGE_OVERRIDE:-$(docker inspect -f '{{.Config.Image}}' open-webui)}"
OLD="open-webui-before-admin-$(date -u +%Y%m%dT%H%M%SZ)"
docker stop open-webui >/dev/null
docker rename open-webui "$OLD"
ROLLBACK_REQUIRED=true
if ! docker run -d \
  --name open-webui \
  --restart unless-stopped \
  -p 0.0.0.0:3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  --env-file "$ENV_FILE" \
  -v open-webui:/app/backend/data \
  "$IMAGE" >/dev/null; then
  echo 'Open WebUI Admin-link restart failed; original container restored.' >&2
  exit 1
fi

for _ in $(seq 1 120); do
  curl -fsS http://127.0.0.1:3000/ >/dev/null 2>&1 && break
  sleep 1
done
if ! curl -fsS http://127.0.0.1:3000/ >/dev/null 2>&1; then
  echo 'Open WebUI did not become ready; original container restored.' >&2
  exit 1
fi
if ! curl -fsS http://127.0.0.1:3000/api/version | jq -e '.version|length>0' >/dev/null \
  || ! curl -fsS http://127.0.0.1:8765/admin | grep -q 'SolomonPrime Admin' \
  || ! docker exec open-webui sh -lc 'curl -fsS -H "Authorization: Bearer $OPENAI_API_KEY" "$OPENAI_API_BASE_URL/tools/self-test"' | jq -e '.state=="ok"' >/dev/null \
  || ! docker exec open-webui sh -lc 'curl -fsS -H "Authorization: Bearer $OPENAI_API_KEY" "$OPENAI_API_BASE_URL/models"' | jq -e '.data[] | select(.id=="solomonprime")' >/dev/null \
  || ! docker exec open-webui printenv WEBUI_BANNERS | grep -Fq "$ADMIN_URL"; then
  echo 'Open WebUI integration validation failed; original container restored.' >&2
  exit 1
fi
docker rm "$OLD" >/dev/null
ROLLBACK_REQUIRED=false
echo "Open WebUI preserved; SolomonPrime Admin link: $ADMIN_URL"
