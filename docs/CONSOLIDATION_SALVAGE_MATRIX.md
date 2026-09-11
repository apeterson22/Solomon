# SolomonPrime Consolidation Salvage Matrix

This document governs consolidation into the canonical `apeterson22/Solomon` repository.

## Rules

- `main` remains the validated v1.0.0-home RC4 baseline until a reviewed v1.1 promotion.
- All consolidation work happens on `develop/v1.1-spatial` or feature branches.
- No legacy repository history is merged into SolomonPrime. Useful material is re-created or selectively ported as fresh files with provenance notes.
- Tricorder Prime remains a separate repository. SolomonPrime may reuse API contracts, mobile patterns, sensor abstractions, and app-build lessons, but the Android application remains independently versioned.
- Gambling/betting integrations are discarded from core and are not carried forward.
- Any source repository with unresolved historical-secret findings is blocked from code salvage until the finding is cleared or affected credentials are rotated.

## Repository classification

| Repository | Disposition | Initial classification |
|---|---|---|
| `apeterson22/Solomon` | ADOPT | Canonical runtime and repository. RC4 is the stable base. |
| `apeterson22/solomon-prime` | ADOPT / PORT | Security tooling, agent scaffolding, CI/pre-commit, self-development patterns, useful runtime capabilities. Port only material that improves the current RC4 architecture. |
| `apeterson22/openclaw-solomon` | PORT / REFERENCE | Agent/tool/runtime lessons and selected capabilities. Large inherited history must not be imported. Prefer interfaces/adapters over replacing the SolomonPrime core. |
| `apeterson22/local-ai-swarm` | PORT | Distributed inference, edge-node and distillation concepts fit `compute/`, `nodes/`, and `research/distillation/`. |
| `apeterson22/agents-o-fun` | REFERENCE / SELECTIVE PORT | Self-improvement experiments, agent patterns, dashboards and data-flow ideas may be useful after full-history secret clearance. `.env`, generated DB/log/checkpoint material and gambling functionality are discarded. |
| `apeterson22/aegisqr-suite` | PORT / INTEGRATION | Security/trust workflows, enterprise approval and agent handoff patterns should inform SolomonPrime security and self-development. AegisQR remains an application/integration capability, not the core runtime. |
| `apeterson22/tricorder-prime` | REFERENCE / EXTERNAL APP | Keep repository separate. Reuse contracts, sensor abstractions and secure app↔SolomonPrime patterns when building the SolomonPrime mobile application surface. |

## Proposed v1.1 destination map

```text
Solomon/
├── runtime/                 # current SolomonPrime controller/node runtime
├── agents/                  # governed local agents and development agents
├── compute/                 # model routing, edge/fleet inference, distillation
├── memory/                  # short/long-term memory and retrieval abstractions
├── spatial/                 # native spatial core and provider adapters
├── security/                # TLS/mTLS, approvals, identity, Aegis-inspired trust
├── integrations/            # OpenClaw, Open WebUI, Ollama, cloud-review adapters
├── research/                # quantization, self-improvement, distillation experiments
├── web/                     # SolomonPrime Admin/spatial surfaces
├── infrastructure/          # deployment, PKI, node bootstrap
├── tests/
└── docs/
```

## Salvage gates

Every candidate component must pass all of the following before entering `develop/v1.1-spatial`:

1. **Secret history gate** — source history scanned; no unresolved live credential exposure.
2. **License/provenance gate** — origin, license and substantial third-party code are identified.
3. **Architecture gate** — functionality improves the current RC4 design and does not reintroduce a second controller/runtime.
4. **Security gate** — no implicit cloud egress, uncontrolled execution, hard-coded credentials, or privilege escalation.
5. **Test gate** — candidate has tests or gains tests before promotion.
6. **Rollback gate** — integration is additive/reversible until proven.
7. **Human approval gate** — no automatic merge to `main`.

## Priority salvage order

1. `solomon-prime`: security/dev tooling, agent-development scaffolding and useful mature capabilities.
2. `local-ai-swarm`: edge-node/distributed inference and distillation concepts.
3. `aegisqr-suite`: enterprise approval/trust and agent-handoff patterns.
4. `openclaw-solomon`: selectively recover capabilities not already present in `solomon-prime` or RC4; avoid duplicate framework import.
5. `agents-o-fun`: only after historical-secret scan completes; salvage concepts, not repository state.
6. `tricorder-prime`: continuously reference for mobile app/API design while keeping source separate.

## What is explicitly discarded

- gambling/betting integrations;
- committed `.env` files or other credential-bearing local config;
- generated databases/logs/checkpoints as source-of-truth artifacts;
- duplicate controllers/runtimes that conflict with SolomonPrime RC4;
- legacy model-specific code that offers no reusable abstraction;
- direct production modification by autonomous agents;
- cloud-provider logic that bypasses SolomonPrime's local-first/data-egress policy.
