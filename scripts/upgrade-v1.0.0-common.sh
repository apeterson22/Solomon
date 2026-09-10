#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run this upgrade with sudo' >&2; exit 1; }

EXPECTED_ROLE="${1:?usage: upgrade-v1.0.0-common.sh controller|node}"
[[ "$EXPECTED_ROLE" == controller || "$EXPECTED_ROLE" == node ]] || { echo 'Invalid expected role' >&2; exit 2; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${SOLOMON_USER:-$(systemctl show solomonprime -p User --value 2>/dev/null || true)}"
APP_USER="${APP_USER:-${SUDO_USER:-}}"
id "$APP_USER" >/dev/null 2>&1 || { echo "SolomonPrime service user not found: $APP_USER" >&2; exit 2; }
APP_GROUP="$(id -gn "$APP_USER")"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT=/apps/solomonprime/upgrade-backups
[[ "$EXPECTED_ROLE" == controller && -d /apps/solomonprime-data ]] && BACKUP_ROOT=/apps/solomonprime-data/upgrade-backups
BACKUP="$BACKUP_ROOT/v100-$EXPECTED_ROLE-$TS"
ABSENT="$BACKUP/absent-paths.txt"
SUCCESS=0
CHECKPOINT_READY=0

log(){ printf '\n[SOLOMON-v1.0.0-%s] %s\n' "$EXPECTED_ROLE" "$*"; }
fail(){ echo "[SOLOMON-v1.0.0-$EXPECTED_ROLE][ERROR] $*" >&2; return 1; }

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
  if [[ $CHECKPOINT_READY -ne 1 ]]; then
    echo "Preflight/checkpoint failed; live installation was not changed." >&2
    exit "$code"
  fi
  trap - ERR
  set +e
  echo "[SOLOMON-v1.0.0-$EXPECTED_ROLE] Upgrade failed; restoring $BACKUP" >&2
  systemctl stop solomonprime >/dev/null 2>&1
  systemctl disable --now solomon-job-broker.socket >/dev/null 2>&1
  [[ -d "$BACKUP/app" ]] && rsync -a --delete --exclude '.venv' "$BACKUP/app/" /apps/solomonprime/app/
  rm -f /var/lib/solomonprime/knowledge.db-wal /var/lib/solomonprime/knowledge.db-shm
  if [[ -f "$BACKUP/knowledge.db" ]]; then
    install -o "$APP_USER" -g "$APP_GROUP" -m 0640 "$BACKUP/knowledge.db" /var/lib/solomonprime/knowledge.db
  elif [[ -f "$BACKUP/knowledge-db-was-absent" ]]; then
    rm -f /var/lib/solomonprime/knowledge.db
  fi
  if [[ -f "$BACKUP/sqlite-manifest.json" ]]; then
    python3 - "$BACKUP" <<'PY'
import json, os, shutil, sys
from pathlib import Path
backup = Path(sys.argv[1])
for item in json.loads((backup / "sqlite-manifest.json").read_text()):
    source = backup / item["backup"]
    target = Path(item["path"])
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(target) + suffix).unlink(missing_ok=True)
        shutil.copy2(source, target)
        os.chown(target, item["uid"], item["gid"])
        os.chmod(target, item["mode"])
PY
  fi
  while IFS= read -r path; do [[ -n "$path" ]] && rm -f "$path"; done <"$ABSENT"
  while IFS= read -r path; do restore_path "$path"; done <"$BACKUP/tracked-paths.txt"
  /apps/solomonprime/.venv/bin/pip install -e /apps/solomonprime/app >/dev/null 2>&1
  systemctl daemon-reload
  if [[ -f "$BACKUP/broker-socket.enabled" ]] && grep -qx enabled "$BACKUP/broker-socket.enabled"; then
    systemctl enable --now solomon-job-broker.socket >/dev/null 2>&1
  fi
  systemctl restart solomonprime
  echo "[SOLOMON-v1.0.0-$EXPECTED_ROLE] Rollback complete; inspect $BACKUP" >&2
  exit "$code"
}
trap rollback ERR

