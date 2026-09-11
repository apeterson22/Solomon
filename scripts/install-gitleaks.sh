#!/usr/bin/env bash
set -euo pipefail

BIN_DIR="${BIN_DIR:-/usr/local/bin}"
VERSION="${GITLEAKS_VERSION:-latest}"

if command -v gitleaks >/dev/null 2>&1; then
  echo "Gitleaks already installed: $(gitleaks version 2>/dev/null || true)"
  exit 0
fi

arch="$(uname -m)"
case "$arch" in
  x86_64|amd64) asset_arch="x64" ;;
  aarch64|arm64) asset_arch="arm64" ;;
  *) echo "Unsupported architecture: $arch" >&2; exit 2 ;;
esac

if [[ "$VERSION" == "latest" ]]; then
  VERSION="$(curl -fsSL https://api.github.com/repos/gitleaks/gitleaks/releases/latest | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p' | head -1)"
fi
[[ -n "$VERSION" ]] || { echo "Could not resolve Gitleaks version" >&2; exit 3; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
asset="gitleaks_${VERSION}_linux_${asset_arch}.tar.gz"
url="https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/${asset}"

echo "Downloading Gitleaks v${VERSION} for linux/${asset_arch}..."
curl -fL "$url" -o "$work/$asset"
tar -xzf "$work/$asset" -C "$work" gitleaks
sudo install -o root -g root -m 0755 "$work/gitleaks" "$BIN_DIR/gitleaks"

echo "Installed: $BIN_DIR/gitleaks"
gitleaks version
