#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo: sudo ./upgrade-v0.3.0.sh'; exit 1; }
SRC="$(cd "$(dirname "$0")" && pwd)"
APP_USER="${SOLOMON_USER:-${SUDO_USER:-solomonprime}}"
id "$APP_USER" >/dev/null 2>&1 || { echo "User $APP_USER not found"; exit 2; }
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/apps/solomonprime-data/upgrade-backups/v030-$TS

log(){ printf '\n[SOLOMON-v0.3] %s\n' "$*"; }
fail(){ echo "[SOLOMON-v0.3][ERROR] $*" >&2; exit 3; }

required=(pyproject.toml solomonprime/api.py solomonprime/goals.py solomonprime/experiments.py solomonprime/jobs.py scripts/migrate-state-to-apps.sh scripts/solomon-job-runner.py config/controller.yaml)
for f in "${required[@]}"; do [[ -f "$SRC/$f" ]] || fail "Incomplete v0.3 package: missing $f"; done
python3 -m py_compile "$SRC"/solomonprime/{api,goals,experiments,jobs,registry}.py

grep -q 'version = "0.3.0"' "$SRC/pyproject.toml" || fail 'Package is not v0.3.0'

log '0. Preflight and backup'
[[ -d /apps ]] || fail '/apps is missing'
mkdir -p "$BACKUP"
cp -a /etc/solomonprime "$BACKUP/etc-solomonprime" 2>/dev/null || true
cp -a /etc/systemd/system/solomonprime.service "$BACKUP/solomonprime.service" 2>/dev/null || true
cp -a /etc/systemd/system/solomonprime.service.d "$BACKUP/solomonprime.service.d" 2>/dev/null || true
rsync -a --delete /apps/solomonprime/app/ "$BACKUP/app/" 2>/dev/null || true
curl -fsS http://127.0.0.1:8765/health >"$BACKUP/health.before.json" 2>/dev/null || true

log '1. Move SolomonPrime state/log/audit/experiment persistence from root to /apps'
SOLOMON_ALLOW_SAME_FS="${SOLOMON_ALLOW_SAME_FS:-0}" "$SRC/scripts/migrate-state-to-apps.sh"

log '2. Install v0.3 runtime and preferred-endpoint fix'
systemctl stop solomonprime
rsync -a --delete --exclude '.venv' --exclude '*.zip' --exclude '*.tar.gz' "$SRC/" /apps/solomonprime/app/
/apps/solomonprime/.venv/bin/pip install -e /apps/solomonprime/app

# Merge new v0.3 settings without overwriting site-specific v0.2.x values.
python3 - <<'PY'
import yaml
p='/etc/solomonprime/config.yaml'
d=yaml.safe_load(open(p)) or {}
defs={
 'goals_db':'/var/lib/solomonprime/goals.db',
 'experiments_db':'/var/lib/solomonprime/experiment-ledger.db',
 'experiment_artifact_dir':'/var/lib/solomonprime/experiments',
 'jobs_db':'/var/lib/solomonprime/jobs.db',
 'job_workspace_dir':'/apps/solomonprime-jobs',
 'job_runner':'/usr/local/libexec/solomon-job-runner',
 'job_default_max_runtime':900,
}
for k,v in defs.items(): d.setdefault(k,v)
open(p,'w').write(yaml.safe_dump(d,sort_keys=False))
PY

install -d -o "$APP_USER" -g "$APP_USER" -m 0750 /apps/solomonprime-jobs
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 /var/lib/solomonprime/experiments /var/lib/solomonprime/training /var/log/solomonprime