required=(
  pyproject.toml solomonprime/api.py solomonprime/jobs.py solomonprime/scheduler.py solomonprime/knowledge.py
  scripts/solomon-job-runner.py scripts/solomon-job-broker.py
  scripts/solomon-job-broker-client.py scripts/install-job-broker.sh
  scripts/seed-improvement-plan.sh
  scripts/seed-edge-device-goals.sh
  scripts/seed-r10-goals.sh
  scripts/seed-v040-knowledge.sh
  scripts/link-openwebui-admin.sh
  scripts/configure-models-and-providers.sh
  scripts/configure-energy.sh
  scripts/model-lab.sh
  scripts/install-edge-rf-tools.sh
  scripts/install-reverse-engineering-lab.sh
  scripts/configure-calendars.py
  scripts/repair-ollama.sh
  scripts/install-ollama-pinned.sh
  scripts/bootstrap-development-workspaces.sh
  scripts/configure-mobile-gateway.sh
  scripts/build-tricorder.sh
  scripts/system-capability-report.sh
  config/energy.yaml
  config/edge-devices.yaml
  config/edge-devices-node.yaml
  config/admin-docs.yaml
  config/license-policy.yaml
  config/voice.yaml
  config/calendars.yaml
  config/self-development.yaml
  docs/TRICORDER_MOBILE_CONTRACT.md
  docs/V1_HANDOFF_AND_REBUILD.md
  solomonprime/selfdev.py
  solomonprime/mobile.py
  solomonprime/rf.py
  systemd/solomon-job-broker.socket systemd/solomon-job-broker@.service
  systemd/solomon-job-broker.tmpfiles
  docs/SOLOMONPRIME_TED_IMPROVEMENT_PLAN.md
  docs/IMPROVEMENT_MEMORY_OBSIDIAN_READINESS.md
  docs/V0.4_KNOWLEDGE_WORKSPACE.md
  docs/RF_EDGE_FLEET.md
  docs/R10_INTEGRATIONS_AND_SECURITY.md
  docs/RC3_RELEASE_NOTES.md
  solomonprime/audit.py
)
for file in "${required[@]}"; do [[ -f "$SRC/$file" ]] || fail "Incomplete package: missing $file"; done
grep -q 'version = "1.0.0"' "$SRC/pyproject.toml" || fail 'Package is not v1.0.0'
python3 -m py_compile "$SRC"/solomonprime/{api,audit,jobs,scheduler,registry,knowledge,energy,cloud_router,models,edge_devices,rf,voice,calendars,selfdev,mobile}.py "$SRC"/scripts/solomon-job-{runner,broker,broker-client}.py "$SRC"/scripts/{configure-calendars,license-gate}.py

ROLE="$(python3 - <<'PY'
import yaml
print((yaml.safe_load(open('/etc/solomonprime/config.yaml')) or {}).get('role','node'))
PY
)"
[[ "$ROLE" == "$EXPECTED_ROLE" ]] || fail "This host is role=$ROLE, not $EXPECTED_ROLE"

log '0. Preflight and rollback checkpoint'
install -d -m 0700 "$BACKUP"
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
  /etc/solomonprime/open-webui.env
  /var/lib/solomonprime/energy.yaml
  /var/lib/solomonprime/edge-devices.yaml
  /var/lib/solomonprime/voice.yaml
  /var/lib/solomonprime/calendars.yaml
  /var/lib/solomonprime/self-development.yaml
)
printf '%s\n' "${tracked[@]}" >"$BACKUP/tracked-paths.txt"
for path in "${tracked[@]}"; do backup_path "$path"; done
rsync -a --delete --exclude '.venv' /apps/solomonprime/app/ "$BACKUP/app/"
if [[ -f /var/lib/solomonprime/knowledge.db ]]; then
  python3 - "$BACKUP/knowledge.db" <<'PY'
