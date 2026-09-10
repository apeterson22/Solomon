> DEVELOPMENT CHECKPOINT: v1 is not yet approved for installation. See docs/SELF_MAINTENANCE.md for new work and remaining release gates.

> **Home test release:** `v1.0.0-home-rc4`. RC4 finalizes the RC3 stability baseline with local Ollama endpoint discovery and existing Open WebUI adoption. See `docs/RC4_RELEASE_NOTES.md`.


# SolomonPrime v1.0.0 home-test candidate 2

This is a supervised home-test candidate, not a validated stable release. See
`docs/HOME_TEST_RELEASE.md` for installation, new skills, test status and open gates.

The candidate It packages the supplied Tricorder Prime Android
source, adds a secure `SP` workspace, and creates local development copies that
SolomonPrime can inspect, search, patch, validate, and test. Patch application
is SHA-256-bound to an Admin approval and can target development copies only.
Live deployment, Git push, package installation, service restart, credentials,
firmware, RF transmission, and physical actions remain operator-controlled.

The installer creates a local capability report without secrets, provides one
explicit `deploy.sh controller|node install|upgrade` entry point, preserves
runtime state, and initializes development repositories with no remote. It also
repairs the r10 calendar prompt, adds truthful Ollama daemon recovery, and
provides a Tailscale HTTPS setup for the Flip5 client. See
`docs/V1_HANDOFF_AND_REBUILD.md`.

## One deployment entry point

Upgrade an existing pre-v1 controller:

```bash
cd ~/solomonprime_v1.0.0
chmod +x deploy.sh scripts/*.sh mobile/tricorder-prime/gradlew
sudo SOLOMON_ADMIN_URL='http://CONTROLLER-IP:8765/admin' ./deploy.sh controller upgrade
```

Existing worker node:

```bash
sudo ./deploy.sh node upgrade
```

New hosts use `controller install` or `node install`. Secrets are prompted or
generated locally under `/etc/solomonprime`; they are never included in the
release or development repositories.

The upgrade checkpoints all discovered SolomonPrime SQLite databases with the
SQLite backup API, preserves Open WebUI's named data volume, migrates the
configuration in place, and rolls back the live runtime and state checkpoint if
verification fails. Machine capability reports remain local under
`/var/lib/solomonprime`.

After the upgrade:

```bash
sudo ./scripts/repair-ollama.sh
sudo /apps/solomonprime/.venv/bin/python \
  /apps/solomonprime/app/scripts/configure-calendars.py connect google
sudo ./scripts/configure-mobile-gateway.sh
```

The supplied Tricorder source did not include a production signing keystore.
The package can build a debug APK when an Android SDK is present; production
signing remains local by design.

## r10 baseline

Revision r10 replaces CLI-dependent Ollama discovery with the daemon's HTTP
inventory, reports exact enablement failures, supports local and `:cloud` /
`-cloud` Ollama models behind free-only gates, and adds license-gated local
model candidates. The WebUI tool path now has a deterministic self-test,
read-only OpenAPI tool schema, and an explicit non-empty fallback when a model
backend fails to synthesize tool evidence.

r10 adds three governed continuous-improvement goals covering retrieval
accuracy/latency/energy, reverse-engineering capability research, and complete
answer/tool/runtime performance regression testing. The RF inventory now
distinguishes sub-GHz rtl_433 reception from real 2.4 GHz-capable hardware and
reports Bluetooth/BLE, Wi-Fi monitor-mode, SDR, serial, and logic-tool readiness.

Admin adds Voice & Mobile and Calendars. Voice challenges are fresh,
action-bound, and device-session-bound; voice cannot authorize alone. Google
Calendar and M365 use separate delegated read-only OAuth clients and token
stores, and calendar events are denied to cloud advisors. The Flip5 Tricorder
gateway contract is present, while the APK correctly remains source-gated until
the existing Tricorder repository and signing configuration are supplied.

Revision r9 extends edge discovery and receive-only RF monitoring to every
controller and node. Bounded summaries travel through signed heartbeats and
appear in Admin → RF Monitoring. It detects supported RF tool/hardware
candidates, records redacted rtl_433 observations when available, and keeps RF
transmission disabled until a verified adapter, regional policy and exact
approval exist.

