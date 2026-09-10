#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
MODE="${1:-}"
[[ "$MODE" == available || "$MODE" == gaming || "$MODE" == disabled ]] || exit 2
python3 - "$MODE" <<'PY'
import json, os, sys, time
from pathlib import Path
p=Path('/etc/solomonprime/availability.json')
tmp=p.with_suffix('.tmp')
tmp.write_text(json.dumps({'mode':sys.argv[1],'expires':time.time()+30}))
tmp.chmod(0o644)
os.replace(tmp,p)
PY
if [[ "$MODE" != available ]]; then
  # Kill only SolomonPrime's bounded jobs. Their runners record the failure.
  systemctl stop 'solomon-job-JOB-*.service' 2>/dev/null || true
  # Optional dedicated inference service, configured locally by the operator.
  if [[ -f /etc/solomonprime/opportunistic-ollama ]]; then
    systemctl stop ollama.service
  fi
elif [[ -f /etc/solomonprime/opportunistic-ollama ]]; then
  systemctl start ollama.service
fi
