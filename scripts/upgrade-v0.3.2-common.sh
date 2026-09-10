#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run this upgrade with sudo' >&2; exit 1; }

EXPECTED_ROLE="${1:?usage: upgrade-v0.3.2-common.sh controller|node}"
[[ "$EXPECTED_ROLE" == controller || "$EXPECTED_ROLE" == node ]] || { echo 'Invalid expected role' >&2; exit 2; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${SOLOMON_USER:-$(systemctl show solomonprime -p User --value 2>/dev/null || true)}"
APP_USER="${APP_USER:-${SUDO_USER:-}}"
id "$APP_USER" >/dev/null 2>&1 || { echo "SolomonPrime service user not found: $APP_USER" >&2; exit 2; }
APP_GROUP="$(id -gn "$APP_USER")"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT=/apps/solomonprime/upgrade-backups
[[ "$EXPECTED_ROLE" == controller && -d /apps/solomonprime-data ]] && BACKUP_ROOT=/apps/solomonprime-data/upgrade-backups
BACKUP="$BACKUP_ROOT/v032-$EXPECTED_ROLE-$TS"
ABSENT="$BACKUP/absent-paths.txt"
SUCCESS=0

log(){ printf '\n[SOLOMON-v0.3.2-%s] %s\n' "$EXPECTED_ROLE" "$*"; }
fail(){ echo "[SOLOMON-v0.3.2-$EXPECTED_ROLE][ERROR] $*" >&2; return 1; }

backup_path(){
  local path="$1" destination="$BACKUP/files$1"
  if [[ -e "$path" || -L "$path" ]]; then
    mkdir -p "$(dirname "$destination")"
    cp -a "$path" "$destination"
  else
    printf '%s\n' "$path" >>"$ABSENT"
  fi
}

restore_path(){
  local path="$1" source="$BACKUP/files$1"
  if [[ -e "$source" || -L "$source" ]]; then
    mkdir -p "$(dirname "$path")"
    rm -f "$path"
    cp -a "$source" "$path"
  fi
}

rollback(){
  local code=$?
  [[ $SUCCESS -eq 1 ]] && return
  trap - ERR
  set +e
  echo "[SOLOMON-v0.3.2-$EXPECTED_ROLE] Upgrade failed; restoring $BACKUP" >&2
  systemctl stop solomonprime >/dev/null 2>&1
  systemctl disable --now solomon-job-broker.socket >/dev/null 2>&1
  [[ -d "$BACKUP/app" ]] && rsync -a --delete --exclude '.venv' "$BACKUP/app/" /apps/solomonprime/app/
  while IFS= read -r path; do [[ -n "$path" ]] && rm -f "$path"; done <"$ABSENT"
  while IFS= read -r path; do restore_path "$path"; done <"$BACKUP/tracked-paths.txt"
  /apps/solomonprime/.venv/bin/pip install -e /apps/solomonprime/app >/dev/null 2>&1
  systemctl daemon-reload
  if [[ -f "$BACKUP/broker-socket.enabled" ]] && grep -qx enabled "$BACKUP/broker-socket.enabled"; then
    systemctl enable --now solomon-job-broker.socket >/dev/null 2>&1
  fi
  systemctl restart solomonprime
  echo "[SOLOMON-v0.3.2-$EXPECTED_ROLE] Rollback complete; inspect $BACKUP" >&2
  exit "$code"
}
trap rollback ERR

required=(
  pyproject.toml solomonprime/api.py solomonprime/jobs.py solomonprime/scheduler.py
  scripts/solomon-job-runner.py scripts/solomon-job-broker.py
  scripts/solomon-job-broker-client.py scripts/install-job-broker.sh
  scripts/seed-improvement-plan.sh
  systemd/solomon-job-broker.socket systemd/solomon-job-broker@.service
  systemd/solomon-job-broker.tmpfiles
  docs/SOLOMONPRIME_TED_IMPROVEMENT_PLAN.md
  docs/IMPROVEMENT_MEMORY_OBSIDIAN_READINESS.md
)
for file in "${required[@]}"; do [[ -f "$SRC/$file" ]] || fail "Incomplete package: missing $file"; done
grep -q 'version = "0.3.2"' "$SRC/pyproject.toml" || fail 'Package is not v0.3.2'
python3 -m py_compile "$SRC"/solomonprime/{api,jobs,scheduler,registry}.py "$SRC"/scripts/solomon-job-{runner,broker,broker-client}.py

ROLE="$(python3 - <<'PY'
import yaml
print((yaml.safe_load(open('/etc/solomonprime/config.yaml')) or {}).get('role','node'))
PY
)"
[[ "$ROLE" == "$EXPECTED_ROLE" ]] || fail "This host is role=$ROLE, not $EXPECTED_ROLE"

