#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
PROFILE="${1:-core}"
core=(usbutils bluez iw rtl-433 sigrok-cli minicom avrdude flashrom)
advanced=(hackrf soapysdr-tools uhd-host tshark)
packages=("${core[@]}"); [[ "$PROFILE" == advanced ]] && packages+=("${advanced[@]}")
apt-get update
available=(); missing=()
for p in "${packages[@]}"; do
  if apt-cache show "$p" >/dev/null 2>&1; then available+=("$p"); else missing+=("$p"); fi
done
((${#available[@]})) && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${available[@]}"
printf 'Installed/verified packages: %s\n' "${available[*]:-none}"
printf 'Unavailable in configured repositories: %s\n' "${missing[*]:-none}"
echo 'No capture, driver detachment, firmware write, radio transmit, injection, or pairing was started.'
echo 'Advanced tools are inert until a fingerprint-scoped Admin action is separately approved.'
