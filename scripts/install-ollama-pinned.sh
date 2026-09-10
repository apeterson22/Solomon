#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
[[ "${SOLOMON_CONFIRM_OLLAMA_INSTALL:-}" == YES ]] || {
  echo 'This installs the pinned official Ollama v0.33.3 release. Rerun with SOLOMON_CONFIRM_OLLAMA_INSTALL=YES.' >&2
  exit 2
}

VERSION=0.33.3
EXPECTED_SHA256=25f64b810b947145095956533e1bdf56eacea2673c55a7e586be4515fc882c9f
URL="https://github.com/ollama/ollama/releases/download/v${VERSION}/install.sh"
INSTALLER="$(mktemp)"
trap 'shred -u "$INSTALLER" 2>/dev/null || rm -f "$INSTALLER"' EXIT
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location "$URL" --output "$INSTALLER"
printf '%s  %s\n' "$EXPECTED_SHA256" "$INSTALLER" | sha256sum --check --status || {
  echo 'Ollama installer checksum mismatch; refusing execution.' >&2
  exit 3
}
OLLAMA_VERSION="$VERSION" sh "$INSTALLER"
"$(cd "$(dirname "$0")" && pwd)/repair-ollama.sh"
ollama --version
echo 'Ollama installed from a pinned official release. No model was pulled or activated.'
