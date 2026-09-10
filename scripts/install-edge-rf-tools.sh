#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }

packages=()
command -v lsusb >/dev/null 2>&1 || packages+=(usbutils)
command -v bluetoothctl >/dev/null 2>&1 || packages+=(bluez)
command -v iw >/dev/null 2>&1 || packages+=(iw)
command -v rtl_433 >/dev/null 2>&1 || packages+=(rtl-433)
command -v sigrok-cli >/dev/null 2>&1 || packages+=(sigrok-cli)
command -v minicom >/dev/null 2>&1 || packages+=(minicom)

if ((${#packages[@]})); then
  apt-get update
  available=()
  for package in "${packages[@]}"; do
    if apt-cache show "$package" >/dev/null 2>&1; then available+=("$package"); else echo "Optional package unavailable: $package" >&2; fi
  done
  if ((${#available[@]})); then DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${available[@]}"; fi
fi

if systemctl list-unit-files bluetooth.service --no-legend 2>/dev/null | grep -q bluetooth.service; then
  systemctl enable --now bluetooth.service >/dev/null 2>&1 || true
fi

printf 'USB: %s\n' "$(command -v lsusb || true)"
printf 'Bluetooth: %s\n' "$(command -v bluetoothctl || true)"
printf 'Wi-Fi scan: %s\n' "$(command -v iw || true)"
printf 'RF receive: %s\n' "$(command -v rtl_433 || true)"
printf 'Logic/protocol decode: %s\n' "$(command -v sigrok-cli || true)"
echo 'Wideband/2.4 GHz advanced tools are installed separately with install-reverse-engineering-lab.sh advanced after hardware review.'
