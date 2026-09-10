#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
SRC="$(cd "$(dirname "$0")" && pwd)"
APP_USER="${SOLOMON_USER:-${SUDO_USER:-$(logname 2>/dev/null || echo root)}}"
id "$APP_USER" >/dev/null || { echo "User $APP_USER not found"; exit 2; }
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/apps/solomonprime/upgrade-backups/v030-node-$TS
log(){ printf '\n[SOLOMON-NODE-v0.3] %s\n' "$*"; }

for f in pyproject.toml solomonprime/api.py solomonprime/jobs.py scripts/solomon-job-runner.py; do [[ -f "$SRC/$f" ]] || { echo "Missing $f"; exit 3; }; done
python3 -m py_compile "$SRC"/solomonprime/{api,jobs,registry}.py
mkdir -p "$BACKUP"
rsync -a /apps/solomonprime/app/ "$BACKUP/app/" 2>/dev/null || true
cp -a /etc/solomonprime "$BACKUP/etc-solomonprime" 2>/dev/null || true

log 'Install v0.3 worker runtime'
systemctl stop solomonprime
rsync -a --delete --exclude '.venv' --exclude '*.zip' "$SRC/" /apps/solomonprime/app/
/apps/solomonprime/.venv/bin/pip install -e /apps/solomonprime/app
python3 - <<'PY'
import yaml
p='/etc/solomonprime/config.yaml';d=yaml.safe_load(open(p)) or {}
for k,v in {
 'goals_db':'/var/lib/solomonprime/goals.db','experiments_db':'/var/lib/solomonprime/experiment-ledger.db',
 'experiment_artifact_dir':'/var/lib/solomonprime/experiments','jobs_db':'/var/lib/solomonprime/jobs.db',
 'job_workspace_dir':'/apps/solomonprime-jobs','job_runner':'/usr/local/libexec/solomon-job-runner','job_default_max_runtime':900,
}.items(): d.setdefault(k,v)
open(p,'w').write(yaml.safe_dump(d,sort_keys=False))
PY

log 'Install bounded worker sandbox'
getent group solomonprime >/dev/null || groupadd --system solomonprime
usermod -aG solomonprime "$APP_USER"
if ! id solomonjob >/dev/null 2>&1; then useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --gid solomonprime solomonjob; fi
for g in video render; do getent group "$g" >/dev/null && usermod -aG "$g" solomonjob || true; done
install -d -o "$APP_USER" -g solomonprime -m 0770 /apps/solomonprime-jobs
install -d -m 0755 /usr/local/libexec
install -o root -g root -m 0755 "$SRC/scripts/solomon-job-runner.py" /usr/local/libexec/solomon-job-runner
cat >/etc/sudoers.d/solomonprime-job-runner <<EOF
$APP_USER ALL=(root) NOPASSWD: /usr/local/libexec/solomon-job-runner /apps/solomonprime-jobs/*/manifest.json
EOF
chmod 0440 /etc/sudoers.d/solomonprime-job-runner
visudo -cf /etc/sudoers.d/solomonprime-job-runner >/dev/null

mkdir -p /etc/systemd/system/solomonprime.service.d
cat >/etc/systemd/system/solomonprime.service.d/v030.conf <<'EOF'
[Unit]
RequiresMountsFor=/apps/solomonprime-jobs
[Service]
SupplementaryGroups=solomonprime
ReadWritePaths=
ReadWritePaths=/apps/solomonprime /apps/solomonprime-jobs /var/lib/solomonprime /var/log/solomonprime
EOF
mkdir -p /var/log/solomonprime
chown -R "$APP_USER:$APP_USER" /var/lib/solomonprime /var/log/solomonprime
systemctl daemon-reload
systemctl restart solomonprime

for _ in $(seq 1 60); do [[ "$(curl -fsS http://127.0.0.1:8765/health 2>/dev/null | jq -r '.version // empty' || true)" == '0.3.0' ]] && break; sleep 1; done
[[ "$(curl -fsS http://127.0.0.1:8765/health | jq -r .version)" == '0.3.0' ]] || { journalctl -u solomonprime -n 100 --no-pager; exit 4; }
log 'NODE UPGRADE COMPLETE'
echo "Backup: $BACKUP"
echo 'The worker will advertise v0.3 capabilities on its next signed heartbeat.'
