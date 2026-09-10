#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
OUT=/var/lib/solomonprime/capability-report.json
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
python3 - "$TMP" <<'PY'
import json,os,platform,shutil,subprocess,sys,time
def run(argv):
    try:return subprocess.run(argv,text=True,capture_output=True,timeout=20,check=False).stdout[-100000:]
    except Exception:return ""
tools=["git","python3","docker","ollama","llama-server","rtl_433","hackrf_info","SoapySDRUtil","bluetoothctl","adb","gradle","node","pnpm"]
report={
  "generated":time.time(),"local_only":True,"secrets_included":False,
  "os":{"system":platform.system(),"release":platform.release(),"machine":platform.machine()},
  "cpu":run(["lscpu","-J"]),"memory":run(["free","-b"]),
  "pci":run(["lspci","-nn"]),"usb":run(["lsusb"]),"block":run(["lsblk","-J","-o","NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,MODEL,ROTA"]),
  "network":run(["ip","-j","addr","show"]),
  "services":{name:run(["systemctl","is-active",name]).strip() for name in ("solomonprime","solomon-llama","ollama","bluetooth","docker","tailscaled")},
  "tools":{name:(shutil.which(name) or "") for name in tools},
}
open(sys.argv[1],"w").write(json.dumps(report,indent=2))
PY
APP_USER="${SOLOMON_USER:-$(systemctl show solomonprime -p User --value 2>/dev/null || true)}"
APP_USER="${APP_USER:-${SUDO_USER:-solomonprime}}"
install -o "$APP_USER" -g "$(id -gn "$APP_USER")" -m 0640 "$TMP" "$OUT"
echo "$OUT"