log '3. Install bounded distributed job runner'
getent group solomonprime >/dev/null || groupadd --system solomonprime
usermod -aG solomonprime "$APP_USER"
if ! id solomonjob >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --gid solomonprime solomonjob
fi
for g in video render; do getent group "$g" >/dev/null && usermod -aG "$g" solomonjob || true; done
install -d -m 0755 /usr/local/libexec
install -o root -g root -m 0755 "$SRC/scripts/solomon-job-runner.py" /usr/local/libexec/solomon-job-runner
cat >"/etc/sudoers.d/solomonprime-job-runner" <<EOF
$APP_USER ALL=(root) NOPASSWD: /usr/local/libexec/solomon-job-runner /apps/solomonprime-jobs/*/manifest.json
EOF
chmod 0440 /etc/sudoers.d/solomonprime-job-runner
visudo -cf /etc/sudoers.d/solomonprime-job-runner >/dev/null

mkdir -p /etc/systemd/system/solomonprime.service.d
cat >/etc/systemd/system/solomonprime.service.d/v030.conf <<'EOF'
[Unit]
RequiresMountsFor=/var/lib/solomonprime /var/log/solomonprime /apps/solomonprime-jobs

[Service]
SupplementaryGroups=solomonprime
ReadWritePaths=
ReadWritePaths=/apps/solomonprime /apps/solomonprime-jobs /var/lib/solomonprime /var/log/solomonprime
EOF

chown -R "$APP_USER:$APP_USER" /var/lib/solomonprime /var/log/solomonprime
# The sandbox account must be able to traverse the shared job root. Keep the
# service user as owner, but use the solomonprime group for controller + worker.
chown "$APP_USER:solomonprime" /apps/solomonprime-jobs
chmod 0770 /apps/solomonprime-jobs
chown root:"$APP_USER" /etc/solomonprime/config.yaml
chmod 0640 /etc/solomonprime/config.yaml

systemctl daemon-reload
systemctl restart solomonprime

log '4. Health and API verification'
ok=0
for _ in $(seq 1 90); do
  v=$(curl -fsS http://127.0.0.1:8765/health 2>/dev/null | jq -r '.version // empty' || true)
  [[ "$v" == '0.3.0' ]] && { ok=1; break; }
  sleep 1
done
if [[ $ok -ne 1 ]]; then
  journalctl -u solomonprime -n 120 --no-pager
  fail 'SolomonPrime v0.3 failed health check. Backup is under /apps and no state data was discarded.'
fi
KEY=$(cat /etc/solomonprime/api.key)
curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/goals >/dev/null
curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/experiments >/dev/null
curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/jobs >/dev/null

# Verify the registry now persists a preferred endpoint on the controller.
for _ in $(seq 1 10); do
  pref=$(curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/nodes | jq -r --arg h "$(hostname)" '.nodes[] | select(.name==$h) | .preferred_endpoint // empty')
  [[ -n "$pref" ]] && break
  sleep 2
done
[[ -n "${pref:-}" ]] || fail 'preferred_endpoint is still empty after v0.3 startup'

log '5. Local sandbox runner smoke test'
SMOKE=/apps/solomonprime-jobs/JOB-SMOKE-$TS
mkdir -p "$SMOKE"
cat >"$SMOKE/main.py" <<'PY'
from pathlib import Path
Path('smoke-output.txt').write_text('SolomonPrime v0.3 sandbox OK\n')
print('sandbox-ok')
PY
cat >"$SMOKE/manifest.json" <<EOF
{
  "job_id":"JOB-SMOKE-$TS",
  "workspace":"$SMOKE",
  "kind":"python",
  "risk":"reversible",
  "source_file":"main.py",
  "resources":{"max_runtime_seconds":30,"max_memory_gb":1,"max_cpu_cores":1,"max_disk_gb":1},
  "allow_network":false
}
EOF
chown -R "$APP_USER:solomonprime" "$SMOKE"
chmod 0770 "$SMOKE"
sudo -u "$APP_USER" sudo -n /usr/local/libexec/solomon-job-runner "$SMOKE/manifest.json" >/tmp/solomon-v030-smoke.out 2>/tmp/solomon-v030-smoke.err || { cat /tmp/solomon-v030-smoke.err; fail 'sandbox runner smoke test failed'; }
[[ -s "$SMOKE/result.json" && -s "$SMOKE/smoke-output.txt" ]] || fail 'sandbox runner did not produce expected artifacts'
rm -rf "$SMOKE" /tmp/solomon-v030-smoke.out /tmp/solomon-v030-smoke.err

log 'UPGRADE COMPLETE'
echo "Backup: $BACKUP"
echo "Version: $(curl -s http://127.0.0.1:8765/health | jq -r .version)"
echo "Preferred endpoint: $pref"
echo 'State/log physical storage:'
findmnt /var/lib/solomonprime /var/log/solomonprime || true
echo 'Next: upgrade worker-node with upgrade-node-v0.3.0.sh before dispatching distributed jobs.'
