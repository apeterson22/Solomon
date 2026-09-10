#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo'; exit 1; }
API=${SOLOMON_API:-http://127.0.0.1:8765}
KEY_FILE=${SOLOMON_API_KEY_FILE:-/etc/solomonprime/api.key}
[[ -s "$KEY_FILE" ]] || { echo "Missing $KEY_FILE" >&2; exit 2; }
KEY=$(cat "$KEY_FILE")
AUTH=(-H "Authorization: Bearer $KEY" -H 'Content-Type: application/json')

remember(){
  local content="$1" tags="$2"
  jq -n --arg c "$content" --arg t "$tags" '{content:$c,tier:"semantic",agent:"research-simulation",domain:"hardware-standards",source:"Anthropic MHS research preview + MarkTechPost review, reviewed 2026-09-01",importance:0.85,confidence:0.95,tags:$t}' \
    | curl -fsS "${AUTH[@]}" -d @- "$API/v1/memory/remember" >/dev/null
}

remember 'MHS is a limited research preview from Anthropic/HHMI Janelia for model-agnostic AI-agent operation of programmable physical devices. Confirmed concepts include standardized drivers, discoverability, read/write-style primitives, reference metadata describing capabilities and enforced safety limits, and control through MCP, CLI, and code APIs. SolomonPrime should build an MHS-inspired compatibility layer now but must not claim official MHS compliance until the public specification is available or preview access is granted.' 'mhs,hardware,standards,safety,mcp'
remember 'For SolomonPrime physical-device control, hard safety envelopes belong in deterministic device drivers/policy rather than prompts. New drivers should expose states, procedures, telemetry, safety constraints, approval requirements, emergency stop, provenance, and audit events. Prefer simulator/digital-twin validation before first physical actuation.' 'mhs,physical-ai,safety,drivers,digital-twin'
remember 'Anthropic MHS case studies demonstrate a useful self-improvement pattern: agents explore and optimize a physical process, then compile validated behavior into deterministic inspectable code for repeated/high-speed execution. SolomonPrime should connect this pattern to Goals, Experiments, Critic evaluation, and promoted deterministic procedures.' 'mhs,self-improvement,experiments,deterministic-procedures'
remember 'Anthropic reports early MHS work with Raspberry Pi products and Hugging Face LeRobot. Track MHS compatibility as a SolomonPrime side project for future Pi camera/sensor nodes, farm automation, home automation, and robotics.' 'mhs,raspberry-pi,lerobot,farm,home,robotics'

# Idempotently create proposed side-project goal.
existing=$(curl -fsS -H "Authorization: Bearer $KEY" "$API/v1/goals?limit=500" | jq -r '.goals[]? | select(.name=="MHS-Compatible Physical Device Layer") | .id' | head -1)
if [[ -z "$existing" ]]; then
  jq -n '{
    name:"MHS-Compatible Physical Device Layer",
    outcome:"Design and validate an MHS-inspired, model-agnostic physical-device abstraction for SolomonPrime that can later map to the public MHS specification without weakening local safety controls.",
    why:"Prepare Home/Farm/robotics automation for safe device discovery and control while preserving driver-level safety, auditability, and portability.",
    owner:"research-simulation",
    status:"proposed",
    priority:"exploratory",
    baseline:{state:"No official MHS compatibility layer installed"},
    target:{device_manifest:true,driver_safety_envelopes:true,simulator_first:true,mcp_adapter:"optional",raspberry_pi_pilot:true},
    constraints:{no_claim_of_official_compliance:true,no_unapproved_physical_writes:true,local_first:true,cloud_advisory_only:true},
    success_metrics:["schema tests pass","simulator fault tests pass","all physical writes are audited","driver safety limits cannot be overridden by model"],
    success_criteria:["At least one Raspberry Pi/simulated device can be discovered/read through the compatibility layer","Six representative fault conditions are blocked before unsafe actuation in simulation"],
    approval_requirements:["Human approval before first real actuator write per driver class"],
    metadata:{project_type:"side-project",source_review_date:"2026-09-01",status_note:"Wait for public MHS spec or preview access before claiming compliance"}
  }' | curl -fsS "${AUTH[@]}" -d @- "$API/v1/goals" | jq '{id,name,status,priority}'
else
  echo "MHS side-project goal already exists: $existing"
fi

PROJECT=/apps/solomonprime/projects/mhs-compatibility
install -d -o "${SUDO_USER:-solomonprime}" -g "${SUDO_USER:-solomonprime}" -m 0750 "$PROJECT"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
if [[ -f "$SCRIPT_DIR/../docs/MHS_REVIEW_AND_SOLOMONPRIME_MAPPING.md" ]]; then
  install -o "${SUDO_USER:-solomonprime}" -g "${SUDO_USER:-solomonprime}" -m 0640 "$SCRIPT_DIR/../docs/MHS_REVIEW_AND_SOLOMONPRIME_MAPPING.md" "$PROJECT/README.md"
fi

echo 'MHS research memory and side-project seed complete.'
