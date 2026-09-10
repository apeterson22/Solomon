#!/usr/bin/env bash
# Read-only checks; no credentials or configuration values printed.
set -Eeuo pipefail
FAIL=0
for tool in python3 systemctl curl jq rsync; do
  if command -v "$tool" >/dev/null; then echo "OK: $tool"; else echo "MISSING: $tool"; FAIL=1; fi
done
[[ "$(ps -p 1 -o comm=)" == systemd ]] || { echo 'FAIL: systemd must be PID 1'; FAIL=1; }
python3 - <<'PY' || FAIL=1
import sys
assert sys.version_info >= (3,11), 'Python 3.11+ required'
import yaml
print('OK: Python version and system PyYAML')
PY
if [[ -e /etc/solomonprime/config.yaml ]]; then
  echo 'Existing installation: use upgrade'
  curl -fsS --max-time 5 http://127.0.0.1:8765/health || FAIL=1
else
  echo 'No installation found: use install'
fi
exit "$FAIL"
