#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
APP_USER="$(systemctl show solomonprime -p User --value)"
APP_GROUP="$(id -gn "$APP_USER")"
SECRETS=/etc/solomonprime/secrets
CONFIG=/etc/solomonprime/cloud-providers.yaml
MAIN_CONFIG=/etc/solomonprime/config.yaml
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="${CONFIG}.before-${STAMP}"
MAIN_BACKUP="${MAIN_CONFIG}.before-${STAMP}"
CONFIG_EXISTED=false
install -d -o root -g "$APP_GROUP" -m 0750 "$SECRETS"
if [[ -f "$CONFIG" ]]; then cp -a "$CONFIG" "$BACKUP"; CONFIG_EXISTED=true; fi
cp -a "$MAIN_CONFIG" "$MAIN_BACKUP"

store_key(){
  local label="$1" path="$2" value tmp
  if [[ -s "$path" ]]; then
    read -rsp "$label API key (leave blank to keep existing): " value; echo
    [[ -n "$value" ]] || return 0
  else
    read -rsp "$label API key (leave blank to disable): " value; echo
    [[ -n "$value" ]] || return 1
  fi
  tmp="$(mktemp)"; printf '%s\n' "$value" >"$tmp"; unset value
  install -o root -g "$APP_GROUP" -m 0640 "$tmp" "$path"
  command shred -u "$tmp" 2>/dev/null || find "$tmp" -delete
}

check_key(){
  local label="$1" path="$2" url="$3" header="$4" prefix="${5:-}" key
  [[ -s "$path" ]] || return 1
  key="$(<"$path")"
  if curl -fsS --max-time 20 -H "$header: ${prefix}${key}" "$url" -o /dev/null; then
    echo "$label credential accepted."
    return 0
  fi
  echo "$label credential validation failed; provider disabled." >&2
  return 1
}

OPENAI_PRESENT=false; OPENROUTER_ENABLED=false; GEMINI_ENABLED=false
store_key OpenAI "$SECRETS/openai.key" && OPENAI_PRESENT=true || true
store_key OpenRouter "$SECRETS/openrouter.key" || true
store_key Gemini "$SECRETS/gemini.key" || true

if [[ "$OPENAI_PRESENT" == true ]]; then
  check_key OpenAI "$SECRETS/openai.key" https://api.openai.com/v1/models Authorization 'Bearer ' || OPENAI_PRESENT=false
fi
if check_key Gemini "$SECRETS/gemini.key" https://generativelanguage.googleapis.com/v1beta/models x-goog-api-key; then
  echo 'Strict free-only mode requires a Gemini Free Tier project with billing disabled.'
  read -rp 'Type YES to confirm this Gemini project cannot create charges: ' answer
  [[ "$answer" == YES ]] && GEMINI_ENABLED=true
fi
if [[ -s "$SECRETS/openrouter.key" ]]; then
  OPENROUTER_LIMIT_JSON="$(mktemp)"; openrouter_key="$(<"$SECRETS/openrouter.key")"
  if curl -fsS --max-time 20 -H "Authorization: Bearer $openrouter_key" https://openrouter.ai/api/v1/key -o "$OPENROUTER_LIMIT_JSON" &&
     jq -e '.data.limit != null and .data.limit_remaining != null' "$OPENROUTER_LIMIT_JSON" >/dev/null; then
    OPENROUTER_ENABLED=true; echo 'OpenRouter credential and finite per-key limit accepted.'
  else
    echo 'OpenRouter finite key-limit check failed; provider disabled.' >&2
  fi
  unset openrouter_key
  command shred -u "$OPENROUTER_LIMIT_JSON" 2>/dev/null || find "$OPENROUTER_LIMIT_JSON" -delete
fi

read -rp 'Ollama daemon URL [http://127.0.0.1:11434]: ' OLLAMA_URL
OLLAMA_URL="${OLLAMA_URL:-${SOLOMON_OLLAMA_URL:-http://127.0.0.1:11434}}"; OLLAMA_URL="${OLLAMA_URL%/}"
OLLAMA_AVAILABLE=false; OLLAMA_REASON="daemon unreachable at $OLLAMA_URL"
OLLAMA_TAGS="$(mktemp)"
if curl -fsS --max-time 8 "$OLLAMA_URL/api/tags" -o "$OLLAMA_TAGS"; then
  OLLAMA_AVAILABLE=true; OLLAMA_REASON='daemon reachable'
