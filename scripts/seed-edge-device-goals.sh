#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
API=${SOLOMON_API:-http://127.0.0.1:8765}
KEY=$(cat "${SOLOMON_API_KEY_FILE:-/etc/solomonprime/api.key}")
AUTH=(-H "Authorization: Bearer $KEY" -H 'Content-Type: application/json')

goal_id(){ curl -fsS -H "Authorization: Bearer $KEY" "$API/v1/goals?limit=500" | jq -r --arg n "$1" '.goals[]? | select(.name==$n) | .id' | head -1; }
create(){
  local name="$1" outcome="$2" priority="$3" owner="$4"; shift 4
  local id; id=$(goal_id "$name")
  if [[ -n "$id" ]]; then printf '%s\n' "$id"; return; fi
  jq -n --arg name "$name" --arg outcome "$outcome" --arg priority "$priority" --arg owner "$owner" --argjson meta "$1" '{name:$name,outcome:$outcome,why:"Extend SolomonPrime with useful, measured home and farm capabilities while keeping device control local, reversible, private, and human-governed.",owner:$owner,status:"proposed",priority:$priority,baseline:{connection:"not established",capabilities:"photo-seeded hypotheses only"},target:{identity_verified:true,capabilities_measured:true,local_integration_documented:true},constraints:{local_first:true,free_advisors_only:true,cloud_physical_control:false,cloud_precise_location:false,no_unapproved_pairing_flashing_transmission_or_actuation:true},success_metrics:["verified hardware identity and interface evidence","reproducible local capability test","documented failure and rollback path","use case accepted by operator"],stop_criteria:["unexpected motion or heat","unknown radio behavior","credential or precise-location exposure","device identity mismatch"],approval_requirements:["Pairing approval","Firmware-write approval","Radio-transmit approval","Physical-actuation approval","Location-sharing approval"],metadata:$meta}' | curl -fsS "${AUTH[@]}" -d @- "$API/v1/goals" | jq -r .id
}

root=$(create 'Secure Edge Device Inventory and Onboarding' 'Identify each attached device, record immutable labels and interfaces, perform read-only discovery, and establish a trusted device registry without changing firmware or pairing state.' high infrastructure '{"device_scope":"all-photo-seeded-devices","phase":1}')
sensor=$(create 'Local Home and Farm Sensor Gateway' 'Turn verified Makey Makey and KosmoDuino inputs into reliable local events for gates, water/leak contacts, task buttons, checklists, and alerts.' high home-ops '{"devices":["makey-makey-01","kosmoduino-01"],"phase":2}')
robot=$(create 'Supervised Mobile Robotics Pilot' 'Evaluate the ELEGOO car and RC chassis for low-speed, supervised inspection and sensor-mule work with a physical stop and exclusion zones.' medium farm-ops '{"devices":["elegoo-car-01","mario-kart-mario-01","mario-kart-wario-01"],"phase":3}')
asset=$(create 'Private Asset Location and Recovery' 'Assign the four Android Find Hub tags to appropriate assets and document private recovery workflows without exporting locations to cloud advisors.' medium home-ops '{"devices":["raykit-tag-01","raykit-tag-02","raykit-tag-03","raykit-tag-04"],"phase":2}')
lab=$(create 'Edge Firmware and Protocol Research Lab' 'Build repeatable, receive-first test procedures for USB, BLE, serial, infrared, and proprietary radio interfaces; promote only verified local adapters.' exploratory research-simulation '{"device_scope":"edge-lab","phase":2}')

relate(){ curl -fsS "${AUTH[@]}" -d "$(jq -n --arg t "$root" '{relation:"depends_on",target_goal:$t,actor:"solomon-core",explanation:"Identity, interface evidence, and safety classification must be verified first."}')" "$API/v1/goals/$1/relationships" >/dev/null; }
relate "$sensor"; relate "$robot"; relate "$asset"; relate "$lab"
jq -n --arg root "$root" --arg sensor "$sensor" --arg robot "$robot" --arg asset "$asset" --arg lab "$lab" '{edge_device_goals:[$root,$sensor,$robot,$asset,$lab],state:"proposed",automatic_actuation:false}'
