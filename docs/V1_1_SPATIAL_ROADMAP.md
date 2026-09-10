# SolomonPrime v1.1 Spatial Roadmap

## Baseline
- `main` is the validated SolomonPrime `v1.0.0-home` RC4 source only.
- Development occurs on `develop/v1.1-spatial` and feature branches.
- No agent or automation may push directly to `main`.
- Production promotion requires tests, security review, rollback evidence, and human approval.

## Legacy branch review

### `solomon-ai`
Useful concepts to retain as roadmap ideas, not code carry-forward:
- Personal/local AI OS model with multiple specialized AI applications.
- Unified model discovery/management framework.
- AI application/plugin development framework and marketplace/catalog concept.
- Strong privacy and data access-control boundary for personal data.
- Local open-source model as the normal core.
- Optional TTS, image generation, and other multimodal application integrations.
- One-click/managed application packaging where it can be implemented safely.

These concepts overlap SolomonPrime's existing goals and should be reimplemented against the
current v1 architecture rather than merging the legacy OpenDAN/DeepSeek tree.

### `codex/find-and-fix-a-bug`
### `gorlp7-codex/find-and-fix-a-bug`
No code is carried forward. These branches contain DeepSeek-specific setup/model fixes that are
not part of the SolomonPrime v1 runtime. Generic lessons retained:
- reproducible setup/bootstrap scripts;
- explicit dependency installation and environment validation;
- small regression-tested fixes rather than unbounded rewrites.

## v1.1-spatial milestone 1 — secure development foundation

1. Git governance
   - protected `main`;
   - PR-only promotion;
   - secret scanning, dependency scanning, SAST, tests;
   - signed/tagged release artifacts;
   - SBOM and provenance for releases;
   - local agent works only in isolated worktrees/branches.

2. TLS / mTLS
   - HTTPS for SolomonPrime Web UI and API;
   - local private CA for node identity;
   - unique node certificates;
   - SANs for approved LAN/Tailscale identities;
   - mTLS for controller↔node traffic;
   - retain signed application messages during transition;
   - certificate rotation/revocation and audit events;
   - CA private key unavailable to ordinary agents.

3. Model-routing / free-tier review
   - local-first inference;
   - optional free-tier/cloud models only through a provider abstraction;
   - sanitize/minimize outbound context;
   - never send credentials, precise private telemetry, or unrestricted memory;
   - use external models primarily as reviewers/critics/teachers;
   - record provider, model, prompt-classification, cost, result, and provenance;
   - no external model may directly modify production.

4. Self-development agent
   - consume goals/issues;
   - decompose tasks;
   - create isolated worktree;
   - implement candidate;
   - run tests and security scans;
   - request cross-model review when allowed;
   - benchmark against current baseline;
   - produce PR + evidence;
   - require human approval to merge/promote.

## v1.1-spatial milestone 2 — native spatial core

Create a canonical `SpatialEntity` / `SpatialEvent` contract:
- stable entity ID;
- source and provenance;
- timestamp / observed-at;
- latitude / longitude / altitude;
- heading / speed where applicable;
- entity type;
- confidence;
- metadata;
- privacy classification;
- retention policy.

Initial API:
- `GET /v1/spatial/entities`
- `GET /v1/spatial/nearby`
- `GET /v1/spatial/search`
- `GET /v1/spatial/track/{id}`
- `GET /v1/spatial/scene`
- `POST /v1/spatial/annotations`

Initial local layers:
- SolomonPrime nodes;
- approved farm/home sensors;
- approved cameras;
- RF detections;
- edge-device discoveries;
- weather/environmental observations.

Read-only is the default. Any physical actuation remains approval-gated.

## v1.1-spatial milestone 3 — God's Eye View adapter

Use `bilawalsidhu/gods-eye-view` as an MIT-licensed visualization/reference component,
not as the SolomonPrime intelligence core.

Goals:
- adapt its globe/scene concepts to SolomonPrime spatial contracts;
- keep provider/model routing behind SolomonPrime;
- support local-model scene reasoning;
- preserve source provenance for every displayed live entity;
- allow chat↔scene handoff;
- add public-data layers only through explicit connectors with terms/quotas documented;
- isolate browser-side provider keys and prefer server-side short-lived credentials where possible.

## v1.1-spatial milestone 4 — Web UI

Target navigation:
- Chat
- Spatial
- Fleet
- Models
- Agents
- Memory
- Home
- Farm
- Devices
- Cameras
- Jobs
- Experiments
- TED / FinOps
- Development
- Security

Security panel:
- node identities/certificate expiry;
- TLS status;
- pending approvals;
- recent audit/security findings;
- model/provider data-egress summary.

## Promotion criteria

A candidate may not be promoted unless:
- unit/integration tests pass;
- no new high/critical security finding is open;
- secret scan passes;
- rollback path exists and is tested;
- resource regression is acceptable;
- external-model usage has provenance and no private-data violation;
- human approval is recorded.
