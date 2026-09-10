# Tricorder mobile integration contract

This release includes the supplied Flip5 Tricorder Android source under
`mobile/tricorder-prime` and adds an `SP` workspace for the governed
SolomonPrime chat/tool path. The application ID remains
`com.solomonprime.tricorder`. Production signing keys are intentionally absent.

## Transport and enrollment

- The phone must use a trusted HTTPS endpoint. Plain LAN HTTP is prohibited for
  microphone capture and approval challenges.
- The API key is encrypted with an AES-GCM key held by Android Keystore and the
  preference file is excluded from Android cloud backup and device transfer.
- Calendar OAuth tokens and
  the SolomonPrime service key must never be embedded in an APK.

## Available server primitives

- `GET /v1/voice/status` reports local STT, TTS, speaker-verifier, and enrollment
  readiness without exposing biometric data.
- `POST /v1/audio/transcriptions` accepts bounded audio for configured local
  whisper.cpp transcription.
- `POST /v1/audio/speech` creates bounded local Piper audio.
- `POST /v1/voice/approval-challenge` creates an action- and device-session-bound
  spoken challenge. It requires HTTPS except for a loopback service client.
- `POST /v1/voice/device-session` issues a short-lived, server-signed session
  after authenticated operator confirmation.
- `POST /v1/voice/verify-challenge` checks the transcript, local speaker score,
  liveness result, action binding, session binding, expiry, and single use. Its
  result explicitly grants no action authority.

## Approval rule

Voice is never sufficient by itself. A critical operation requires a signed
device session, a fresh spoken challenge, server-side speaker verification, and
the existing action-specific Admin approval. Firmware flashing, radio transmit,
USB writes, driver detachment, location access, and movement also require the
verified hardware adapter and bounded execution parameters already enforced by
the device-action system.

## Build and signing

Run `scripts/configure-mobile-gateway.sh` to expose the API through Tailscale's
trusted HTTPS endpoint, then configure that URL in the SP tab. Build a debug APK
with `scripts/build-tricorder.sh`. Release signing and Play/phone deployment
remain operator-local because no signing keystore was supplied and none should
be committed.
