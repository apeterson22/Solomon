#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
[[ -s /etc/solomonprime/api.key ]] || { echo 'Missing SolomonPrime API key' >&2; exit 2; }
command -v docker >/dev/null || { echo 'Docker is required' >&2; exit 2; }

install -d -m 0755 /etc/solomonprime
ENV_FILE=/etc/solomonprime/open-webui.env
TMP="$(mktemp)"
ENV_BACKUP="$(mktemp)"
HAD_ENV=false
COMMITTED=false
if [[ -f "$ENV_FILE" ]]; then cp -a "$ENV_FILE" "$ENV_BACKUP"; HAD_ENV=true; fi
cleanup(){
  if [[ "$COMMITTED" != true ]]; then
    if [[ "$HAD_ENV" == true ]]; then cp -a "$ENV_BACKUP" "$ENV_FILE"; else rm -f "$ENV_FILE"; fi
  fi
  rm -f "$TMP" "$ENV_BACKUP"
}
trap cleanup EXIT

# Keep the deployment identity and any unrelated administrator settings. Only
# replace values owned by the SolomonPrime integration.
SECRET=''
if [[ -f "$ENV_FILE" ]]; then
  SECRET="$(grep '^WEBUI_SECRET_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
  grep -Ev '^(WEBUI_NAME|WEBUI_SECRET_KEY|ENABLE_PERSISTENT_CONFIG|ENABLE_OLLAMA_API|ENABLE_OPENAI_API|ENABLE_SIGNUP|OPENAI_API_BASE_URL|OPENAI_API_KEY|DEFAULT_MODELS|MODEL_ORDER_LIST|AUDIO_STT_ENGINE|WHISPER_MODEL|WHISPER_COMPUTE_TYPE|WHISPER_VAD_FILTER|AUDIO_TTS_ENGINE)=' "$ENV_FILE" >"$TMP" || true
fi
if [[ -z "$SECRET" ]] && docker inspect open-webui >/dev/null 2>&1; then
  SECRET="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' open-webui | sed -n 's/^WEBUI_SECRET_KEY=//p' | head -1)"
fi
[[ -n "$SECRET" ]] || SECRET="$(openssl rand -hex 32)"
API_KEY="$(cat /etc/solomonprime/api.key)"
{
  printf '%s\n' \
    'WEBUI_NAME=SolomonPrime' \
    "WEBUI_SECRET_KEY=$SECRET" \
    'ENABLE_PERSISTENT_CONFIG=False' \
    'ENABLE_OLLAMA_API=False' \
    'ENABLE_OPENAI_API=True' \
    'ENABLE_SIGNUP=False' \
    'OPENAI_API_BASE_URL=http://host.docker.internal:8765/v1' \
    "OPENAI_API_KEY=$API_KEY" \
    'DEFAULT_MODELS=solomonprime' \
    'MODEL_ORDER_LIST=["solomonprime","solomonprime-local","solomonprime-reviewed"]' \
    'AUDIO_STT_ENGINE=' \
    'WHISPER_MODEL=base' \
    'WHISPER_COMPUTE_TYPE=int8' \
    'WHISPER_VAD_FILTER=True' \
    'AUDIO_TTS_ENGINE='
} >>"$TMP"
install -o root -g root -m 0600 "$TMP" "$ENV_FILE"
unset API_KEY SECRET

IMAGE="${OPENWEBUI_IMAGE:-ghcr.io/open-webui/open-webui:main}"
docker pull "$IMAGE"

# A first install has nothing to restore. Existing installations are replaced
# only by link-openwebui-admin.sh, which keeps the old container until all
# health and SolomonPrime integration checks pass.
if ! docker inspect open-webui >/dev/null 2>&1; then
  docker run -d \
    --name open-webui \
    --restart unless-stopped \
    -p 0.0.0.0:3000:8080 \
    --add-host=host.docker.internal:host-gateway \
    --env-file "$ENV_FILE" \
    -v open-webui:/app/backend/data \
    "$IMAGE" >/dev/null
fi

SOLOMON_OPENWEBUI_IMAGE_OVERRIDE="$IMAGE" \
  "$(dirname "$0")/link-openwebui-admin.sh"
COMMITTED=true

# Browser microphone APIs require a secure context. Preserve other Serve
# mappings and add an HTTPS tailnet endpoint when Tailscale is authenticated.
if command -v tailscale >/dev/null 2>&1 && tailscale ip -4 >/dev/null 2>&1; then
  if ! tailscale serve status 2>/dev/null | grep -q '127.0.0.1:3000'; then
    tailscale serve --bg http://127.0.0.1:3000 >/dev/null 2>&1 || true
  fi
  tailscale serve status || true
else
  echo 'WARNING: direct LAN HTTP is not suitable for microphone or voice approval. Configure trusted HTTPS before enabling voice.' >&2
fi
