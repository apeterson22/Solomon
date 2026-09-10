#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo ./install-controller.sh"; exit 1; }
SRC="$(cd "$(dirname "$0")" && pwd)"
APP_USER="${SOLOMON_USER:-${SUDO_USER:-solomonprime}}"
if ! id "$APP_USER" >/dev/null 2>&1; then
  [[ "$APP_USER" == "solomonprime" ]] || { echo "User $APP_USER not found"; exit 1; }
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/solomonprime-$TS"
export DEBIAN_FRONTEND=noninteractive

log(){ printf '\n[SOLOMON] %s\n' "$*"; }
warn(){ printf '\n[SOLOMON][WARN] %s\n' "$*" >&2; }

log "0. Preflight and access protection"
mkdir -p "$BACKUP"
cp -a /etc/solomonprime "$BACKUP/" 2>/dev/null || true
systemctl enable --now ssh >/dev/null 2>&1 || true
ss -ltn | grep -qE '(:|\])22[[:space:]]' || { echo "SSH is not listening; refusing deployment"; exit 2; }

apt-get update -y
apt-get install -y python3-venv python3-yaml python3-pip curl jq rsync pciutils iproute2 iputils-ping ethtool smartmontools sqlite3 avahi-daemon avahi-utils openssl tmux
if ! command -v docker >/dev/null 2>&1; then apt-get install -y docker.io; systemctl enable --now docker; fi
if ! command -v tailscale >/dev/null 2>&1; then curl -fsSL https://tailscale.com/install.sh | sh; fi
systemctl enable --now tailscaled >/dev/null 2>&1 || true

# If UFW is already active, protect current SSH before touching anything else. Never enable UFW here.
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow OpenSSH >/dev/null || true
  ip link show tailscale0 >/dev/null 2>&1 && ufw allow in on tailscale0 to any port 22 proto tcp >/dev/null || true
  while read -r net dev; do
    [[ -n "$net" && "$dev" != docker* && "$dev" != br-* && "$dev" != veth* && "$dev" != tailscale* ]] || continue
    ufw allow from "$net" to any port 22 proto tcp >/dev/null || true
  done < <(ip -4 route show scope link | awk '$1 ~ /^[0-9]+\./ && $0 ~ / dev / {for(i=1;i<=NF;i++)if($i=="dev"){print $1,$(i+1)}}' | sort -u)
fi

log "1. Discover existing inference without changing it"
if pgrep -x llama-server >/dev/null 2>&1; then
  log "Existing llama.cpp service detected and preserved."
elif [[ "${SOLOMON_CONFIGURE_LLAMA:-NO}" == "YES" ]]; then
  SOLOMON_USER="$APP_USER" "$SRC/scripts/configure-llama.sh"
else
  warn "No existing llama.cpp service detected. Local inference can be added later with the pinned Ollama installer or configure-llama.sh."
fi

log "2. Install SolomonPrime clean-room runtime"
install -d -m 0755 /apps/solomonprime /apps/solomonprime/app /apps/solomonprime/workspace /var/lib/solomonprime /etc/solomonprime /var/log/solomonprime
rsync -a --delete --exclude '.venv' --exclude '*.zip' --exclude '*.tar.gz' "$SRC/" /apps/solomonprime/app/
python3 -m venv /apps/solomonprime/.venv
/apps/solomonprime/.venv/bin/pip install -U pip wheel
/apps/solomonprime/.venv/bin/pip install -e /apps/solomonprime/app