fi
mapfile -t OLLAMA_LOCAL_MODELS < <(jq -r '.models[]?.name // .models[]?.model // empty' "$OLLAMA_TAGS" 2>/dev/null | awk '$0 !~ /(:cloud|-cloud)$/')
mapfile -t OLLAMA_CLOUD_MODELS < <(jq -r '.models[]?.name // .models[]?.model // empty' "$OLLAMA_TAGS" 2>/dev/null | awk '$0 ~ /(:cloud|-cloud)$/')
command shred -u "$OLLAMA_TAGS" 2>/dev/null || find "$OLLAMA_TAGS" -delete
OLLAMA_LOCAL_ENABLED=false; OLLAMA_CLOUD_ENABLED=false
OLLAMA_LOCAL_MODEL="${OLLAMA_LOCAL_MODELS[0]:-}"
OLLAMA_CLOUD_MODEL="${OLLAMA_CLOUD_MODELS[0]:-}"
[[ "$OLLAMA_AVAILABLE" == true && -n "$OLLAMA_LOCAL_MODEL" ]] && OLLAMA_LOCAL_ENABLED=true
if [[ "$OLLAMA_AVAILABLE" == true && -z "$OLLAMA_LOCAL_MODEL" ]]; then OLLAMA_REASON='daemon reachable but no local model is pulled'; fi
if [[ "$OLLAMA_AVAILABLE" == true && -n "$OLLAMA_CLOUD_MODEL" ]]; then
  echo "Ollama cloud candidate: $OLLAMA_CLOUD_MODEL"
  read -rp 'Type YES only if this Ollama account is restricted to free/included usage with charges disabled: ' answer
  [[ "$answer" == YES ]] && OLLAMA_CLOUD_ENABLED=true
fi
echo "Ollama discovery: $OLLAMA_REASON; local=${#OLLAMA_LOCAL_MODELS[@]}; cloud=${#OLLAMA_CLOUD_MODELS[@]}"

read -rp 'OpenRouter free model/router [openrouter/free]: ' OPENROUTER_MODEL
OPENROUTER_MODEL="${OPENROUTER_MODEL:-openrouter/free}"
[[ "$OPENROUTER_MODEL" == free ]] && OPENROUTER_MODEL=openrouter/free
if [[ "$OPENROUTER_MODEL" != openrouter/free && "$OPENROUTER_MODEL" != *:free ]]; then
  echo 'OpenRouter selection is not a free router or :free model; provider disabled.' >&2
  OPENROUTER_ENABLED=false
fi
if [[ -n "$OLLAMA_LOCAL_MODEL" ]]; then
  read -rp "Ollama local review model [$OLLAMA_LOCAL_MODEL]: " value; OLLAMA_LOCAL_MODEL="${value:-$OLLAMA_LOCAL_MODEL}"
fi
if [[ -n "$OLLAMA_CLOUD_MODEL" ]]; then
  read -rp "Ollama included cloud model [$OLLAMA_CLOUD_MODEL]: " value; OLLAMA_CLOUD_MODEL="${value:-$OLLAMA_CLOUD_MODEL}"
  [[ "$OLLAMA_CLOUD_MODEL" == *:cloud || "$OLLAMA_CLOUD_MODEL" == *-cloud ]] || { echo 'Ollama cloud model must end in :cloud or -cloud; provider disabled.' >&2; OLLAMA_CLOUD_ENABLED=false; }
fi
read -rp 'Gemini free-tier model [gemini-3.1-flash-lite]: ' GEMINI_MODEL
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.1-flash-lite}"
if [[ "$GEMINI_ENABLED" == true ]]; then
  gemini_key="$(<"$SECRETS/gemini.key")"
  if ! curl -fsS --max-time 20 -H "x-goog-api-key: $gemini_key" \
       https://generativelanguage.googleapis.com/v1beta/models | \
       jq -e --arg model "models/$GEMINI_MODEL" '.models[] | select(.name==$model) | .supportedGenerationMethods | index("generateContent")' >/dev/null; then
    echo 'Selected Gemini model is unavailable to this key or cannot generate content; provider disabled.' >&2
    GEMINI_ENABLED=false
  fi
  unset gemini_key
fi
read -rp 'OpenAI paid fallback model (stored disabled) [gpt-5.6-luna]: ' OPENAI_MODEL
OPENAI_MODEL="${OPENAI_MODEL:-gpt-5.6-luna}"

