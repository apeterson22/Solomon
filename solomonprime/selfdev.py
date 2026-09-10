from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

MAX_READ_BYTES = 256 * 1024
MAX_PATCH_BYTES = 1024 * 1024


class DevelopmentLab:
    """Repository-scoped development proposals; live deployment is out of scope."""

    def __init__(self, config_path: str, db_path: str):
        self.config_path = Path(config_path)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS proposals(
                id TEXT PRIMARY KEY, repository TEXT, title TEXT, patch TEXT, patch_sha256 TEXT,
                state TEXT, actor TEXT, created REAL, updated REAL, evidence TEXT)""")

    def config(self) -> dict[str, Any]:
        try:
            return yaml.safe_load(self.config_path.read_text()) or {}
        except OSError:
            return {}

    def repositories(self) -> list[dict[str, Any]]:
        out = []
        for item in self.config().get("repositories") or []:
            root = Path(str(item.get("path") or ""))
            out.append({
                "id": str(item.get("id") or ""), "path": str(root),
                "present": root.is_dir(), "writable": os.access(root, os.W_OK) if root.is_dir() else False,
                "test_commands": list(item.get("test_commands") or []),
                "live_runtime": bool(item.get("live_runtime", False)),
            })
        return out

    def _repo(self, repo_id: str) -> tuple[dict[str, Any], Path]:
        if self.config().get("enabled") is False:raise ValueError("development is disabled")
        item = next((x for x in self.config().get("repositories") or [] if x.get("id") == repo_id), None)
        if not item:
            raise ValueError("repository is not allowlisted")
        root = Path(str(item.get("path") or "")).resolve()
        if not root.is_dir():
            raise ValueError("repository path is unavailable")
        return item, root

    @staticmethod
    def _sensitive(relative: str) -> bool:
        """Deny common secret and machine-local files even inside an allowlisted repo."""
        path = Path(relative)
        lowered = [part.lower() for part in path.parts]
        name = path.name.lower()
        blocked_parts = {".git", ".ssh", ".gnupg", "secrets", "credentials", "token-cache"}
        blocked_names = {".env", "local.properties", "google-client-secret.json", "m365-client-secret.json"}
        blocked_suffixes = {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"}
        return bool(set(lowered) & blocked_parts) or name in blocked_names or name.startswith((".env.","credentials", "token")) or path.suffix.lower() in blocked_suffixes

    @staticmethod
    def _path(root: Path, relative: str) -> Path:
        if not relative or Path(relative).is_absolute():
            raise ValueError("a relative repository path is required")
        requested = root / relative
        if any((root/Path(*Path(relative).parts[:i])).is_symlink() for i in range(1,len(Path(relative).parts)+1)):
            raise ValueError("symlink paths are not readable")
        resolved = requested.resolve()
        if resolved == root or root not in resolved.parents:
            raise ValueError("path escapes repository")
        return resolved

    def read(self, repo_id: str, relative: str) -> dict[str, Any]:
        _, root = self._repo(repo_id)
        if self._sensitive(relative):
            raise ValueError("secret and machine-local files are not readable")
        path = self._path(root, relative)
        if not path.is_file():
            raise ValueError("file is unavailable")
        size = path.stat().st_size
        if size > MAX_READ_BYTES:
            raise ValueError("file exceeds 256 KiB read limit")
        data = path.read_bytes()
        if b"\x00" in data:
            raise ValueError("binary files are not returned")
        return {"repository": repo_id, "path": relative, "size": size,
                "sha256": hashlib.sha256(data).hexdigest(), "content": data.decode("utf-8", "replace")}

    def search(self, repo_id: str, query: str, limit: int = 100) -> dict[str, Any]:
        _, root = self._repo(repo_id)
        if not query or len(query) > 200:
            raise ValueError("query must contain 1-200 characters")
        rx = re.compile(re.escape(query), re.IGNORECASE)
        matches = []
        ignored = {".git", ".gradle", "build", "node_modules", ".venv", "__pycache__"}
        for path in root.rglob("*"):
            if len(matches) >= min(max(limit, 1), 200):
                break
            if not path.is_file() or path.is_symlink() or any(part in ignored for part in path.parts):
                continue
            if self._sensitive(str(path.relative_to(root))):
                continue
            try:
                if path.stat().st_size > MAX_READ_BYTES:
                    continue
                for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                    if rx.search(line):
                        matches.append({"path": str(path.relative_to(root)), "line": number, "text": line[:500]})
                        if len(matches) >= min(max(limit, 1), 200):
                            break
            except OSError:
                continue
        return {"repository": repo_id, "query": query, "matches": matches, "truncated": len(matches) >= min(max(limit, 1), 200)}

    def propose(self, repo_id: str, title: str, patch: str, actor: str) -> dict[str, Any]:
        self._repo(repo_id)
        encoded = patch.encode()
        if not title.strip() or not patch.strip() or len(encoded) > MAX_PATCH_BYTES:
            raise ValueError("title and a patch no larger than 1 MiB are required")
        if "diff --git " not in patch and not patch.startswith("--- "):
            raise ValueError("proposal must be a unified diff")
        pid = "DEV-" + uuid.uuid4().hex[:16]
        digest = hashlib.sha256(encoded).hexdigest()
        now = time.time()
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?,?)",
                (pid, repo_id, title.strip(), patch, digest, "proposed", actor.strip(), now, now, "{}"))
        return self.get(pid) or {}

    def get(self, proposal_id: str, include_patch: bool = True) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["evidence"] = json.loads(item.get("evidence") or "{}")
        if not include_patch:
            item.pop("patch", None)
        return item

    def list(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as con:
            ids = [x[0] for x in con.execute("SELECT id FROM proposals ORDER BY created DESC LIMIT 100")]
        return [x for pid in ids if (x := self.get(pid, include_patch=False))]

    def validate(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.get(proposal_id)
        if not proposal:
            raise ValueError("proposal not found")
        _, root = self._repo(proposal["repository"])
        self._check_patch_paths(root, proposal["patch"])
        result = subprocess.run(["git", "apply", "--check", "--whitespace=error-all", "-"], cwd=root,
            input=proposal["patch"], text=True, capture_output=True, timeout=30, check=False)
        evidence = {"check_exit_code": result.returncode, "stderr": result.stderr[-4000:],
                    "validated_at": time.time(), "repository_head": self._head(root),
                    "worktree_fingerprint": self._worktree_fingerprint(root)}
        state = "validated" if result.returncode == 0 else "validation_failed"
        self._update(proposal_id, state, evidence)
        return {"proposal_id": proposal_id, "state": state, "evidence": evidence}

    def apply(self, proposal_id: str, expected_sha256: str) -> dict[str, Any]:
        proposal = self.get(proposal_id)
        if not proposal or proposal["state"] != "validated":
            raise ValueError("proposal must be validated immediately before approval")
        if not expected_sha256 or expected_sha256 != proposal["patch_sha256"]:
            raise ValueError("approved patch digest does not match")
        item, root = self._repo(proposal["repository"])
        if item.get("live_runtime"):
            raise ValueError("patches cannot be applied directly to a live runtime repository")
        evidence_before = proposal.get("evidence") or {}
        if evidence_before.get("repository_head") != self._head(root) or evidence_before.get("worktree_fingerprint") != self._worktree_fingerprint(root):
            raise ValueError("development repository changed after validation; revalidate the proposal")
        preflight = subprocess.run(["git", "apply", "--check", "--whitespace=error-all", "-"], cwd=root,
            input=proposal["patch"], text=True, capture_output=True, timeout=30, check=False)
        if preflight.returncode != 0:
            raise ValueError("patch no longer applies cleanly; revalidate the proposal")
        result = subprocess.run(["git", "apply", "--whitespace=error-all", "-"], cwd=root,
            input=proposal["patch"], text=True, capture_output=True, timeout=30, check=False)
        evidence = {**(proposal.get("evidence") or {}), "apply_exit_code": result.returncode,
                    "apply_stderr": result.stderr[-4000:], "applied_at": time.time(), "repository_head": self._head(root)}
        state = "applied_to_development" if result.returncode == 0 else "apply_failed"
        self._update(proposal_id, state, evidence)
        return {"proposal_id": proposal_id, "state": state, "evidence": evidence,
                "promotion_required": result.returncode == 0}

    def test(self, repo_id: str) -> dict[str, Any]:
        raise ValueError("Tests must run through the isolated maintenance build job")

    @classmethod
    def _check_patch_paths(cls, root: Path, patch: str) -> None:
        if "120000" in patch or "160000" in patch:
            raise ValueError("symlink/submodule patch modes are not allowed")
        result=subprocess.run(["git","apply","--numstat","-z","-"],cwd=root,input=patch.encode(),capture_output=True,timeout=20)
        if result.returncode:raise ValueError("patch cannot be parsed")
        for entry in result.stdout.split(b"\0"):
            if not entry:continue
            fields=entry.split(b"\t",2)
            if len(fields)!=3:raise ValueError("unsupported patch path encoding")
            name=os.fsdecode(fields[2])
            if cls._sensitive(name):raise ValueError("patch touches protected repository metadata or secrets")
            cls._path(root,name)

    def _update(self, proposal_id: str, state: str, evidence: dict[str, Any]) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute("UPDATE proposals SET state=?,updated=?,evidence=? WHERE id=?",
                (state, time.time(), json.dumps(evidence), proposal_id))

    @staticmethod
    def _head(root: Path) -> str:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True,
            capture_output=True, timeout=10, check=False)
        return result.stdout.strip() if result.returncode == 0 else "unversioned"

    @staticmethod
    def _worktree_fingerprint(root: Path) -> str:
        result=subprocess.run(["git","-c","core.fsmonitor=false","ls-files","--cached","--others","--exclude-standard","-z"],cwd=root,capture_output=True,timeout=20,check=False)
        if result.returncode:raise ValueError("cannot fingerprint repository")
        digest=hashlib.sha256()
        for name in sorted(set(x for x in result.stdout.split(b"\0") if x)):
            relative=os.fsdecode(name);path=root/relative
            digest.update(name+b"\0")
            if path.is_symlink():digest.update(b"symlink:"+os.fsencode(os.readlink(path)));continue
            if not path.exists():digest.update(b"deleted");continue
            if path.is_file():
                digest.update(str(path.stat().st_mode & 0o777).encode()+b"\0")
                with path.open('rb') as handle:
                    for chunk in iter(lambda:handle.read(1024*1024),b''):digest.update(chunk)
        return digest.hexdigest()
