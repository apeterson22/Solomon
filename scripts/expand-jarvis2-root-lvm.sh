#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
TARGET_GB=${TARGET_GB:-200}
ROOT_SRC=$(findmnt -n -o SOURCE /)
[[ "$ROOT_SRC" == /dev/mapper/* || "$ROOT_SRC" == /dev/*/* ]] || { echo "Root is not an LVM LV: $ROOT_SRC"; exit 2; }
CUR_BYTES=$(blockdev --getsize64 "$ROOT_SRC")
CUR_GB=$(( CUR_BYTES / 1024 / 1024 / 1024 ))
echo "Root LV: $ROOT_SRC current≈${CUR_GB}GiB target=${TARGET_GB}GiB"
lvs; vgs; df -h /
if (( CUR_GB >= TARGET_GB-2 )); then echo 'Root already at/above target; nothing to do.'; exit 0; fi
NEED=$((TARGET_GB-CUR_GB))
FREE_BYTES=$(vgs --noheadings --units b --nosuffix -o vg_free "$(lvs --noheadings -o vg_name "$ROOT_SRC" | xargs)" | xargs | cut -d. -f1)
NEED_BYTES=$((NEED*1024*1024*1024))
(( FREE_BYTES > NEED_BYTES )) || { echo 'Insufficient VG free space'; exit 3; }
[[ "${APPLY:-0}" == 1 ]] || { echo "Dry-run only. To expand online, run: sudo APPLY=1 TARGET_GB=$TARGET_GB $0"; exit 0; }
lvextend -r -L "${TARGET_GB}G" "$ROOT_SRC"
df -h /