python3 - "$CONFIG" "$MAIN_CONFIG" "$OPENROUTER_ENABLED" "$OLLAMA_LOCAL_ENABLED" "$OLLAMA_CLOUD_ENABLED" "$GEMINI_ENABLED" "$OPENAI_PRESENT" "$OPENROUTER_MODEL" "$OLLAMA_LOCAL_MODEL" "$OLLAMA_CLOUD_MODEL" "$GEMINI_MODEL" "$OPENAI_MODEL" "$OLLAMA_URL" "$OLLAMA_REASON" <<'PY'
import sys,yaml
p,main,re,le,ce,ge,op,rm,lm,cm,gm,om,ollama_url,ollama_reason=sys.argv[1:]
enabled=lambda x:x=="true"
common={"allow_overage":False,"max_output_tokens":2048,"max_cost_microusd_per_call":0}
providers=[
 {"name":"openrouter-free","kind":"openrouter","enabled":enabled(re),"priority":10,"billing_mode":"free",
  "endpoint":"https://openrouter.ai/api/v1","model":rm,"api_key_file":"/etc/solomonprime/secrets/openrouter.key",**common,
  "limits":{"daily_requests":40,"monthly_requests":1000,"monthly_input_tokens":4_000_000,"monthly_output_tokens":1_000_000}},
 {"name":"ollama-local-review","kind":"ollama_local","enabled":enabled(le),"priority":20,"billing_mode":"free",
  "endpoint":ollama_url+"/v1","model":lm,"configured_reason":"ready" if enabled(le) else ollama_reason,**common,
  "limits":{"daily_requests":1000,"monthly_requests":20000,"monthly_input_tokens":50_000_000,"monthly_output_tokens":20_000_000}},
 {"name":"ollama-cloud-free","kind":"ollama_cloud","enabled":enabled(ce),"priority":30,"billing_mode":"free",
  "account_overage_disabled":enabled(ce),"upstream_hard_cap_confirmed":enabled(ce),
  "endpoint":ollama_url+"/v1","model":cm,"configured_reason":"ready" if enabled(ce) else "No pulled :cloud/-cloud model or free-only confirmation missing.",**common,
  "limits":{"daily_requests":10,"monthly_requests":200,"monthly_input_tokens":2_000_000,"monthly_output_tokens":500_000}},
 {"name":"gemini-free","kind":"gemini","enabled":enabled(ge),"priority":40,"billing_mode":"free",
  "upstream_hard_cap_confirmed":enabled(ge),"endpoint":"https://generativelanguage.googleapis.com/v1beta",
  "model":gm,"api_key_file":"/etc/solomonprime/secrets/gemini.key",**common,
  "limits":{"daily_requests":15,"monthly_requests":300,"monthly_input_tokens":2_000_000,"monthly_output_tokens":500_000}},
 {"name":"openai-disabled","kind":"openai","enabled":False,"priority":90,
  "billing_mode":"metered-disabled-by-free-only-policy","endpoint":"https://api.openai.com/v1","model":om,
  "api_key_file":"/etc/solomonprime/secrets/openai.key",**common,"limits":{}},
]
with open(p,"w") as f:yaml.safe_dump({"policy":{"mode":"free_only","local_core_always_first":True,"routing_order":["openrouter-free","ollama-local-review","ollama-cloud-free","gemini-free","openai-disabled"],"high_complexity_consensus":2,"openai_credential_present":enabled(op)},"providers":providers},f,sort_keys=False)
d=yaml.safe_load(open(main)) or {};d["ollama_endpoint"]=ollama_url
with open(main,"w") as f:yaml.safe_dump(d,f,sort_keys=False)
PY
chown root:"$APP_GROUP" "$CONFIG"; chmod 0640 "$CONFIG"
python3 - "$MAIN_CONFIG" <<'PY'
import sys,yaml
p=sys.argv[1];d=yaml.safe_load(open(p)) or {}
d["cloud_complexity_threshold"]=0.78
d["cloud_max_calls_per_request"]=2
open(p,"w").write(yaml.safe_dump(d,sort_keys=False))
PY
chown root:"$APP_GROUP" "$MAIN_CONFIG"; chmod 0640 "$MAIN_CONFIG"

rollback(){
  echo 'Provider configuration failed health validation; restoring prior configuration.' >&2
  if [[ "$CONFIG_EXISTED" == true ]]; then cp -a "$BACKUP" "$CONFIG"; else rm -f "$CONFIG"; fi
  cp -a "$MAIN_BACKUP" "$MAIN_CONFIG"
  systemctl restart solomonprime || true
}
systemctl restart solomonprime
healthy=false
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8765/health >/dev/null 2>&1; then healthy=true; break; fi
  sleep 1
done
if [[ "$healthy" != true ]]; then rollback; journalctl -u solomonprime -n 120 --no-pager; exit 3; fi

echo 'Configured providers (keys are not displayed):'
KEY="$(cat /etc/solomonprime/api.key)"
curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/cloud/status | jq '{policy,complexity_threshold,max_calls_per_request,providers}'
echo 'Installed local models:'
curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/models/local | jq
echo 'Open WebUI model choices refresh automatically from /v1/models.'