if [[ ! -s /etc/solomonprime/cluster.key ]]; then openssl rand -hex 32 >/etc/solomonprime/cluster.key; fi
if [[ ! -s /etc/solomonprime/api.key ]]; then openssl rand -hex 32 >/etc/solomonprime/api.key; fi
chmod 600 /etc/solomonprime/*.key
cp /apps/solomonprime/app/config/controller.yaml /etc/solomonprime/config.yaml

# Dynamically record connected local networks. This is informational/policy data; firewall remains operator-controlled.
LOCAL_NETS="$(ip -4 route show scope link | awk '$1 ~ /^[0-9]+\./ && $0 ~ / dev / && $0 !~ /docker|virbr|br-|veth|tailscale/ {print $1}' | sort -u | paste -sd, -)"
python3 - "$LOCAL_NETS" <<'PY'
import sys,yaml,socket
p='/etc/solomonprime/config.yaml';d=yaml.safe_load(open(p))
d['node_name']=socket.gethostname()
nets=[x for x in sys.argv[1].split(',') if x]
if nets:d['local_subnets']=nets
open(p,'w').write(yaml.safe_dump(d,sort_keys=False))
PY
chown -R "$APP_USER:$APP_USER" /apps/solomonprime /var/lib/solomonprime /var/log/solomonprime

# Keep growing state/log/audit/experiment data off the small root filesystem and install the bounded job sandbox.
"$SRC/scripts/migrate-state-to-apps.sh"
"$SRC/scripts/install-job-executor.sh" "$APP_USER"

chown root:"$APP_USER" /etc/solomonprime
chmod 750 /etc/solomonprime
chown root:"$APP_USER" /etc/solomonprime/config.yaml /etc/solomonprime/api.key /etc/solomonprime/cluster.key
chmod 640 /etc/solomonprime/config.yaml /etc/solomonprime/api.key /etc/solomonprime/cluster.key

cat >/etc/systemd/system/solomonprime.service <<UNIT
[Unit]
Description=SolomonPrime Local-First Home/Farm AI Controller
After=network-online.target tailscaled.service docker.service
Wants=network-online.target
RequiresMountsFor=/var/lib/solomonprime /var/log/solomonprime /apps/solomonprime-jobs
StartLimitIntervalSec=300
StartLimitBurst=8

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
SupplementaryGroups=solomonprime
Environment=SOLOMON_CONFIG=/etc/solomonprime/config.yaml
WorkingDirectory=/apps/solomonprime
ExecStart=/apps/solomonprime/.venv/bin/solomonprime
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ReadWritePaths=/apps/solomonprime /apps/solomonprime-jobs /var/lib/solomonprime /var/log/solomonprime
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
UNIT

# Cloud providers are opt-in. Install a zero-overage template without enabling any provider.
install -d -m 700 /etc/solomonprime/secrets
if [ ! -f /etc/solomonprime/cloud-providers.yaml ]; then
  install -m 600 "$SRC/config/cloud-providers.yaml.example" /etc/solomonprime/cloud-providers.yaml
fi
install -d -o "$APP_USER" -g "$APP_USER" /var/lib/solomonprime/training 2>/dev/null || true

systemctl daemon-reload
systemctl enable solomonprime.service
systemctl restart solomonprime.service

API_KEY="$(cat /etc/solomonprime/api.key)"
ok=0
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8765/health >/dev/null 2>&1 && curl -fsS -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8765/v1/models >/dev/null 2>&1; then ok=1;break;fi
  sleep 1
done
if [[ $ok -ne 1 ]]; then journalctl -u solomonprime -n 120 --no-pager; exit 4; fi

ln -sfn /apps/solomonprime/.venv/bin/solomonctl /usr/local/bin/solomonctl
cat >/usr/local/bin/solomon-chat <<'CHAT'
#!/usr/bin/env bash
set -euo pipefail
MODEL="${SOLOMON_MODEL:-solomonprime}"
KEY="$(sudo cat /etc/solomonprime/api.key 2>/dev/null || cat /etc/solomonprime/api.key)"
PROMPT="${*:-}"
if [[ -z "$PROMPT" ]]; then read -r -p 'SolomonPrime> ' PROMPT; fi
jq -n --arg m "$MODEL" --arg p "$PROMPT" '{model:$m,stream:false,messages:[{role:"user",content:$p}]}' | curl -fsS -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:8765/v1/chat/completions | jq -r '.choices[0].message.content // .error // .'
CHAT
chmod 755 /usr/local/bin/solomon-chat
cat >/usr/local/bin/solomon-status <<'STATUS'
#!/usr/bin/env bash
set -u
KEY="$(sudo cat /etc/solomonprime/api.key 2>/dev/null || cat /etc/solomonprime/api.key)"
echo '=== SolomonPrime ==='; curl -s http://127.0.0.1:8765/health | jq . || true
echo '=== Nodes ==='; curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/nodes | jq '.nodes[] | {name,node_id,role,trust,health,capabilities,endpoints}' || true
echo '=== Memory ==='; curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/memory/stats | jq . || true
echo '=== Cloud Router ==='; curl -s -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/cloud/status | jq . || true
echo '=== llama.cpp ==='; pgrep -a llama-server || true
echo '=== WebUI ==='; docker ps --filter name=open-webui || true
STATUS
chmod 755 /usr/local/bin/solomon-status
ln -sfn /apps/solomonprime/app/scripts/model-lab.sh /usr/local/bin/solomon-model-lab

log "3. Seed durable architectural memory"
remember(){
  local text="$1" domain="$2" importance="$3"
  jq -n --arg c "$text" --arg d "$domain" --argjson i "$importance" '{content:$c,tier:"semantic",agent:"solomon-core",domain:$d,source:"bootstrap",importance:$i,confidence:1.0,tags:"bootstrap"}' | \
    curl -fsS -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:8765/v1/memory/remember >/dev/null
}
remember "SolomonPrime network policy: same-host loopback first; dedicated/direct Ethernet next; wired local LAN next; local Wi-Fi next; Tailscale is encrypted remote/fallback connectivity. Local links remain authenticated and are not implicitly trusted." infrastructure 1.0
remember "First SolomonPrime project: perform a non-destructive inventory of all storage, calculate exact duplicates with cryptographic hashes, propose an optimal hot/bulk/archive layout, and require approval before important moves or deletion." storage 1.0
remember "Memory strategy: minimize active context, maintain tiered working/episodic/semantic/domain/archive memory, deduplicate near-equivalent records, score retrieval by relevance/importance/confidence/recency/reuse, preserve provenance and contradictions, and benchmark memory effectiveness." memory 1.0

log "4. Configure Open WebUI as the SolomonPrime front end"
"$SRC/scripts/configure-openwebui.sh"

log "5. Local-first firewall allowances if UFW is already active"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  while read -r net dev; do
    [[ -n "$net" && "$dev" != docker* && "$dev" != br-* && "$dev" != veth* && "$dev" != tailscale* ]] || continue
    ufw allow from "$net" to any port 22 proto tcp comment 'Solomon local SSH' >/dev/null || true
    ufw allow from "$net" to any port 3000 proto tcp comment 'Solomon local WebUI' >/dev/null || true
    ufw allow from "$net" to any port 8765 proto tcp comment 'Solomon local API' >/dev/null || true
  done < <(ip -4 route show scope link | awk '$1 ~ /^[0-9]+\./ && $0 ~ / dev / {for(i=1;i<=NF;i++)if($i=="dev"){print $1,$(i+1)}}' | sort -u)
  ip link show tailscale0 >/dev/null 2>&1 && {
    ufw allow in on tailscale0 to any port 22 proto tcp comment 'Solomon Tailscale SSH' >/dev/null || true
    ufw allow in on tailscale0 to any port 3000 proto tcp comment 'Solomon Tailscale WebUI' >/dev/null || true
    ufw allow in on tailscale0 to any port 8765 proto tcp comment 'Solomon Tailscale API' >/dev/null || true
  }
  DOCKER_NET="$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Subnet}}' 2>/dev/null || true)"
  [[ -n "$DOCKER_NET" ]] && ufw allow from "$DOCKER_NET" to any port 8765 proto tcp comment 'OpenWebUI to Solomon' >/dev/null || true
fi

log "6. Initial read-only hardware/storage layout snapshot"
curl -fsS -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8765/v1/storage/layout > /var/lib/solomonprime/initial-storage-layout.json || true
curl -fsS -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8765/v1/nodes > /var/lib/solomonprime/initial-nodes.json || true
chown "$APP_USER:$APP_USER" /var/lib/solomonprime/initial-*.json 2>/dev/null || true

log "INSTALL COMPLETE"
echo "Backup of prior config: $BACKUP"
echo "WebUI local addresses:"
ip -o -4 addr show scope global | awk '$2 !~ /docker|virbr|br-|veth|tailscale/ {split($4,a,"/"); print "  http://" a[1] ":3000"}'
if tailscale ip -4 >/dev/null 2>&1; then
  echo "Tailscale IP: $(tailscale ip -4)"
  tailscale serve status 2>/dev/null || true
else
  warn "Tailscale is installed but not authenticated. Run: sudo tailscale up"
fi
echo "Solomon API: http://127.0.0.1:8765/v1"
echo "CLI: solomon-chat 'your request'"
echo "Status: solomon-status"
echo "Model lab (safe benchmark, no auto-promotion): sudo solomon-model-lab bench"
echo "First storage audit example:"
echo "  KEY=\$(sudo cat /etc/solomonprime/api.key)"
echo "  curl -s -H \"Authorization: Bearer \$KEY\" -H 'Content-Type: application/json' -d '{\"roots\":[\"/apps\",\"/home\"],\"max_files\":100000}' http://127.0.0.1:8765/v1/storage/scan | jq"
echo "UFW state was preserved; this installer never enables it."
