# Third-party and model-license notes

SolomonPrime source in this distribution is provided under the repository's
MIT license. External packages are installed only from configured operating
system repositories or an explicitly pinned, operator-confirmed upstream
installer.

Key optional components include llama.cpp and Ollama (MIT), BlueZ and rtl_433
(GPL-2.0), sigrok-cli (GPL-3.0), Wireshark/tshark (GPL-2.0), and AndroidX
(Apache-2.0). SoapySDR and every model-weight artifact require a separate
license review before installation or promotion. An installed package remains
governed by its own license; this notice does not relicense it.

Model metadata in `config/license-policy.yaml` is an allowlist and review gate,
not a substitute for the license card attached to the exact downloaded
artifact. A missing or changed license fails closed. No model weights, API
credentials, cloud responses, or third-party proprietary binaries are included
in the source repository or release archive.
