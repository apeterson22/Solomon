#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo"; exit 1; }
CLUSTER_KEY="${SOLOMON_CLUSTER_KEY:-}"
unset SOLOMON_CLUSTER_KEY
if [[ -z "$CLUSTER_KEY" ]]; then
  read -r -s -p 'Controller cluster key (input hidden): ' CLUSTER_KEY
  printf '\n'
fi
[[ "$CLUSTER_KEY" =~ ^[[:xdigit:]]{64}$ ]] || { echo 'Cluster key must be the controller 64-character hexadecimal key.' >&2; exit 2; }
SRC="$(cd "$(dirname "$0")" && pwd)"
APP_USER="${SOLOMON_USER:-${SUDO_USER:-$(logname 2>/dev/null || echo root)}}"
id "$APP_USER" >/dev/null || { echo "User $APP_USER not found"; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3-venv python3-yaml python3-pip curl jq rsync pciutils iproute2 iputils-ping ethtool avahi-daemon avahi-utils openssl
if ! command -v tailscale >/dev/null 2>&1; then curl -fsSL https://tailscale.com/install.sh | sh; fi
systemctl enable --now tailscaled >/dev/null 2>&1 || true
install -d -m 0755 /apps/solomonprime /apps/solomonprime/app /apps/solomonprime/workspace /var/lib/solomonprime /etc/solomonprime
rsync -a --delete --exclude '.venv' --exclude '*.zip' --exclude '*.tar.gz' "$SRC/" /apps/solomonprime/app/
python3 -m venv /apps/solomonprime/.venv
/apps/solomonprime/.venv/bin/pip install -U pip wheel
/apps/solomonprime/.venv/bin/pip install -e /apps/solomonprime/app
printf '%s\n' "$CLUSTER_KEY" >/etc/solomonprime/cluster.key
unset CLUSTER_KEY
[[ -s /etc/solomonprime/api.key ]] || openssl rand -hex 32 >/etc/solomonprime/api.key
chmod 640 /etc/solomonprime/*.key;chown root:"$APP_USER" /etc/solomonprime/*.key
cp /apps/solomonprime/app/config/node.yaml /etc/solomonprime/config.yaml
chown root:"$APP_USER" /etc/solomonprime
chmod 750 /etc/solomonprime
chown root:"$APP_USER" /etc/solomonprime/config.yaml
chmod 640 /etc/solomonprime/config.yaml

# Discover controller candidates. Explicit URLs win; otherwise LAN mDNS, then Tailscale peers.
CANDIDATES="${SOLOMON_CONTROLLER_URLS:-}"
if [[ -z "$CANDIDATES" ]]; then
  CANDIDATES="$(/apps/solomonprime/.venv/bin/python - <<'PY'
import socket,time
from zeroconf import Zeroconf,ServiceBrowser,ServiceListener,IPVersion
TYPE='_solomonprime._tcp.local.';found=[]
class L(ServiceListener):
 def add_service(self,zc,t,n):
  i=zc.get_service_info(t,n,timeout=1000)
  if i:
   for a in i.parsed_addresses():found.append(f'http://{a}:{i.port}')
 def update_service(self,*a):self.add_service(*a)
 def remove_service(self,*a):pass
z=Zeroconf(ip_version=IPVersion.V4Only);b=ServiceBrowser(z,TYPE,L());time.sleep(3);z.close();print(';'.join(dict.fromkeys(found)))
PY
)"
fi
if command -v tailscale >/dev/null 2>&1 && tailscale ip -4 >/dev/null 2>&1; then
  TS_CANDS="$(tailscale status --json 2>/dev/null | jq -r '.Peer // {} | .[] | .TailscaleIPs[]?' | grep -v ':' | awk '{print "http://"$1":8765"}' | paste -sd';' - || true)"
  [[ -n "$TS_CANDS" ]] && CANDIDATES="${CANDIDATES:+$CANDIDATES;}$TS_CANDS"
fi
[[ -n "$CANDIDATES" ]] || { echo "No SolomonPrime controller discovered. Set SOLOMON_CONTROLLER_URLS='http://<local-controller>:8765;http://<tailscale-ip>:8765'"; exit 3; }

# Sort reachable candidates by the local interface used to reach them: direct/small subnet > wired > wifi > tailscale.
SORTED="$(CANDIDATES="$CANDIDATES" /apps/solomonprime/.venv/bin/python - <<'PY'
import os,re,subprocess,urllib.parse
items=[]
for u in dict.fromkeys(x for x in os.environ.get('CANDIDATES','').split(';') if x):
 try:
  host=urllib.parse.urlparse(u).hostname or ''
  r=subprocess.check_output(['ip','route','get',host],text=True,stderr=subprocess.DEVNULL,timeout=2)
  m=re.search(r' dev (\S+)',r);dev=m.group(1) if m else ''
  import ipaddress
  try:is_ts=ipaddress.ip_address(host) in ipaddress.ip_network('100.64.0.0/10')
  except Exception:is_ts=False
  if is_ts or dev.startswith('tailscale'):rank=50
  elif dev.startswith(('wl','wlan')) or os.path.exists(f'/sys/class/net/{dev}/wireless'):rank=70
  else:
   rank=90
  items.append((rank,u))
 except Exception:items.append((0,u))
print(';'.join(u for _,u in sorted(items,reverse=True)))
PY
)"

python3 - "$SORTED" <<'PY'
import sys,yaml,socket
p='/etc/solomonprime/config.yaml';d=yaml.safe_load(open(p));d['node_name']=socket.gethostname();d['controller_candidates']=[x for x in sys.argv[1].split(';') if x];open(p,'w').write(yaml.safe_dump(d,sort_keys=False))
PY
chown -R "$APP_USER:$APP_USER" /apps/solomonprime /var/lib/solomonprime
"$SRC/scripts/install-job-executor.sh" "$APP_USER"
mkdir -p /var/log/solomonprime
chown -R "$APP_USER:$APP_USER" /var/log/solomonprime

cat >/etc/systemd/system/solomonprime.service <<UNIT
[Unit]
Description=SolomonPrime Dynamic Worker Node
After=network-online.target tailscaled.service
Wants=network-online.target
RequiresMountsFor=/apps/solomonprime-jobs
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
systemctl daemon-reload;systemctl enable --now solomonprime

# Optional current worker-node-style scientific/CAD tool set. Drivers are never altered automatically.
if [[ "${SOLOMON_INSTALL_SIM_TOOLS:-0}" == "1" ]]; then
  apt-get install -y openscad blender xvfb libgl1 libglx-mesa0 python3-numpy python3-scipy
  cat >/usr/local/bin/solomon-run-sim <<'SIM'
#!/usr/bin/env bash
set -euo pipefail
export CUDA_DEVICE_ORDER=PCI_BUS_ID
xvfb-run -a "$@"
SIM
  chmod 755 /usr/local/bin/solomon-run-sim
fi

# Never enable UFW. If active, add authenticated mesh reachability through existing local/Tailscale paths.
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  while read -r net dev; do
    [[ -n "$net" && "$dev" != docker* && "$dev" != br-* && "$dev" != veth* && "$dev" != tailscale* ]] || continue
    ufw allow from "$net" to any port 8765 proto tcp comment 'Solomon local mesh' >/dev/null || true
  done < <(ip -4 route show scope link | awk '$1 ~ /^[0-9]+\./ && $0 ~ / dev / {for(i=1;i<=NF;i++)if($i=="dev"){print $1,$(i+1)}}' | sort -u)
  ip link show tailscale0 >/dev/null 2>&1 && ufw allow in on tailscale0 to any port 8765 proto tcp comment 'Solomon Tailscale mesh' >/dev/null || true
fi

for _ in $(seq 1 60); do [[ -s /var/lib/solomonprime/assigned-profile.json ]] && break; sleep 2; done
echo "Node installed. Controller candidates (local-first): $SORTED"
[[ -s /var/lib/solomonprime/assigned-profile.json ]] && cat /var/lib/solomonprime/assigned-profile.json || echo "Waiting for first signed heartbeat/profile assignment."