import sqlite3,sys
source=sqlite3.connect('/var/lib/solomonprime/knowledge.db')
target=sqlite3.connect(sys.argv[1])
with target: source.backup(target)
source.close();target.close()
PY
else
  : >"$BACKUP/knowledge-db-was-absent"
fi
python3 - "$BACKUP" <<'PY'
import json, os, sqlite3, sys
from pathlib import Path
backup = Path(sys.argv[1])
roots = [Path("/var/lib/solomonprime"), Path("/apps/solomonprime-data")]
seen, manifest = set(), []
out = backup / "sqlite"
out.mkdir(parents=True, exist_ok=True)
for root in roots:
    if not root.is_dir():
        continue
    paths = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d != "upgrade-backups" and not (Path(directory)/d).is_symlink()]
        paths.extend(Path(directory)/f for f in files if f.endswith(".db"))
    for path in paths:
        try:
            resolved = path.resolve(strict=True)
            if resolved in seen or not resolved.is_file():
                continue
            seen.add(resolved)
            target = out / f"{len(manifest):04d}.db"
            source_db = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=30)
            target_db = sqlite3.connect(target)
            with target_db:
                source_db.backup(target_db)
            source_db.close(); target_db.close()
            meta=resolved.stat()
            manifest.append({"path": str(resolved), "backup": str(target.relative_to(backup)), "uid":meta.st_uid,"gid":meta.st_gid,"mode":meta.st_mode & 0o777})
        except (OSError, sqlite3.Error) as exc:
            raise SystemExit(f"Unable to checkpoint SQLite database {path}: {exc}")
(backup / "sqlite-manifest.json").write_text(json.dumps(manifest, indent=2))
PY
curl --noproxy '*' -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8765/health >"$BACKUP/health.before.json" || true
systemctl is-enabled solomon-job-broker.socket >"$BACKUP/broker-socket.enabled" 2>/dev/null || printf 'disabled\n' >"$BACKUP/broker-socket.enabled"

CHECKPOINT_READY=1
log '1. Install v1.0.0 runtime'
if ! "$SRC/scripts/install-edge-rf-tools.sh"; then
  echo '[SOLOMON] Optional edge/RF tool installation failed; runtime will report unavailable capabilities instead of claiming them active.' >&2
fi
if [[ "${SOLOMON_INSTALL_OLLAMA:-}" == YES ]]; then
  SOLOMON_CONFIRM_OLLAMA_INSTALL=YES "$SRC/scripts/install-ollama-pinned.sh"
elif command -v ollama >/dev/null 2>&1 || [[ -x /usr/local/bin/ollama || -x /usr/bin/ollama || -x /snap/bin/ollama ]]; then
  "$SRC/scripts/repair-ollama.sh" || echo '[SOLOMON][WARN] Existing Ollama installation could not be recovered; llama.cpp remains unchanged.' >&2
