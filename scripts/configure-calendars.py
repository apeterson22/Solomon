#!/usr/bin/env python3
"""Configure isolated, read-only Google and M365 calendar connectors."""
from __future__ import annotations

import argparse
import json
import os
import pwd
import subprocess
from pathlib import Path

import yaml

CONFIG_PATH = Path("/var/lib/solomonprime/calendars.yaml")


def normalize_interactive(value: str) -> tuple[str, str]:
    words = value.strip().lower().replace("_", "-").split()
    if not words:
        return "", ""
    if words[0] in {"authorize", "connect", "enable"} and len(words) == 2:
        return "connect", words[1]
    if words[0] in {"revoke", "disconnect", "disable"} and len(words) == 2:
        return "disconnect", words[1]
    aliases = {
        "google": ("connect", "google"), "m365": ("connect", "m365"),
        "both": ("connect", "both"), "revoke-google": ("disconnect", "google"),
        "revoke-m365": ("disconnect", "m365"), "revoke-all": ("disconnect", "all"),
    }
    return aliases.get(words[0], ("", ""))


def parse_args() -> tuple[str, str]:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action")
    for action, choices in (("connect", ("google", "m365", "both")), ("disconnect", ("google", "m365", "all"))):
        command = sub.add_parser(action)
        command.add_argument("provider", choices=choices)
    args = parser.parse_args()
    if args.action:
        return args.action, args.provider
    entered = input("Connect [google/m365/both] or disconnect [google/m365/all]: ")
    action, provider = normalize_interactive(entered)
    if not action:
        parser.error("unrecognized choice; no calendar configuration was changed")
    return action, provider


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo")
    action, target = parse_args()
    cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    providers = cfg.get("providers") or {}
    if not {"google", "m365"}.issubset(providers):
        raise SystemExit("calendar configuration is missing google or m365 provider sections")
    app_user = subprocess.check_output(
        ["systemctl", "show", "solomonprime", "-p", "User", "--value"], text=True
    ).strip()
    account = pwd.getpwnam(app_user)

    def protect(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chown(path, account.pw_uid, account.pw_gid)
        os.chmod(path, 0o600)

    changed: list[str] = []
    if action == "disconnect":
        selected = ("google", "m365") if target == "all" else (target,)
        for name in selected:
            p = providers[name]
            token_key = "token_file" if name == "google" else "token_cache_file"
            Path(p[token_key]).unlink(missing_ok=True)
            p["enabled"] = False
            changed.append(f"{name}: disconnected")
    else:
        selected = ("google", "m365") if target == "both" else (target,)
        if "google" in selected:
            from google_auth_oauthlib.flow import InstalledAppFlow

            p = providers["google"]
            credentials = Path(p["credentials_file"])
            if not credentials.is_file():
                raise SystemExit(f"Google OAuth client file is missing: {credentials}")
            flow = InstalledAppFlow.from_client_secrets_file(credentials, [p["scope"]])
            print("If controller host is remote, use an SSH port forward for the displayed loopback callback.")
            creds = flow.run_local_server(host="127.0.0.1", port=8766, open_browser=False,
                authorization_prompt_message="Open this URL in your browser:\n{url}")
            token = Path(p["token_file"])
            token.parent.mkdir(parents=True, exist_ok=True)
            token.write_text(creds.to_json())
            protect(token)
            p["enabled"] = True
            changed.append("google: connected read-only")
        if "m365" in selected:
            import msal

            p = providers["m365"]
            if not p.get("client_id"):
                p["client_id"] = input("Microsoft Entra public-client application ID: ").strip()
            if not p.get("client_id"):
                raise SystemExit("M365 client ID is required")
            cache = msal.SerializableTokenCache()
            app = msal.PublicClientApplication(p["client_id"],
                authority=f"https://login.microsoftonline.com/{p.get('tenant', 'organizations')}", token_cache=cache)
            flow = app.initiate_device_flow(scopes=p["scopes"])
            if "user_code" not in flow:
                raise SystemExit(json.dumps(flow))
            print(flow["message"])
            result = app.acquire_token_by_device_flow(flow)
            if "access_token" not in result:
                raise SystemExit(result.get("error_description", "authorization failed"))
            token = Path(p["token_cache_file"])
            token.parent.mkdir(parents=True, exist_ok=True)
            token.write_text(cache.serialize())
            protect(token)
            p["enabled"] = True
            changed.append("m365: connected read-only")

    cfg["enabled"] = any(bool(x.get("enabled")) for x in providers.values())
    CONFIG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False))
    os.chown(CONFIG_PATH, 0, account.pw_gid)
    CONFIG_PATH.chmod(0o640)
    print("Calendar pull configuration updated:")
    for item in changed:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