Admin now includes Documentation sourced from `config/admin-docs.yaml` and live
integration health. The Open WebUI linker validates the WebUI version endpoint,
Admin page, banner, and SolomonPrime model exposure from inside the container;
it restores the previous container if validation fails.

Revision r8 added a photo-seeded edge-device fleet and five staged goals for
secure discovery, home/farm sensing, supervised robotics, private asset
location, and firmware/protocol research. Admin → Edge Devices shows nine
inventory records without claiming they are connected. Pairing, firmware
writes, radio transmission, physical actuation, and location sharing remain
explicit approval gates. Cloud assistance stays free-only, receives no precise
location or live private telemetry, and has no device-control authority.

Dynamic discovery fingerprints newly attached USB devices and Bluetooth
advertisements. All discoveries enter quarantine for Admin approval or denial.
Approval enables local protocol analysis planning only—not pairing, writes,
firmware changes, radio commands, location access, or physical control.

After local-analysis approval, Admin provides a separate time-bounded action
authorization ledger for pairing, authentication, USB writes, driver detach,
firmware, radio, location, and movement. BlueZ pairing/connection can execute
through fixed commands. Higher-risk operations remain unavailable until a
signed adapter for the exact device fingerprint is installed and validated.

This release upgrades the validated v0.3.2 controller/worker mesh without
replacing its databases or weakening its protected job broker.

Revision r2 removes the installer's dependency on `/dev/stdin` behaving like a
regular file. It supersedes r1 after worker-node correctly rolled back from that
portability failure.

Revision r3 sanitizes normal punctuation before constructing the FTS5 MATCH
expression, preserving lexical scores for queries containing values such as
`v0.4`.

Revision r4 replaces the temporary JSON status page with one responsive Admin
workspace and links it from the existing Open WebUI without replacing the
`open-webui` data volume. Chats, users, history and workspaces remain in Open
WebUI on port 3000. Admin operations remain on the authenticated SolomonPrime
API and are presented in one console at `/admin`.

Revision r5 corrects Admin-link selection on multi-homed controllers. It uses
the default-route source address instead of interface enumeration order and
supports an explicit `SOLOMON_ADMIN_URL` override.

Revision r6 adds runtime discovery of downloaded GGUF and Ollama models, a
Models section in Admin, an explicit local-only Open WebUI choice, and gated
OpenAI/OpenRouter/Gemini advisor choices. Provider secrets are entered locally
and stored only in root-controlled files. Paid providers require confirmed
upstream hard limits plus conservative local request, token, and dollar
reservations. OpenRouter also checks its live finite per-key credit limit.
The model lab exposes four allowlisted download candidates (Qwen3.5 27B,
Gemma 3 12B, Ministral 3 14B, and Ollama gpt-oss 20B); downloads never become the active model
without separate benchmark evidence and an operator-controlled service change.

Revision r7 makes cross-model advice free-only and local-first. The local
SolomonPrime model always owns the final response; bounded advisors are tried in
the governed order OpenRouter free, Ollama local, Ollama included cloud, Gemini
Free Tier, and OpenAI disabled. Very complex requests may use two independent
advisors before local synthesis. Open WebUI defaults new chats to SolomonPrime
and warns that directly selected provider models cannot access SolomonPrime's
live fleet tools.

r7 also adds a configurable TED electricity provider and component-energy
ledger. Chickasaw Electric Cooperative residential service is seeded from the
September 2026 monthly rate sheet at $0.10626/kWh and an $18.14 monthly fixed
charge. TED can discover newer official Chickasaw monthly PDFs, preserves rate
history and source hashes, and permits manual configuration for other
providers. Component sensors are never represented as whole-premises power.

## What v0.4 adds

- A separate, additive governed knowledge ledger.
- Approved-only hybrid lexical/vector retrieval with structured citations.
- Versioned drafts, reviews, approvals, supersession and retirement events.
- Contradiction detection with human-only resolution.
- Preview-only memory/knowledge consolidation.
- Manual, governed Obsidian-compatible Markdown exchange.
- One live Admin workspace for fleet, goals, jobs, experiments, knowledge,
  approvals, and TED FinOps/observability.
