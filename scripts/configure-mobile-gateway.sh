#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
command -v tailscale >/dev/null || { echo 'Tailscale is required for the trusted mobile HTTPS gateway.' >&2; exit 2; }
tailscale status >/dev/null 2>&1 || { echo 'Authenticate Tailscale first: sudo tailscale up' >&2; exit 2; }
DNS_NAME="$(tailscale status --json | python3 -c 'import json,sys; print((json.load(sys.stdin).get("Self") or {}).get("DNSName","").rstrip("."))')"
[[ -n "$DNS_NAME" ]] || { echo 'Tailscale MagicDNS/HTTPS name is unavailable.' >&2; exit 3; }
tailscale serve --yes --bg --https=443 http://127.0.0.1:8765
echo "Trusted Tricorder gateway: https://$DNS_NAME"
echo 'Use this URL and the one-time scope-limited mobile token from Admin → Voice & Mobile.'
echo 'The Tricorder stores that token with Android Keystore-backed encryption; do not enter the Admin API key.'
