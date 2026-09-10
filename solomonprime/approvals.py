from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

RISK_ORDER = {"read_only": 0, "reversible": 1, "mutating": 2, "destructive": 3, "critical": 4}


class ApprovalStore:
    def __init__(self, path: str):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self._init()

    def _db(self):
        con = sqlite3.connect(self.path, check_same_thread=False); con.row_factory = sqlite3.Row; con.execute("PRAGMA journal_mode=WAL"); return con

    def _init(self):
        with self._db() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS approvals(
                id TEXT PRIMARY KEY, plan_hash TEXT, risk TEXT, actor TEXT, action TEXT, payload TEXT,
                state TEXT, created REAL, approved REAL, approved_by TEXT, note TEXT)""")

    @staticmethod
    def plan_hash(action: str, payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps({"action": action, "payload": payload}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def request(self, *, actor: str, action: str, payload: dict[str, Any], risk: str) -> dict[str, Any]:
        if risk not in RISK_ORDER: raise ValueError(risk)
        aid = str(uuid.uuid4()); ph = self.plan_hash(action, payload); now = time.time()
        with self._db() as con:
            con.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?,?,?)", (aid, ph, risk, actor, action, json.dumps(payload), "pending", now, 0.0, "", ""))
        return {"id": aid, "plan_hash": ph, "risk": risk, "actor": actor, "action": action, "payload": payload, "state": "pending"}

    def approve(self, aid: str, *, by: str, note: str = "") -> bool:
        with self._db() as con:
            cur = con.execute("UPDATE approvals SET state='approved',approved=?,approved_by=?,note=? WHERE id=? AND state='pending'", (time.time(), by, note, aid))
            return cur.rowcount == 1

    def get(self, aid: str) -> dict[str, Any] | None:
        with self._db() as con:
            r = con.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
        if not r: return None
        d = dict(r); d["payload"] = json.loads(d["payload"] or "{}"); return d

    def list_pending(self) -> list[dict[str, Any]]:
        with self._db() as con:
            rows = con.execute("SELECT * FROM approvals WHERE state='pending' ORDER BY created").fetchall()
        out=[]
        for r in rows:
            d=dict(r); d["payload"]=json.loads(d["payload"] or "{}"); out.append(d)
        return out

    def find_approved(self, *, action: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        ph = self.plan_hash(action, payload)
        with self._db() as con:
            row = con.execute(
                "SELECT id FROM approvals WHERE action=? AND plan_hash=? AND state='approved' ORDER BY approved DESC LIMIT 1",
                (action, ph),
            ).fetchone()
        return self.get(row[0]) if row else None

    def consume(self, aid: str, *, action: str, payload: dict[str, Any], max_age: int = 3600) -> bool:
        """Atomically spend one matching approval; failure never grants authority."""
        with self._db() as con:
            changed = con.execute(
                "UPDATE approvals SET state='consumed' WHERE id=? AND action=? AND plan_hash=? AND state='approved' AND approved>=?",
                (aid, action, self.plan_hash(action, payload), time.time()-max_age))
            return changed.rowcount == 1