log '0. Preflight and rollback checkpoint'
mkdir -p "$BACKUP"
: >"$ABSENT"
tracked=(
  /etc/solomonprime/config.yaml
  /etc/solomonprime/job-broker.env
  /etc/systemd/system/solomonprime.service.d/v032.conf
  /etc/systemd/system/solomon-job-broker.socket
  /etc/systemd/system/solomon-job-broker@.service
  /etc/tmpfiles.d/solomon-job-broker.conf
  /usr/local/libexec/solomon-job-runner
  /usr/local/libexec/solomon-job-broker
  /usr/local/libexec/solomon-job-broker-client
  /etc/sudoers.d/solomonprime-job-runner
  /etc/sudoers.d/solomon-job-runner
)
printf '%s\n' "${tracked[@]}" >"$BACKUP/tracked-paths.txt"
for path in "${tracked[@]}"; do backup_path "$path"; done
rsync -a --delete --exclude '.venv' /apps/solomonprime/app/ "$BACKUP/app/"
curl -fsS http://127.0.0.1:8765/health >"$BACKUP/health.before.json" || true
systemctl is-enabled solomon-job-broker.socket >"$BACKUP/broker-socket.enabled" 2>/dev/null || printf 'disabled\n' >"$BACKUP/broker-socket.enabled"

log '1. Install v0.3.2 runtime'
systemctl stop solomonprime
rsync -a --delete --exclude '.venv' --exclude '*.zip' --exclude '*.tar.gz' "$SRC/" /apps/solomonprime/app/
/apps/solomonprime/.venv/bin/pip install -e /apps/solomonprime/app
python3 - <<'PY'
import yaml
p='/etc/solomonprime/config.yaml';d=yaml.safe_load(open(p)) or {}
d['job_runner']='/usr/local/libexec/solomon-job-broker-client'
d['job_broker_socket']='/run/solomonprime/job-broker.sock'
d.setdefault('job_workspace_dir','/apps/solomonprime-jobs')
d.setdefault('job_default_max_runtime',900)
open(p,'w').write(yaml.safe_dump(d,sort_keys=False))
PY

log '2. Install protected root broker and unprivileged client'
"$SRC/scripts/install-job-broker.sh" "$APP_USER"
chown root:"$APP_GROUP" /etc/solomonprime/config.yaml
chmod 0640 /etc/solomonprime/config.yaml
systemctl restart solomonprime

log '3. Verify service hardening, health, socket, and API'
for _ in $(seq 1 90); do
  version="$(curl -fsS http://127.0.0.1:8765/health 2>/dev/null | jq -r '.version // empty' || true)"
  [[ "$version" == 0.3.2 ]] && break
  sleep 1