fi
DETECTED_OLLAMA_ENDPOINT="$($SRC/scripts/detect-ollama-endpoint.sh 2>/dev/null || true)"
systemctl stop solomonprime
rsync -a --delete --exclude '.venv' --exclude '*.zip' --exclude '*.tar.gz' "$SRC/" /apps/solomonprime/app/
/apps/solomonprime/.venv/bin/pip install -e /apps/solomonprime/app
DETECTED_OLLAMA_ENDPOINT="$DETECTED_OLLAMA_ENDPOINT" python3 - <<'PY'
import os,yaml
p='/etc/solomonprime/config.yaml';d=yaml.safe_load(open(p)) or {}
d['job_runner']='/usr/local/libexec/solomon-job-broker-client'
d['job_broker_socket']='/run/solomonprime/job-broker.sock'
d.setdefault('job_workspace_dir','/apps/solomonprime-jobs')
d.setdefault('job_default_max_runtime',900)
d.setdefault('knowledge_db','/var/lib/solomonprime/knowledge.db')
d['knowledge_vector_backend']='feature_hash_v1'
d['knowledge_hybrid_enabled']=True
d['energy_config']='/var/lib/solomonprime/energy.yaml'
d.setdefault('energy_ledger','/var/lib/solomonprime/energy.db')
d.setdefault('energy_sample_interval',30)
d['edge_device_catalog']='/var/lib/solomonprime/edge-devices.yaml'
d.setdefault('edge_device_state','/var/lib/solomonprime/edge-devices.db')
d.setdefault('edge_discovery_enabled',True)
d.setdefault('edge_usb_scan_interval',5)
d.setdefault('edge_bluetooth_scan_interval',60)
d.setdefault('edge_bluetooth_scan_seconds',8)
d.setdefault('edge_bluetooth_nearby_rssi',-70)
d.setdefault('rf_monitor_enabled',True)
d.setdefault('rf_monitor_interval',300)
d.setdefault('rf_receive_window',10)
d.setdefault('rf_ledger','/var/lib/solomonprime/rf-observations.db')
d['admin_docs_path']='/apps/solomonprime/app/config/admin-docs.yaml'
d['ollama_endpoint']=os.environ.get('DETECTED_OLLAMA_ENDPOINT') or d.get('ollama_endpoint') or 'http://127.0.0.1:11434'
d.setdefault('voice_config','/var/lib/solomonprime/voice.yaml')
d.setdefault('voice_ledger','/var/lib/solomonprime/voice-approvals.db')
d.setdefault('calendar_config','/var/lib/solomonprime/calendars.yaml')
d.setdefault('calendar_ledger','/var/lib/solomonprime/calendars.db')
d.setdefault('self_development_config','/var/lib/solomonprime/self-development.yaml')
d.setdefault('self_development_ledger','/var/lib/solomonprime/self-development.db')
d.setdefault('mobile_access_ledger','/var/lib/solomonprime/mobile-access.db')
if d.get('role','node')=='controller':
    d['obsidian_enabled']=True
    d['obsidian_sync_mode']='manual'
    d['obsidian_vault_path']='/var/lib/solomonprime/obsidian'
open(p,'w').write(yaml.safe_dump(d,sort_keys=False))
PY

if [[ "$EXPECTED_ROLE" == controller ]]; then
  install -d -o "$APP_USER" -g "$APP_GROUP" -m 2770 /var/lib/solomonprime/obsidian
  if [[ ! -s /var/lib/solomonprime/energy.yaml ]]; then
    install -o "$APP_USER" -g "$APP_GROUP" -m 0640 "$SRC/config/energy.yaml" /var/lib/solomonprime/energy.yaml
  fi
  if [[ ! -s /var/lib/solomonprime/edge-devices.yaml ]]; then
    install -o "$APP_USER" -g "$APP_GROUP" -m 0640 "$SRC/config/edge-devices.yaml" /var/lib/solomonprime/edge-devices.yaml
  fi
  if [[ ! -s /var/lib/solomonprime/voice.yaml ]]; then install -o "$APP_USER" -g "$APP_GROUP" -m 0640 "$SRC/config/voice.yaml" /var/lib/solomonprime/voice.yaml; fi
  if [[ ! -s /var/lib/solomonprime/calendars.yaml ]]; then install -o "$APP_USER" -g "$APP_GROUP" -m 0640 "$SRC/config/calendars.yaml" /var/lib/solomonprime/calendars.yaml; fi
  if [[ ! -s /var/lib/solomonprime/self-development.yaml ]]; then install -o "$APP_USER" -g "$APP_GROUP" -m 0640 "$SRC/config/self-development.yaml" /var/lib/solomonprime/self-development.yaml; fi
  "$SRC/scripts/install-build-environment.sh"
  python3 - <<'BUILD_CONFIG'
import yaml
from pathlib import Path
p=Path('/var/lib/solomonprime/self-development.yaml')
d=yaml.safe_load(p.read_text()) or {}
for repo in d.get('repositories',[]):
    repo['test_commands']=[command.replace('/apps/solomonprime/.venv/bin/pytest','/apps/solomonprime-build/.venv/bin/python -m pytest') if isinstance(command,str) else command for command in repo.get('test_commands',[])]
