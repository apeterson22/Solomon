from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_STATUS = {"draft", "planned", "queued", "running", "completed", "failed", "cancelled", "inconclusive"}


def _canon(v: Any) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str).encode()


def _load(v: str | None, default: Any) -> Any:
    try:
        return json.loads(v) if v else default
    except Exception:
        return default


class ExperimentLedger:
    def __init__(self, path: str, artifact_root: str):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root = Path(artifact_root); self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._init()

    def _db(self):
        c = sqlite3.connect(self.path, check_same_thread=False); c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init(self):
        with self._db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS experiments(
              id TEXT PRIMARY KEY, goal_id TEXT, title TEXT NOT NULL, hypothesis TEXT, status TEXT NOT NULL,
              manifest TEXT NOT NULL, manifest_hash TEXT NOT NULL, selected_node TEXT, job_id TEXT,
              metrics TEXT, result TEXT, artifacts TEXT, conclusion TEXT, recommendation TEXT,
              created REAL NOT NULL, started REAL, finished REAL, updated REAL NOT NULL
            )""")

    def _next_id(self) -> str:
        year = datetime.now(timezone.utc).year; prefix = f"EXP-{year}-"
        with self._db() as c:r = c.execute("SELECT id FROM experiments WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (prefix+"%",)).fetchone()
        n = int(r[0].split("-")[-1]) + 1 if r else 1
        return f"{prefix}{n:03d}"

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        if not title: raise ValueError("title is required")
        eid = str(payload.get("id") or self._next_id())
        status = str(payload.get("status") or "planned").lower()
        if status not in VALID_STATUS: raise ValueError(f"invalid experiment status: {status}")
        manifest = {
            "goal_id": str(payload.get("goal_id") or ""),
            "title": title,
            "hypothesis": str(payload.get("hypothesis") or ""),
            "independent_variable": payload.get("independent_variable"),
            "controlled_variables": payload.get("controlled_variables") or [],
            "environment": payload.get("environment") or {},
            "metrics": payload.get("metrics") or [],
            "success_threshold": payload.get("success_threshold") or {},
            "resource_budget": payload.get("resource_budget") or {},
            "metadata": payload.get("metadata") or {},
        }
        mh = hashlib.sha256(_canon(manifest)).hexdigest(); now = time.time()
        with self._db() as c:
            c.execute("INSERT INTO experiments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                eid, manifest["goal_id"], title, manifest["hypothesis"], status, json.dumps(manifest), mh, "", "",
                "{}", "{}", "[]", "", "", now, None, None, now,
            ))
        return self.get(eid) or {}

    def get(self, eid: str) -> dict[str, Any] | None:
        with self._db() as c:r = c.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
        if not r:return None
        d = dict(r)
        for k, default in (("manifest", {}), ("metrics", {}), ("result", {}), ("artifacts", [])):
            d[k] = _load(d.get(k), default)
        return d

    def list(self, *, goal_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        limit = min(max(limit, 1), 500)
        with self._db() as c:
            if goal_id: rows = c.execute("SELECT id FROM experiments WHERE goal_id=? ORDER BY created DESC LIMIT ?", (goal_id, limit)).fetchall()
            else: rows = c.execute("SELECT id FROM experiments ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [e for r in rows if (e := self.get(r[0]))]

    def bind_job(self, eid: str, *, job_id: str, node_id: str) -> None:
        with self._db() as c:
            c.execute("UPDATE experiments SET job_id=?,selected_node=?,status='queued',updated=? WHERE id=?", (job_id, node_id, time.time(), eid))

    def update_from_job(self, eid: str, job: dict[str, Any]) -> dict[str, Any] | None:
        if not eid or not self.get(eid): return None
        status = str(job.get("status") or "")
        mapped = {"queued":"queued", "running":"running", "completed":"completed", "failed":"failed", "cancelled":"cancelled"}.get(status)
        if not mapped:return self.get(eid)
        now = time.time(); started = job.get("started") or None; finished = job.get("finished") or None
        result = job.get("result") or {}; artifacts = result.get("artifacts") or []
        metrics = result.get("metrics") or {}
        with self._db() as c:
            c.execute("""UPDATE experiments SET status=?,started=COALESCE(started,?),finished=COALESCE(?,finished),
              metrics=?,result=?,artifacts=?,updated=? WHERE id=?""",
              (mapped, started, finished, json.dumps(metrics), json.dumps(result), json.dumps(artifacts), now, eid))
        return self.get(eid)
