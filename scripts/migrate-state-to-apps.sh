#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }

STATE_SRC=/var/lib/solomonprime
LOG_SRC=/var/log/solomonprime
DATA_ROOT=/apps/solomonprime-data
STATE_DST=$DATA_ROOT/state
LOG_DST=$DATA_ROOT/log
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR=$DATA_ROOT/migration-backups/$TS
FSTAB=/etc/fstab
MARK='# SolomonPrime /apps bind mounts'
SERVICE_WAS_ACTIVE=0

log(){ printf '\n[SOLOMON-MIGRATE] %s\n' "$*"; }
fail(){ echo "[SOLOMON-MIGRATE][ERROR] $*" >&2; exit 2; }

mkdir -p "$STATE_SRC" "$LOG_SRC" /apps
ROOT_SRC=$(findmnt -n -o SOURCE -T / || true)
APPS_SRC=$(findmnt -n -o SOURCE -T /apps || true)
[[ -n "$APPS_SRC" ]] || fail '/apps is not mounted or resolvable'
if [[ "$ROOT_SRC" == "$APPS_SRC" && "${SOLOMON_ALLOW_SAME_FS:-0}" != 1 ]]; then
  fail "/apps resolves to the same filesystem as /. Refusing because this migration would not relieve root storage. Set SOLOMON_ALLOW_SAME_FS=1 only if intentional."
fi

# Idempotent success path.
if mountpoint -q "$STATE_SRC" && mountpoint -q "$LOG_SRC" && grep -Fq "$MARK" "$FSTAB"; then
  log 'State and log bind mounts already active.'
  findmnt "$STATE_SRC" "$LOG_SRC" || true
  exit 0
fi

mkdir -p "$STATE_DST" "$LOG_DST" "$BACKUP_DIR"
chmod 750 "$DATA_ROOT" "$STATE_DST" "$LOG_DST" || true
cp -a "$FSTAB" "$BACKUP_DIR/fstab.before"

need=$(($(du -sb "$STATE_SRC" "$LOG_SRC" 2>/dev/null | awk '{s+=$1} END{print s+0}') + 536870912))
avail=$(df -B1 --output=avail /apps | tail -1 | tr -d ' ')
(( avail > need )) || fail "Insufficient free space on /apps. Need about $need bytes including safety margin; available $avail."

systemctl is-active --quiet solomonprime && SERVICE_WAS_ACTIVE=1 || true
log 'Stopping SolomonPrime for a consistent SQLite/audit copy'
systemctl stop solomonprime 2>/dev/null || true

log 'Copying state and logs to /apps'
rsync -aHAX --numeric-ids "$STATE_SRC/" "$STATE_DST/"
rsync -aHAX --numeric-ids "$LOG_SRC/" "$LOG_DST/"

log 'Checksum-verifying migration before removing root-resident copies'
state_diff=$(rsync -aHAXnc --delete --numeric-ids "$STATE_SRC/" "$STATE_DST/" || true)
log_diff=$(rsync -aHAXnc --delete --numeric-ids "$LOG_SRC/" "$LOG_DST/" || true)
[[ -z "$state_diff" && -z "$log_diff" ]] || { echo "$state_diff"; echo "$log_diff"; fail 'Verification mismatch; root copy left untouched.'; }

cat >"$BACKUP_DIR/manifest.txt" <<EOF
migration=$TS
root_source=$ROOT_SRC
apps_source=$APPS_SRC
state_source=$STATE_SRC
state_destination=$STATE_DST
log_source=$LOG_SRC
log_destination=$LOG_DST
state_bytes=$(du -sb "$STATE_DST" | awk '{print $1}')
log_bytes=$(du -sb "$LOG_DST" | awk '{print $1}')
EOF

# Add persistent mounts before switching the live paths.
if ! grep -Fq "$MARK" "$FSTAB"; then
  cat >>"$FSTAB" <<EOF

$MARK
$STATE_DST $STATE_SRC none bind,x-systemd.requires-mounts-for=/apps 0 0
$LOG_DST $LOG_SRC none bind,x-systemd.requires-mounts-for=/apps 0 0
EOF
fi
systemctl daemon-reload

rollback(){
  set +e
  echo '[SOLOMON-MIGRATE] Rolling back bind-mount migration...' >&2
  systemctl stop solomonprime 2>/dev/null
  umount "$LOG_SRC" 2>/dev/null
  umount "$STATE_SRC" 2>/dev/null
  cp -a "$BACKUP_DIR/fstab.before" "$FSTAB"
  rm -rf "$STATE_SRC"/* "$STATE_SRC"/.[!.]* "$STATE_SRC"/..?* 2>/dev/null
  rm -rf "$LOG_SRC"/* "$LOG_SRC"/.[!.]* "$LOG_SRC"/..?* 2>/dev/null
  rsync -aHAX --numeric-ids "$STATE_DST/" "$STATE_SRC/"
  rsync -aHAX --numeric-ids "$LOG_DST/" "$LOG_SRC/"
  systemctl daemon-reload
  (( SERVICE_WAS_ACTIVE )) && systemctl start solomonprime
}
trap 'rollback' ERR

log 'Removing verified root copies and activating bind mounts'
find "$STATE_SRC" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
find "$LOG_SRC" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
mount "$STATE_SRC"
mount "$LOG_SRC"
mountpoint -q "$STATE_SRC"
mountpoint -q "$LOG_SRC"

sentinel="$STATE_SRC/.migration-test-$TS"
echo ok >"$sentinel"
[[ -f "$STATE_DST/.migration-test-$TS" ]] || fail 'Bind verification sentinel did not appear under /apps'
rm -f "$sentinel"

trap - ERR
if (( SERVICE_WAS_ACTIVE )); then
  log 'Starting SolomonPrime'
  systemctl start solomonprime
  for _ in $(seq 1 60); do
    curl -fsS http://127.0.0.1:8765/health >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS http://127.0.0.1:8765/health >/dev/null || { rollback; fail 'SolomonPrime failed health check after migration'; }
fi

log 'Migration complete'
findmnt "$STATE_SRC" "$LOG_SRC" || true
df -h / /apps
printf 'Migration manifest: %s\n' "$BACKUP_DIR/manifest.txt"
