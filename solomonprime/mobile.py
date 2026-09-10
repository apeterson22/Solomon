from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any


class MobileAccess:
    """Revocable, hashed, scope-limited mobile bearer credentials."""

    ALLOWED_SCOPES = {"chat", "models", "audio", "voice"}

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS mobile_devices(
                id TEXT PRIMARY KEY, label TEXT, token_hash TEXT UNIQUE, scopes TEXT,
                created REAL, last_used REAL, revoked REAL DEFAULT 0)""")

    def _db(self):
        con = sqlite3.connect(self.path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        return con

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def issue(self, device_id: str, label: str, scopes: list[str] | None = None) -> dict[str, Any]:
        device_id = device_id.strip()
        if not device_id or len(device_id) > 120:
            raise ValueError("device_id must contain 1-120 characters")
        chosen = sorted(set(scopes or self.ALLOWED_SCOPES))
        if not chosen or not set(chosen).issubset(self.ALLOWED_SCOPES):
            raise ValueError("invalid mobile scope")
        token = "spm_" + secrets.token_urlsafe(32)
        now = time.time()
        with self._db() as con:
            con.execute("UPDATE mobile_devices SET revoked=? WHERE id=? AND revoked=0", (now, device_id))
            con.execute("INSERT OR REPLACE INTO mobile_devices VALUES(?,?,?,?,?,?,0)",
                (device_id, label.strip()[:120], self._hash(token), json.dumps(chosen), now, 0.0))
        return {"device_id": device_id, "label": label.strip()[:120], "token": token,
                "scopes": chosen, "created": now, "display_once": True}

    def authorize(self, token: str, scope: str) -> bool:
        if not token.startswith("spm_") or scope not in self.ALLOWED_SCOPES:
            return False
        digest = self._hash(token)
        with self._db() as con:
            rows = con.execute("SELECT id,token_hash,scopes FROM mobile_devices WHERE revoked=0").fetchall()
            for row in rows:
                if hmac.compare_digest(row["token_hash"], digest) and scope in json.loads(row["scopes"]):
                    con.execute("UPDATE mobile_devices SET last_used=? WHERE id=?", (time.time(), row["id"]))
                    return True
        return False

    def revoke(self, device_id: str) -> bool:
        with self._db() as con:
            return con.execute("UPDATE mobile_devices SET revoked=? WHERE id=? AND revoked=0",
                (time.time(), device_id)).rowcount == 1

    def list(self) -> list[dict[str, Any]]:
        with self._db() as con:
            rows = con.execute("SELECT id,label,scopes,created,last_used,revoked FROM mobile_devices ORDER BY created DESC").fetchall()
        return [{**dict(row), "scopes": json.loads(row["scopes"]), "state": "revoked" if row["revoked"] else "active"} for row in rows]