done
[[ "${version:-}" == 0.3.2 ]] || { journalctl -u solomonprime -n 120 --no-pager; fail 'v0.3.2 health check failed'; }
[[ "$(systemctl show solomonprime -p NoNewPrivileges --value)" == yes ]] || fail 'NoNewPrivileges is not enabled'
[[ -S /run/solomonprime/job-broker.sock ]] || fail 'broker socket is unavailable'
[[ "$(stat -c '%a %U %G' /run/solomonprime/job-broker.sock)" == '660 root solomonprime' ]] || fail 'broker socket permissions are incorrect'
if [[ "$EXPECTED_ROLE" == controller ]]; then
  KEY="$(cat /etc/solomonprime/api.key)"
  curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/goals >/dev/null
  curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/experiments >/dev/null
  curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/jobs >/dev/null
  curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/improvement/status | jq -e '.plan.present==true and .rag.state=="partial" and .obsidian.state=="not_implemented"' >/dev/null
  curl -fsS http://127.0.0.1:8765/openapi.json | jq -e '.components.schemas.JobSubmitRequest and .components.schemas.JobResources' >/dev/null
  "$SRC/scripts/seed-improvement-plan.sh"
fi

log '4. Execute broker smoke test from a NoNewPrivileges client'
SMOKE="/apps/solomonprime-jobs/JOB-BROKER-SMOKE-$TS"
install -d -o "$APP_USER" -g solomonprime -m 0770 "$SMOKE"
install -o "$APP_USER" -g solomonprime -m 0640 /dev/stdin "$SMOKE/main.py" <<'PY'
from pathlib import Path
Path('broker-smoke-output.txt').write_text('NoNewPrivileges broker path OK\n')
print('broker-smoke-ok')
PY
SOURCE_SHA="$(sha256sum "$SMOKE/main.py" | awk '{print $1}')"
install -o "$APP_USER" -g solomonprime -m 0640 /dev/stdin "$SMOKE/manifest.json" <<EOF
{"job_id":"JOB-BROKER-SMOKE-$TS","workspace":"$SMOKE","kind":"python","risk":"reversible","source_file":"main.py","source_sha256":"$SOURCE_SHA","resources":{"max_runtime_seconds":30,"max_memory_gb":1,"max_cpu_cores":1,"max_disk_gb":1},"allow_network":false}
EOF
systemd-run --wait --collect --pipe --quiet \
  --unit="solomon-broker-smoke-$TS" \
  --uid="$APP_USER" --gid="$APP_GROUP" \
  --property=SupplementaryGroups=solomonprime \
  --property=NoNewPrivileges=yes \
  /usr/local/libexec/solomon-job-broker-client "$SMOKE/manifest.json"
jq -e '.exit_code==0 and .metrics.network_enabled==false' "$SMOKE/result.json" >/dev/null
[[ -s "$SMOKE/broker-smoke-output.txt" ]] || fail 'broker smoke artifact is missing'
rm -rf "$SMOKE"

log '5. Retire obsolete sudo privilege path'
rm -f /etc/sudoers.d/solomonprime-job-runner /etc/sudoers.d/solomon-job-runner
systemctl restart solomonprime
[[ "$(systemctl show solomonprime -p NoNewPrivileges --value)" == yes ]] || fail 'service hardening changed after restart'
final_version=""
for _ in $(seq 1 90); do
  final_version="$(curl -fsS http://127.0.0.1:8765/health 2>/dev/null | jq -r '.version // empty' || true)"
  [[ "$final_version" == 0.3.2 ]] && break
  sleep 1
done
if [[ "$final_version" != 0.3.2 ]]; then
  journalctl -u solomonprime -n 120 --no-pager
  fail 'final v0.3.2 health check failed after 90 seconds'
fi

SUCCESS=1
trap - ERR
log 'UPGRADE COMPLETE'
echo "Backup: $BACKUP"
echo "Version: $(curl -fsS http://127.0.0.1:8765/health | jq -r .version)"
echo "NoNewPrivileges: $(systemctl show solomonprime -p NoNewPrivileges --value)"
echo "Broker socket: $(stat -c '%a %U:%G %n' /run/solomonprime/job-broker.sock)"
