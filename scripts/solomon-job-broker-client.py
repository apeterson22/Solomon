#!/usr/bin/env python3
"""Unprivileged client for the SolomonPrime root job broker."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
from pathlib import Path

SOCKET_PATH = os.environ.get("SOLOMON_JOB_BROKER_SOCKET", "/run/solomonprime/job-broker.sock")
MAX_RESPONSE = 4 * 1024 * 1024


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fail(message: str, code: int = 125) -> int:
    print(f"[SOLOMON-BROKER-CLIENT][ERROR] {message}", file=sys.stderr)
    return code


def main() -> int:
    if len(sys.argv) != 2:
        return fail("usage: solomon-job-broker-client /apps/solomonprime-jobs/JOB-.../manifest.json")
    manifest = Path(sys.argv[1])
    if not manifest.is_absolute() or manifest.name != "manifest.json" or not manifest.is_file():
        return fail("invalid manifest path")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        runtime = min(max(int((data.get("resources") or {}).get("max_runtime_seconds") or 900), 1), 86400)
        request = {
            "manifest_path": str(manifest),
            "manifest_sha256": sha256(manifest),
        }
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(runtime + 90)
            conn.connect(SOCKET_PATH)
            conn.sendall((json.dumps(request, separators=(",", ":")) + "\n").encode())
            conn.shutdown(socket.SHUT_WR)
            chunks = []
            total = 0
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESPONSE:
                    return fail("broker response exceeded limit")
                chunks.append(chunk)
        response = json.loads(b"".join(chunks) or b"{}")
    except Exception as exc:
        return fail(f"broker request failed: {type(exc).__name__}: {exc}")

    if not response.get("ok"):
        return fail(str(response.get("error") or "broker rejected job"), int(response.get("exit_code") or 125))
    if response.get("stdout"):
        print(str(response["stdout"]), end="")
    if response.get("stderr"):
        print(str(response["stderr"]), end="", file=sys.stderr)
    code = int(response.get("exit_code") or 0)
    return code if 0 <= code <= 255 else 125


if __name__ == "__main__":
    raise SystemExit(main())
