#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
required=(
  deploy.sh install-controller.sh install-node.sh SECURITY.md THIRD_PARTY_NOTICES.md
  upgrade-v1.0.0.sh upgrade-node-v1.0.0.sh upgrade-v0.4.0.sh upgrade-node-v0.4.0.sh
  scripts/upgrade-v1.0.0-common.sh scripts/upgrade-v0.4.0-common.sh scripts/install-job-broker.sh
  scripts/solomon-job-broker.py scripts/solomon-job-broker-client.py
  scripts/solomon-job-runner.py systemd/solomon-job-broker.socket
  systemd/solomon-job-broker@.service systemd/solomon-job-broker.tmpfiles
  scripts/seed-improvement-plan.sh scripts/seed-v040-knowledge.sh
  scripts/seed-edge-device-goals.sh config/edge-devices.yaml solomonprime/edge_devices.py
  config/edge-devices-node.yaml
  config/admin-docs.yaml solomonprime/rf.py
  docs/EDGE_DEVICE_INTEGRATION_PLAN.md
  docs/RF_EDGE_FLEET.md
  docs/SOLOMONPRIME_TED_IMPROVEMENT_PLAN.md docs/V0.4_KNOWLEDGE_WORKSPACE.md
  docs/V0.4_VALIDATION.md
  docs/IMPROVEMENT_MEMORY_OBSIDIAN_READINESS.md
  tests/test_v040.py solomonprime/knowledge.py
  solomonprime/web/admin.html solomonprime/web/admin.css solomonprime/web/admin.js
  scripts/link-openwebui-admin.sh
  scripts/configure-models-and-providers.sh scripts/model-lab.sh solomonprime/models.py
  scripts/configure-energy.sh config/energy.yaml solomonprime/energy.py
  scripts/install-edge-rf-tools.sh
  scripts/install-reverse-engineering-lab.sh scripts/license-gate.py scripts/seed-r10-goals.sh
  scripts/configure-calendars.py solomonprime/calendars.py solomonprime/voice.py
  config/license-policy.yaml config/voice.yaml config/calendars.yaml docs/TRICORDER_MOBILE_CONTRACT.md
  docs/R10_INTEGRATIONS_AND_SECURITY.md
  docs/V1_HANDOFF_AND_REBUILD.md docs/RC4_RELEASE_NOTES.md docs/GODS_EYE_VIEW_INTEGRATION_PLAN.md
  scripts/repair-ollama.sh scripts/detect-ollama-endpoint.sh scripts/install-ollama-pinned.sh scripts/bootstrap-development-workspaces.sh
  scripts/configure-mobile-gateway.sh scripts/build-tricorder.sh scripts/system-capability-report.sh
  config/self-development.yaml solomonprime/selfdev.py solomonprime/mobile.py tests/test_v100.py
  mobile/tricorder-prime/gradlew
  mobile/tricorder-prime/app/src/main/java/com/solomonprime/tricorder/ui/SolomonPrimeScreen.kt
  mobile/tricorder-prime/app/src/main/java/com/solomonprime/tricorder/data/SolomonPrimeClient.kt
  mobile/tricorder-prime/app/src/main/java/com/solomonprime/tricorder/data/SolomonPrimeConfigStore.kt
)
for file in "${required[@]}"; do
  [[ -f "$ROOT/$file" ]] || { echo "Missing required v1.0.0 file: $file" >&2; exit 2; }
done
python3 -m compileall -q "$ROOT/solomonprime" "$ROOT/scripts/solomon-job-runner.py" "$ROOT/scripts/solomon-job-broker.py" "$ROOT/scripts/solomon-job-broker-client.py" "$ROOT/scripts/configure-calendars.py"
while IFS= read -r -d "" script; do bash -n "$script"; done < <(find "$ROOT" -name "*.sh" -print0)
[[ "$(grep -Fc 'for _ in $(seq 1 90)' "$ROOT/scripts/upgrade-v1.0.0-common.sh")" -ge 2 ]] || {
  echo 'Both post-restart health checks must use a bounded readiness loop.' >&2
  exit 3
}
grep -Fq 'final v1.0.0-home-rc4 health check failed after 90 seconds' "$ROOT/scripts/upgrade-v1.0.0-common.sh"
node --check "$ROOT/solomonprime/web/admin.js"
grep -Fq 'android:usesCleartextTraffic="false"' "$ROOT/mobile/tricorder-prime/app/src/main/AndroidManifest.xml"
grep -Fq 'AndroidKeyStore' "$ROOT/mobile/tricorder-prime/app/src/main/java/com/solomonprime/tricorder/data/SolomonPrimeConfigStore.kt"
if python3 -c 'import pytest' >/dev/null 2>&1; then
  (cd "$ROOT" && PYTHONPATH="$ROOT" python3 -m pytest -q tests)
else
  echo "pytest not installed; syntax validation passed."
fi