p.write_text(yaml.safe_dump(d,sort_keys=False))
BUILD_CONFIG
  "$SRC/scripts/bootstrap-development-workspaces.sh"
else
  if [[ ! -s /var/lib/solomonprime/edge-devices.yaml ]]; then
    install -o "$APP_USER" -g "$APP_GROUP" -m 0640 "$SRC/config/edge-devices-node.yaml" /var/lib/solomonprime/edge-devices.yaml
  fi
fi

log '2. Install protected root broker and unprivileged client'
"$SRC/scripts/install-job-broker.sh" "$APP_USER"
chown root:"$APP_GROUP" /etc/solomonprime/config.yaml
chmod 0640 /etc/solomonprime/config.yaml
systemctl restart solomonprime

log '3. Verify service hardening, health, socket, and API'
for _ in $(seq 1 90); do
  health_json="$(curl --noproxy '*' -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8765/health 2>/dev/null || true)"
  version="$(jq -r '.version // empty' <<<"$health_json" 2>/dev/null || true)"
  release="$(jq -r '.release // empty' <<<"$health_json" 2>/dev/null || true)"
  [[ "$version" == 1.0.0 && "$release" == home-rc4 ]] && break
  sleep 1
done
[[ "${version:-}" == 1.0.0 && "${release:-}" == home-rc4 ]] || { journalctl -u solomonprime -n 120 --no-pager; fail 'v1.0.0-home-rc4 health check failed'; }
[[ "$(systemctl show solomonprime -p NoNewPrivileges --value)" == yes ]] || fail 'NoNewPrivileges is not enabled'
[[ -S /run/solomonprime/job-broker.sock ]] || fail 'broker socket is unavailable'
[[ "$(stat -c '%a %U %G' /run/solomonprime/job-broker.sock)" == '660 root solomonprime' ]] || fail 'broker socket permissions are incorrect'
KEY="$(cat /etc/solomonprime/api.key)"
curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/edge-devices >/dev/null
curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/rf/status >/dev/null
curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/voice/status >/dev/null
if [[ "$EXPECTED_ROLE" == controller ]]; then
  log '3b. Adopt/link existing Open WebUI to SolomonPrime Admin workspace'
  "$SRC/scripts/link-openwebui-admin.sh" || echo '[SOLOMON][WARN] Open WebUI Admin-link adoption was not completed; existing container was preserved.' >&2
fi
curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/calendars/status >/dev/null
curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/documentation | jq -e '.sections|length>0' >/dev/null
if [[ "$EXPECTED_ROLE" == controller ]]; then
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/goals >/dev/null
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/experiments >/dev/null
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/jobs >/dev/null
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/development/status | jq -e '.enabled==true and (.repositories|length)==2' >/dev/null
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/mobile/devices | jq -e '.tokens_displayed==false' >/dev/null
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 -H "Authorization: Bearer $KEY" http://127.0.0.1:8765/v1/improvement/status | jq -e '.plan.present==true and .rag.state=="active" and .rag.hybrid_retrieval==true and .rag.neural_semantic_embeddings==false and .knowledge.governance.automatic_conflict_resolution==false and .obsidian.state=="available_manual_governed" and .dashboard.visual_improvement_workspace=="active"' >/dev/null
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 http://127.0.0.1:8765/openapi.json | jq -e '.components.schemas.JobSubmitRequest and .components.schemas.JobResources' >/dev/null
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 http://127.0.0.1:8765/openapi.json | jq -e '.paths["/v1/knowledge"] and .paths["/v1/models/local"] and .paths["/v1/edge-devices"] and .paths["/v1/rf/status"] and .paths["/v1/rf/fleet"] and .paths["/v1/voice/status"] and .paths["/v1/voice/device-session"] and .paths["/v1/voice/verify-challenge"] and .paths["/v1/calendars/status"] and .paths["/v1/development/status"] and .paths["/v1/mobile/devices"] and .paths["/v1/tools/self-test"] and .paths["/v1/documentation"] and .paths["/v1/integration/status"] and .paths["/admin"]' >/dev/null
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 10 http://127.0.0.1:8765/admin | grep -q 'SolomonPrime Admin'
  "$SRC/scripts/seed-improvement-plan.sh"
  "$SRC/scripts/seed-edge-device-goals.sh" | jq -e '.automatic_actuation==false and (.edge_device_goals|length)==5' >/dev/null
  "$SRC/scripts/seed-r10-goals.sh" | jq -e '.automatic_promotion==false and (.goals|length)==3' >/dev/null
  "$SRC/scripts/seed-v040-knowledge.sh" | jq -e '(.inserted==true and .state=="review") or (.deduplicated==true)' >/dev/null
