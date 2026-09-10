#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo: sudo ./repair-v0.3.0-sandbox.sh'; exit 1; }
APP_USER="${SOLOMON_USER:-${SUDO_USER:-solomonprime}}"
id "$APP_USER" >/dev/null 2>&1 || { echo "User $APP_USER not found"; exit 2; }
TS=$(date -u +%Y%m%dT%H%M%SZ)
log(){ printf '\n[SOLOMON-v0.3-REPAIR] %s\n' "$*"; }
fail(){ echo "[SOLOMON-v0.3-REPAIR][ERROR] $*" >&2; exit 3; }

log '1. Verify the v0.3 controller is already healthy'
health=$(curl -fsS http://127.0.0.1:8765/health 2>/dev/null || true)
ver=$(jq -r '.version // empty' <<<"$health" 2>/dev/null || true)
[[ "$ver" == "0.3.0" ]] || fail "Expected running SolomonPrime v0.3.0, got: ${health:-no health response}"

log '2. Repair sandbox job-root ownership and restricted sudo path'
getent group solomonprime >/dev/null || groupadd --system solomonprime
usermod -aG solomonprime "$APP_USER"
if ! id solomonjob >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --gid solomonprime solomonjob
fi
# Keep job root writable by the controller and traversable by the sandbox user.
install -d -o "$APP_USER" -g solomonprime -m 0770 /apps/solomonprime-jobs
chown "$APP_USER:solomonprime" /apps/solomonprime-jobs
chmod 0770 /apps/solomonprime-jobs

[[ -x /usr/local/libexec/solomon-job-runner ]] || fail '/usr/local/libexec/solomon-job-runner is missing'
cat >/etc/sudoers.d/solomonprime-job-runner <<SUDOEOF
$APP_USER ALL=(root) NOPASSWD: /usr/local/libexec/solomon-job-runner /apps/solomonprime-jobs/*/manifest.json
SUDOEOF
chmod 0440 /etc/sudoers.d/solomonprime-job-runner
visudo -cf /etc/sudoers.d/solomonprime-job-runner >/dev/null || fail 'sudoers validation failed'

log '3. Restart controller so supplementary group membership is definitely active'
systemctl restart solomonprime
for _ in $(seq 1 90); do
  [[ "$(curl -fsS http://127.0.0.1:8765/health 2>/dev/null | jq -r '.version // empty' || true)" == '0.3.0' ]] && break
  sleep 1
done
[[ "$(curl -fsS http://127.0.0.1:8765/health | jq -r .version)" == '0.3.0' ]] || { journalctl -u solomonprime -n 100 --no-pager; fail 'controller did not recover'; }

log '4. Run a verbose local sandbox smoke test'
SMOKE=/apps/solomonprime-jobs/JOB-SMOKE-REPAIR-$TS
mkdir -p "$SMOKE"
cat >"$SMOKE/main.py" <<'PY'
from pathlib import Path
Path('smoke-output.txt').write_text('SolomonPrime v0.3 sandbox OK\n')
print('sandbox-ok')
PY
cat >"$SMOKE/manifest.json" <<JSONEOF
{
  "job_id":"JOB-SMOKE-REPAIR-$TS",
  "workspace":"$SMOKE",
  "kind":"python",
  "risk":"reversible",
  "source_file":"main.py",
  "resources":{"max_runtime_seconds":30,"max_memory_gb":1,"max_cpu_cores":1,"max_disk_gb":1},
  "allow_network":false
}
JSONEOF
chown -R "$APP_USER:solomonprime" "$SMOKE"
chmod 0770 "$SMOKE"

set +e
sudo -u "$APP_USER" sudo -n /usr/local/libexec/solomon-job-runner "$SMOKE/manifest.json" >"/tmp/solomon-v030-repair-smoke.out" 2>"/tmp/solomon-v030-repair-smoke.err"
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  echo '--- stdout ---'
  cat /tmp/solomon-v030-repair-smoke.out || true
  echo '--- stderr ---' >&2
  cat /tmp/solomon-v030-repair-smoke.err >&2 || true
  echo '--- recent transient-unit/systemd errors ---' >&2
  journalctl -n 120 --no-pager | grep -Ei 'solomon-job|CHDIR|EXEC|namespace|permission|denied|failed' | tail -80 >&2 || true
  echo "Smoke workspace retained for inspection: $SMOKE" >&2
  fail "sandbox runner still failed with rc=$rc"
fi

[[ -s "$SMOKE/result.json" ]] || fail 'runner did not produce result.json'
[[ -s "$SMOKE/smoke-output.txt" ]] || fail 'sandbox did not produce smoke-output.txt'
cat "$SMOKE/result.json" | jq .

echo '--- permissions ---'
namei -l "$SMOKE/manifest.json"

echo '--- root/app storage ---'
df -h / /apps

rm -rf "$SMOKE" /tmp/solomon-v030-repair-smoke.out /tmp/solomon-v030-repair-smoke.err
log 'REPAIR COMPLETE — bounded local job execution is working'
