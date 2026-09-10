# SolomonPrime r10 integrations and security

## Ollama

Discovery uses `GET /api/tags` on the configured daemon URL. It no longer depends on the root user's CLI output. `:cloud` and `-cloud` names are classified as cloud-backed. Local and cloud models remain separate providers, and cloud is allowed only after free/included-only confirmation.

## Calendar isolation

- Google: delegated `calendar.readonly`, its own OAuth client JSON and token.
- M365: delegated `Calendars.Read`, MSAL device-code flow, its own cache.
- No write scope, no shared token, no browser-visible secret, and no cloud-advisor export.
- Local SQLite contains normalized meetings and their source label.

## Voice

The server contract and challenge ledger are present. A ready state requires local STT, local TTS, a server-side speaker verifier, speaker enrollment, HTTPS, and a signed phone/browser session. A fresh random phrase is bound to one existing action and expires. Voice is additive authentication; critical actions also retain Admin confirmation.

The Flip5 Tricorder APK is not included because the existing application source, package ID, API contract, and signing configuration were not available in this release workspace. The Admin Voice & Mobile page reports this explicitly.

## Reverse-engineering lab

Core tools cover USB descriptors, BlueZ/BLE observation, Wi-Fi capability inspection, sub-GHz rtl_433 reception, serial, and logic/protocol decoding. The advanced installer adds available HackRF, SoapySDR, UHD, and tshark packages. Tool presence does not prove attached hardware capability.

RTL-SDR/rtl_433 is not a full 2.4 GHz receiver. Full 2.4 GHz analysis requires compatible HackRF/Ubertooth/USRP/Soapy hardware or a Wi-Fi adapter whose driver reports monitor mode. Transmission, injection, driver detachment, firmware writing, pairing, and movement remain action-specific and time-bounded.

## Licensing

`config/license-policy.yaml` records approved software and model licenses. Model weights are checked separately from runtimes. Unknown licenses fail closed. GPL components are permitted for local use and redistribution only with their license obligations preserved.

## Open WebUI

SolomonPrime continues to use the supported OpenAI-compatible model gateway. `/v1/tools/openapi.json` exposes the read-only local tool surface for supported Open WebUI OpenAPI tool integration, while `/v1/tools/self-test` verifies the live bridge without asking a model. Empty upstream answers now produce an explicit integration error/evidence response instead of a blank chat bubble.

Browser microphone access and protection of the Admin bearer key require HTTPS. r10 reports this requirement but does not silently create a local certificate authority or claim clients trust it.