fi

"$SRC/scripts/system-capability-report.sh" >/dev/null || echo '[SOLOMON][WARN] Local capability report could not be refreshed.' >&2

log '4. Execute broker smoke test from a NoNewPrivileges client'
SMOKE="/apps/solomonprime-jobs/JOB-BROKER-SMOKE-$TS"
install -d -o "$APP_USER" -g solomonprime -m 0770 "$SMOKE"
command tee "$SMOKE/main.py" >/dev/null <<'PY'
from pathlib import Path
Path('broker-smoke-output.txt').write_text('NoNewPrivileges broker path OK\n')
print('broker-smoke-ok')
PY
chown "$APP_USER":solomonprime "$SMOKE/main.py"
chmod 0640 "$SMOKE/main.py"
SOURCE_SHA="$(sha256sum "$SMOKE/main.py" | awk '{print $1}')"
command tee "$SMOKE/manifest.json" >/dev/null <<EOF
{"job_id":"JOB-BROKER-SMOKE-$TS","workspace":"$SMOKE","kind":"python","risk":"reversible","source_file":"main.py","source_sha256":"$SOURCE_SHA","resources":{"max_runtime_seconds":30,"max_memory_gb":1,"max_cpu_cores":1,"max_disk_gb":1},"allow_network":false}
EOF
chown "$APP_USER":solomonprime "$SMOKE/manifest.json"
chmod 0640 "$SMOKE/manifest.json"
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
final_release=""
for _ in $(seq 1 90); do
  final_health="$(curl --noproxy '*' -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8765/health 2>/dev/null || true)"
  final_version="$(jq -r '.version // empty' <<<"$final_health" 2>/dev/null || true)"
  final_release="$(jq -r '.release // empty' <<<"$final_health" 2>/dev/null || true)"
  [[ "$final_version" == 1.0.0 && "$final_release" == home-rc4 ]] && break
  sleep 1
done
if [[ "$final_version" != 1.0.0 || "$final_release" != home-rc4 ]]; then
  journalctl -u solomonprime -n 120 --no-pager
  fail 'final v1.0.0-home-rc4 health check failed after 90 seconds'
fi

if [[ "$EXPECTED_ROLE" == controller ]]; then
  log '6. Link the existing Open WebUI to the unified Admin workspace'
  if ! "$SRC/scripts/link-openwebui-admin.sh"; then
    echo '[SOLOMON-v1.0.0-controller][WARN] Open WebUI remains available, but its Admin navigation banner could not be refreshed.' >&2
  fi
fi

SUCCESS=1
trap - ERR
log 'UPGRADE COMPLETE'
echo "Backup: $BACKUP"
echo "Release: $(curl --noproxy '*' -fsS --connect-timeout 2 --max-time 5 http://127.0.0.1:8765/health | jq -r '(.version + "-" + .release)')"
echo "NoNewPrivileges: $(systemctl show solomonprime -p NoNewPrivileges --value)"
echo "Broker socket: $(stat -c '%a %U:%G %n' /run/solomonprime/job-broker.sock)"