- Retrieval evaluation evidence without automatic backend promotion.

The bundled `feature_hash_v1` vectors are deterministic and offline. They are
not represented as neural semantic embeddings. A neural provider remains an
operator-approved future promotion.

## Fleet upgrade order

Upgrade the controller first:

```bash
cd ~/solomonprime_v1.0.0
chmod +x deploy.sh upgrade-v1.0.0.sh upgrade-node-v1.0.0.sh scripts/*.sh
sudo ./deploy.sh controller upgrade
```

Upgrade each trusted worker to enable its local edge/RF discovery and signed
fleet reporting:

```bash
cd ~/solomonprime_v1.0.0
sudo ./deploy.sh node upgrade
```

Each installer creates a timestamped rollback checkpoint, checks service
hardening, exercises the protected job broker, verifies the APIs and restarts
into v1.0.0. The controller creates `/var/lib/solomonprime/obsidian` with
service-user group ownership and mode `2770`. This avoids weakening permissions
on the previously inaccessible `/apps/solomonprime-data` hierarchy.
Upgrade the controller first, then each trusted worker. Older node compute and
job functions remain compatible while nodes are upgraded one at a time, but v1
edge/RF discovery and capability reporting appear only after that node receives
v1.

## Verification

```bash
KEY=$(sudo cat /etc/solomonprime/api.key)

curl -sS http://127.0.0.1:8765/health | jq

curl -sS -H "Authorization: Bearer $KEY" \
  http://127.0.0.1:8765/v1/improvement/status | jq

curl -sS -H "Authorization: Bearer $KEY" \
  http://127.0.0.1:8765/v1/knowledge | jq
```

Open the established chat UI and the unified Admin workspace at:

```text
http://CONTROLLER-IP:3000
http://CONTROLLER-IP:8765/admin
```

Open WebUI displays a persistent supported banner linking to Admin. The Admin
workspace asks for the API key and retains it only in that browser tab's
session storage. It does not place the key in the URL.

See `docs/V0.4_KNOWLEDGE_WORKSPACE.md` for lifecycle, security invariants and
endpoint details. Existing v0.3.2 documentation remains packaged as historical
and security-baseline evidence.

After the controller upgrade, configure provider credentials and ceilings
interactively without printing keys:

```bash
sudo ./scripts/configure-models-and-providers.sh
```

List or download local candidates without promoting them:

```bash
sudo ./scripts/model-lab.sh list-candidates
sudo ./scripts/model-lab.sh download gemma3-12b-q4
```

The provider setup validates all three credentials without printing them.
OpenRouter must expose a finite per-key credit limit and use the free router or
a model ending in `:free`. Gemini requires explicit Free Tier/no-charge
confirmation. The OpenAI credential may be retained and validated, but OpenAI
remains disabled because its API is metered. A failed check leaves that provider
disabled, while local inference remains available. Blank credential prompts
preserve already configured secrets.

Admin → Configuration changes the complexity thresholds, advisor count,
electric utility, tariff, and automatic updater. API keys remain CLI-only.

Authorize the two read-only calendar connectors separately (or revoke either
local token cache) with:

```bash
sudo /apps/solomonprime/.venv/bin/python \
  /apps/solomonprime/app/scripts/configure-calendars.py
```

Google requires a Desktop OAuth client JSON at the configured secret path;
M365 requires a public-client application ID. The connected Google Calendar
plugin in ChatGPT is a separate authorization and does not copy credentials to
controller host.

Voice API primitives are installed but remain disabled until Admin reports
local STT, local TTS, speaker-verifier, enrollment, and trusted HTTPS as ready.
The direct `http://CONTROLLER-IP` URLs must not be used for microphone approvals.
See `docs/TRICORDER_MOBILE_CONTRACT.md` for the exact mobile boundary.


## Post-v1 spatial capability track

See `docs/GODS_EYE_VIEW_INTEGRATION_PLAN.md` for the planned local-first spatial/3D situational-awareness integration.
