#!/usr/bin/env python3
"""Root-side, socket-activated privilege boundary for bounded jobs.

The network-facing SolomonPrime daemon remains under NoNewPrivileges.  This
broker accepts one request over a root-owned AF_UNIX socket, authenticates the
peer, independently validates the on-disk manifest, and only then invokes the
root-owned sandbox runner.
"""
from __future__ import annotations

import hashlib
import grp
import json
import os
import re
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("SOLOMON_JOB_ROOT", "/apps/solomonprime-jobs")).resolve()
RUNNER = Path(os.environ.get("SOLOMON_JOB_RUNNER", "/usr/local/libexec/solomon-job-runner"))
ALLOWED_KINDS = {"python", "blender", "openscad"}
ALLOWED_RISKS = {"read_only", "reversible"}
JOB_RE = re.compile(r"^JOB-[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
MAX_REQUEST = 16 * 1024
MAX_MANIFEST = 2 * 1024 * 1024
MAX_SOURCE = 1024 * 1024
MAX_RESPONSE = 4 * 1024 * 1024


class BrokerReject(ValueError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _bounded_number(value: Any, name: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise BrokerReject(f"{name} must be numeric") from None
    if not low <= number <= high:
        raise BrokerReject(f"{name} is outside the allowed range")
    return number


def _regular_owned_file(path: Path, owner_uid: int, max_bytes: int) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise BrokerReject(f"missing file: {path.name}") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise BrokerReject(f"{path.name} must be a regular non-symlink file")
    if info.st_uid != owner_uid:
        raise BrokerReject(f"{path.name} has an unexpected owner")
    if info.st_mode & stat.S_IWOTH:
        raise BrokerReject(f"{path.name} must not be world-writable")
    if info.st_size > max_bytes:
        raise BrokerReject(f"{path.name} exceeds its size limit")
    return info


def validate_request(request: dict[str, Any], allowed_uid: int) -> tuple[Path, int, Path]:
    raw_path = request.get("manifest_path")
    expected_hash = str(request.get("manifest_sha256") or "")
    if not isinstance(raw_path, str) or not raw_path:
        raise BrokerReject("manifest_path is required")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise BrokerReject("manifest_sha256 is invalid")

    requested = Path(raw_path)
    if requested.name != "manifest.json" or not requested.is_absolute():
        raise BrokerReject("invalid manifest path")
    workspace = requested.parent
    if not JOB_RE.fullmatch(workspace.name):
        raise BrokerReject("invalid job workspace name")
    if workspace.parent.resolve() != ROOT:
        raise BrokerReject("manifest is outside the job root")
    try:
        workspace_info = workspace.lstat()
    except FileNotFoundError:
        raise BrokerReject("job workspace does not exist") from None
    if stat.S_ISLNK(workspace_info.st_mode) or not stat.S_ISDIR(workspace_info.st_mode):
        raise BrokerReject("job workspace must be a non-symlink directory")
    if workspace_info.st_uid != allowed_uid:
        raise BrokerReject("job workspace has an unexpected owner")
    if workspace_info.st_mode & stat.S_IWOTH:
        raise BrokerReject("job workspace must not be world-writable")

    manifest_path = workspace / "manifest.json"
    _regular_owned_file(manifest_path, allowed_uid, MAX_MANIFEST)
    if _sha256(manifest_path) != expected_hash:
        raise BrokerReject("manifest hash mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise BrokerReject(f"invalid manifest JSON: {exc}") from None
    if not isinstance(manifest, dict):
        raise BrokerReject("manifest must be a JSON object")
    if manifest.get("workspace") != str(workspace):
        raise BrokerReject("workspace mismatch")
    if manifest.get("job_id") != workspace.name:
        raise BrokerReject("job_id does not match workspace")
    if str(manifest.get("kind") or "").lower() not in ALLOWED_KINDS:
        raise BrokerReject("unsupported job kind")
    if str(manifest.get("risk") or "reversible").lower() not in ALLOWED_RISKS:
        raise BrokerReject("job risk requires approval")
    if not isinstance(manifest.get("allow_network", False), bool):
        raise BrokerReject("allow_network must be boolean")

    source_name = manifest.get("source_file")
    if not isinstance(source_name, str) or Path(source_name).name != source_name:
        raise BrokerReject("invalid source_file")
    source_path = workspace / source_name
    _regular_owned_file(source_path, allowed_uid, MAX_SOURCE)
    source_hash = str(manifest.get("source_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", source_hash) or _sha256(source_path) != source_hash:
        raise BrokerReject("source hash mismatch")

    resources = manifest.get("resources") or {}
    if not isinstance(resources, dict):
        raise BrokerReject("resources must be an object")
    runtime = int(_bounded_number(resources.get("max_runtime_seconds", 900), "max_runtime_seconds", 1, 86400))
    _bounded_number(resources.get("max_memory_gb", 4), "max_memory_gb", 0.25, 256)
    _bounded_number(resources.get("max_cpu_cores", 2), "max_cpu_cores", 0.1, 64)
    _bounded_number(resources.get("max_disk_gb", 4), "max_disk_gb", 0.1, 512)
    return manifest_path, runtime, source_path


def _peer_uid() -> int:
    conn = socket.fromfd(0, socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", raw)
        return uid
    finally:
        conn.close()


def _validate_runner() -> None:
    try:
        info = RUNNER.lstat()
    except FileNotFoundError:
        raise BrokerReject("sandbox runner is not installed") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise BrokerReject("sandbox runner must be a regular non-symlink file")
    if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise BrokerReject("sandbox runner ownership or permissions are unsafe")


def _job_group_id() -> int:
    configured = os.environ.get("SOLOMON_JOB_GROUP_GID")
    return int(configured) if configured is not None else grp.getgrnam("solomonprime").gr_gid


def _freeze_workspace(manifest_path: Path, source: Path) -> None:
    """Remove the submitting service's write access after validation."""
    workspace = manifest_path.parent
    group_id = _job_group_id()
    # Freeze the directory first so path entries cannot be replaced, then take
    # ownership of both validated files. Hashes are checked again afterward.
    os.chown(workspace, 0, group_id, follow_symlinks=False)
    workspace.chmod(0o750)
    for item in (manifest_path, source):
        os.chown(item, 0, group_id, follow_symlinks=False)
        item.chmod(0o640)


def _read_nofollow(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        data = b""
        while len(data) <= limit:
            block = os.read(descriptor, min(1024 * 1024, limit + 1 - len(data)))
            if not block:
                break
            data += block
    finally:
        os.close(descriptor)
    if len(data) > limit:
        raise BrokerReject(f"{path.name} exceeds its size limit")
    return data


def _sealed_replace(path: Path, data: bytes, group_id: int) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".broker-seal-", dir=path.parent)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.fchown(descriptor, 0, group_id)
        os.fchmod(descriptor, 0o640)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _seal_verified_files(manifest_path: Path, source: Path, expected_manifest_hash: str) -> None:
    """Replace mutable input inodes with verified root-owned copies."""
    manifest_bytes = _read_nofollow(manifest_path, MAX_MANIFEST)
    source_bytes = _read_nofollow(source, MAX_SOURCE)
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_hash:
        raise BrokerReject("manifest changed during validation")
    manifest = json.loads(manifest_bytes)
    if manifest.get("source_file") != source.name:
        raise BrokerReject("source path changed during validation")
    if hashlib.sha256(source_bytes).hexdigest() != manifest.get("source_sha256"):
        raise BrokerReject("source changed during validation")
    group_id = _job_group_id()
    _sealed_replace(source, source_bytes, group_id)
    _sealed_replace(manifest_path, manifest_bytes, group_id)


def _thaw_workspace(workspace: Path, allowed_uid: int) -> None:
    """Return completed output to the service user without following links."""
    group_id = _job_group_id()
    for item in workspace.rglob("*"):
        try:
            os.chown(item, allowed_uid, group_id, follow_symlinks=False)
        except OSError:
            continue
    os.chown(workspace, allowed_uid, group_id, follow_symlinks=False)
    workspace.chmod(0o770)


def main() -> int:
    response: dict[str, Any]
    peer_uid = -1
    job_id = ""
    workspace: Path | None = None
    allowed_uid = -1
    try:
        if os.geteuid() != 0:
            raise BrokerReject("broker must run as root")
        allowed_uid = int(os.environ["SOLOMON_JOB_CLIENT_UID"])
        peer_uid = _peer_uid()
        if peer_uid not in {0, allowed_uid}:
            raise BrokerReject("peer uid is not authorized")
        line = sys.stdin.buffer.readline(MAX_REQUEST + 1)
        if not line or len(line) > MAX_REQUEST:
            raise BrokerReject("invalid broker request size")
        request = json.loads(line)
        if not isinstance(request, dict):
            raise BrokerReject("broker request must be an object")
        manifest_path, runtime, source_path = validate_request(request, allowed_uid)
        job_id = manifest_path.parent.name
        workspace = manifest_path.parent
        _validate_runner()
        _freeze_workspace(manifest_path, source_path)
        _seal_verified_files(manifest_path, source_path, request["manifest_sha256"])
        print(json.dumps({"event":"broker.accept","job_id":job_id,"peer_uid":peer_uid,"manifest_sha256":request["manifest_sha256"],"ts":time.time()},separators=(",",":")),file=sys.stderr)
        proc = subprocess.run(
            [str(RUNNER), str(manifest_path)],
            text=True,
            capture_output=True,
            timeout=runtime + 90,
        )
        response = {
            "ok": True,
            "exit_code": proc.returncode,
            "stdout": (proc.stdout or "")[-1024 * 1024 :],
            "stderr": (proc.stderr or "")[-1024 * 1024 :],
        }
        print(json.dumps({"event":"broker.complete","job_id":job_id,"peer_uid":peer_uid,"exit_code":proc.returncode,"ts":time.time()},separators=(",",":")),file=sys.stderr)
    except subprocess.TimeoutExpired:
        response = {"ok": False, "exit_code": 124, "error": "sandbox runner timed out"}
    except (BrokerReject, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"event":"broker.reject","job_id":job_id,"peer_uid":peer_uid,"reason":str(exc)[:300],"ts":time.time()},separators=(",",":")),file=sys.stderr)
        response = {"ok": False, "exit_code": 125, "error": str(exc)}
    except Exception as exc:
        print(f"[SOLOMON-BROKER] internal error: {type(exc).__name__}", file=sys.stderr)
        response = {"ok": False, "exit_code": 125, "error": "internal broker error"}

    if workspace is not None and allowed_uid >= 0:
        try:
            _thaw_workspace(workspace, allowed_uid)
        except Exception as exc:
            print(f"[SOLOMON-BROKER] workspace thaw failed: {type(exc).__name__}", file=sys.stderr)
            response = {"ok": False, "exit_code": 125, "error": "workspace ownership restore failed"}

    encoded = (json.dumps(response, separators=(",", ":")) + "\n").encode()
    if len(encoded) > MAX_RESPONSE:
        encoded = b'{"ok":false,"exit_code":125,"error":"broker response exceeded limit"}\n'
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
