# SolomonPrime v1.0.0 local development handoff and rebuild

v1.0.0 turns SolomonPrime into a governed maintainer of development copies. It does
not give a language model root, secret-store, live-runtime, Git-push, radio, or
firmware authority.

## Authority boundary

- Automatic: inventory allowlisted repositories, bounded text read/search,
  unified-diff drafting, `git apply --check`, and allowlisted tests.
- Admin approval: apply an exact SHA-256-bound patch to a development copy.
- Separate operator execution: promote to live, install packages, restart a
  service, push Git, pair/control hardware, transmit RF, or flash firmware.
- Never exposed: provider keys, OAuth tokens, API keys, calendar tokens,
  voiceprints, device secrets, runtime databases, and signing keys.

## Reproducible layouts

- Live runtime: `/apps/solomonprime/app`
- Python environment: `/apps/solomonprime/.venv`
- State: `/var/lib/solomonprime`
- Secrets: `/etc/solomonprime/secrets`
- Development copies: `/apps/solomonprime-development`
- Bounded job workspaces: `/apps/solomonprime-jobs`

## Install or upgrade

Use the same entry point for a rebuild, a new node, or any supported pre-v1
installation:

```bash
sudo ./deploy.sh controller install   # clean controller
sudo ./deploy.sh controller upgrade   # existing pre-v1 controller
sudo ./deploy.sh node install         # clean worker; requires local cluster key input
sudo ./deploy.sh node upgrade         # existing worker
```

An upgrade creates a timestamped runtime/configuration checkpoint and a
consistent SQLite backup of every discovered SolomonPrime database. The
installer does not export those checkpoints, capability reports, secrets, or
machine identifiers. The controller verifies health, API schema, Admin,
knowledge, development workspaces, mobile-token isolation, broker hardening,
and the preserved Open WebUI link before declaring success.

The installer runs `scripts/bootstrap-development-workspaces.sh`. The script
creates local Git repositories with no remote and preserves an existing
development tree. Add a Git remote only from an operator shell after reviewing
the target and credentials.

## Tricorder

The supplied Android source is under `mobile/tricorder-prime`. Its SP tab talks
to SolomonPrime through HTTPS, stores a revocable scope-limited mobile token
with Android Keystore-backed AES-GCM, and can use the governed chat/tool path.
The token cannot enter Admin or approve an action. The app does not embed
signing keys or credentials. Issue the token in Admin → Voice & Mobile, run
`sudo scripts/configure-mobile-gateway.sh`, copy the printed HTTPS URL and the
one-time token into the app, and build with `scripts/build-tricorder.sh` after
installing a local Android SDK.

## Ollama

`repair-ollama.sh` reuses an already installed executable, repairs or creates a
loopback-only service, and never downloads a binary. Model downloads remain
license-gated and never replace the active llama.cpp model automatically.

If Ollama is absent, v1 includes a separate operator-confirmed installer pinned
to the official v0.33.3 release installer and its published SHA-256. It does
not pull or activate a model:

```bash
sudo SOLOMON_CONFIRM_OLLAMA_INSTALL=YES ./scripts/install-ollama-pinned.sh
```

Set `SOLOMON_INSTALL_OLLAMA=YES` on the v1 controller upgrade only when that
additional runtime is desired. The active llama.cpp service is not replaced.

## Calendar OAuth

Google and Microsoft 365 use separate read-only OAuth applications and token
stores. Use the explicit commands below; a connected ChatGPT calendar plugin
does not transfer a credential to the SolomonPrime controller.

```bash
sudo /apps/solomonprime/.venv/bin/python \
  /apps/solomonprime/app/scripts/configure-calendars.py connect google
sudo /apps/solomonprime/.venv/bin/python \
  /apps/solomonprime/app/scripts/configure-calendars.py connect m365
```

OAuth client files and tokens stay under `/etc/solomonprime/secrets` and
`/var/lib/solomonprime`; neither location is copied to a development workspace
or GitHub.

## Nodes

Use `upgrade-node-v1.0.0.sh` on an existing node. A clean new host uses
`install-node.sh`. Each node discovers its own hardware, USB/BLE/RF receive
capabilities and reports bounded summaries through signed mesh heartbeats.
