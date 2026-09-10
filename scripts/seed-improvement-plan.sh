#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }

API=${SOLOMON_API:-http://127.0.0.1:8765}
KEY_FILE=${SOLOMON_API_KEY_FILE:-/etc/solomonprime/api.key}
[[ -s "$KEY_FILE" ]] || { echo "Missing $KEY_FILE" >&2; exit 2; }
KEY=$(cat "$KEY_FILE")
AUTH=(-H "Authorization: Bearer $KEY" -H 'Content-Type: application/json')
SOURCE='Operator-supplied SolomonPrime_TED_Improvement_Plan.md, preserved in the v0.3.2 package on 2026-09-02'

remember(){
  local content="$1" tags="$2"
  jq -n --arg c "$content" --arg t "$tags" --arg s "$SOURCE" \
    '{content:$c,tier:"semantic",agent:"solomon-core",domain:"continuous-improvement",source:$s,importance:0.95,confidence:1.0,tags:$t}' \
    | curl -fsS "${AUTH[@]}" -d @- "$API/v1/memory/remember" >/dev/null
}

remember 'The operator-approved SolomonPrime + TED Improvement Plan is the governing roadmap for continuous improvement. Production availability outranks research; models remain replaceable; material decisions preserve provenance; destructive actions require approval; experiments must be reproducible; promoted changes require benchmarks, regression tests, approval, and rollback.' 'improvement-plan,ted,governance,non-negotiable'
remember 'The Improvement Plan phases are: telemetry foundation, resource scheduler, evaluation engine, Improvement Mode, Knowledge Compiler, safe self-expansion, and selective model improvement. Existing capabilities must be measured honestly and incomplete phases must remain visible in the dashboard.' 'improvement-plan,phases,dashboard,telemetry,evaluation'
remember 'The target knowledge workspace combines auditable tiered memory with benchmarked hybrid retrieval and an Obsidian human workspace. User notes remain protected; agent changes to standards, SOPs, rulesets, and shared knowledge are proposals until reviewed; conflicts preserve both versions; deletion defaults to archival.' 'memory,rag,obsidian,notes,standards,sops,rules,agents,safety'

existing=$(curl -fsS -H "Authorization: Bearer $KEY" "$API/v1/goals?limit=500" \
  | jq -r '.goals[]? | select(.name=="SolomonPrime + TED Continuous Improvement System") | .id' | head -1)

if [[ -z "$existing" ]]; then
  jq -n '{
    name:"SolomonPrime + TED Continuous Improvement System",
    outcome:"Build a measured, reversible continuous-improvement system and expose its truthful state in the current SolomonPrime dashboard, including RAG quality, memory curation, Obsidian knowledge workflows, experiments, promotions, cost, and energy.",
    why:"Improve SolomonPrime reliability and capability without allowing research automation or agent-authored knowledge to bypass production safety, provenance, review, or rollback controls.",
    owner:"solomon-core",
    status:"proposed",
    priority:"high",
    baseline:{rag:"SQLite FTS5 lexical retrieval",memory:"tiered records with basic dedup/scoring",obsidian:"not implemented",dashboard:"status API only"},
    target:{telemetry:true,evaluation_engine:true,improvement_mode:true,knowledge_compiler:true,hybrid_rag:true,obsidian_workspace:true,dashboard:true,safe_self_expansion:true},
    constraints:{production_availability_first:true,local_first:true,no_unapproved_destructive_actions:true,provenance_required:true,benchmark_before_promotion:true,rollback_required:true,user_notes_protected:true},
    success_metrics:["retrieval benchmark improvement without citation regression","all promoted knowledge retains provenance","Obsidian round-trip and conflict tests pass","dashboard never marks unimplemented features active","every promoted system change has reproducible evidence and rollback"],
    success_criteria:["Improvement Plan phases and gates are visible in the dashboard","approved standards, SOPs, rulesets, notes, and agent proposals follow the versioned knowledge workflow","hybrid RAG beats the lexical baseline on an operator-approved evaluation set"],
    approval_requirements:["Human approval before first production vector backend activation","Human approval before first Obsidian bidirectional sync","Human approval before promoted agent changes can alter standards, SOPs, or rules"],
    metadata:{project_type:"core-roadmap",source_document:"docs/SOLOMONPRIME_TED_IMPROVEMENT_PLAN.md",readiness_document:"docs/IMPROVEMENT_MEMORY_OBSIDIAN_READINESS.md",seed_date:"2026-09-02"}
  }' | curl -fsS "${AUTH[@]}" -d @- "$API/v1/goals" | jq '{id,name,status,priority}'
else
  echo "Continuous-improvement goal already exists: $existing"
fi

curl -fsS -H "Authorization: Bearer $KEY" "$API/v1/improvement/status" \
  | jq '{plan,memory:{state:.memory.state,active:.memory.active,retrieval:.memory.retrieval},rag,obsidian,dashboard}'

echo 'Improvement Plan memory and roadmap seed complete.'
