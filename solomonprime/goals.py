from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_STATUS = {"draft", "proposed", "active", "paused", "blocked", "achieved", "abandoned", "superseded"}
VALID_PRIORITY = {"critical", "high", "medium", "low", "exploratory"}
VALID_RELATIONS = {"supports", "conflicts_with", "depends_on", "blocks", "duplicates", "replaces", "derived_from", "contributes_to"}


def _json(v: Any) -> str:
    return json.dumps(v if v is not None else {}, sort_keys=True, separators=(",", ":"))


def _load(v: str | None, default: Any) -> Any:
    if not v:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


class GoalStore:
    """Persistent mission/goal store.

    Goals describe outcomes. Jobs and experiments are execution records that can
    reference a goal, but a goal is not considered complete merely because work ran.
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _db(self):
        c = sqlite3.connect(self.path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def _init(self):
        with self._db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS goals(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                outcome TEXT NOT NULL,
                why TEXT,
                owner TEXT,
                status TEXT NOT NULL,
                priority TEXT NOT NULL,
                baseline TEXT,
                target TEXT,
                constraints TEXT,
                success_metrics TEXT,
                success_criteria TEXT,
                stop_criteria TEXT,
                approval_requirements TEXT,
                deadline TEXT,
                metadata TEXT,
                created REAL NOT NULL,
                updated REAL NOT NULL
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS goal_relationships(
                source_goal TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_goal TEXT NOT NULL,
                explanation TEXT,
                created REAL NOT NULL,
                PRIMARY KEY(source_goal, relation, target_goal)
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS goal_events(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id TEXT NOT NULL,
                event TEXT NOT NULL,
                actor TEXT NOT NULL,
                data TEXT,
                created REAL NOT NULL
            )""")

    def _next_id(self) -> str:
        year = datetime.now(timezone.utc).year
        prefix = f"GOAL-{year}-"
        with self._db() as c:
            rows = c.execute("SELECT id FROM goals WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (prefix + "%",)).fetchone()
        n = int(rows[0].split("-")[-1]) + 1 if rows else 1
        return f"{prefix}{n:03d}"

    def create(self, payload: dict[str, Any], *, actor: str = "operator") -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        outcome = str(payload.get("outcome") or "").strip()
        if not name or not outcome:
            raise ValueError("name and outcome are required")
        status = str(payload.get("status") or "active").lower()
        priority = str(payload.get("priority") or "medium").lower()
        if status not in VALID_STATUS:
            raise ValueError(f"invalid goal status: {status}")
        if priority not in VALID_PRIORITY:
            raise ValueError(f"invalid goal priority: {priority}")
        gid = str(payload.get("id") or self._next_id())
        now = time.time()
        row = (
            gid, name, outcome, str(payload.get("why") or ""), str(payload.get("owner") or actor), status, priority,
            _json(payload.get("baseline") or {}), _json(payload.get("target") or {}), _json(payload.get("constraints") or {}),
            _json(payload.get("success_metrics") or []), _json(payload.get("success_criteria") or []), _json(payload.get("stop_criteria") or []),
            _json(payload.get("approval_requirements") or []), str(payload.get("deadline") or ""), _json(payload.get("metadata") or {}), now, now,
        )
        with self._db() as c:
            c.execute("INSERT INTO goals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            c.execute("INSERT INTO goal_events(goal_id,event,actor,data,created) VALUES(?,?,?,?,?)", (gid, "created", actor, _json(payload), now))
        return self.get(gid) or {}

    def get(self, gid: str) -> dict[str, Any] | None:
        with self._db() as c:
            r = c.execute("SELECT * FROM goals WHERE id=?", (gid,)).fetchone()
            rels = c.execute("SELECT relation,target_goal,explanation,created FROM goal_relationships WHERE source_goal=? ORDER BY created", (gid,)).fetchall()
        if not r:
            return None
        d = dict(r)
        for k, default in (("baseline", {}), ("target", {}), ("constraints", {}), ("success_metrics", []), ("success_criteria", []), ("stop_criteria", []), ("approval_requirements", []), ("metadata", {})):
            d[k] = _load(d.get(k), default)
        d["relationships"] = [dict(x) for x in rels]
        return d

    def list(self, *, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 500)
        with self._db() as c:
            if status:
                rows = c.execute("SELECT id FROM goals WHERE status=? ORDER BY updated DESC LIMIT ?", (status, limit)).fetchall()
            else:
                rows = c.execute("SELECT id FROM goals ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
        return [g for r in rows if (g := self.get(r[0]))]

    def update_status(self, gid: str, status: str, *, actor: str = "operator", note: str = "") -> dict[str, Any] | None:
        status = status.lower()
        if status not in VALID_STATUS:
            raise ValueError(f"invalid goal status: {status}")
        now = time.time()
        with self._db() as c:
            cur = c.execute("UPDATE goals SET status=?,updated=? WHERE id=?", (status, now, gid))
            if not cur.rowcount:
                return None
            c.execute("INSERT INTO goal_events(goal_id,event,actor,data,created) VALUES(?,?,?,?,?)", (gid, "status", actor, _json({"status": status, "note": note}), now))
        return self.get(gid)

    def relate(self, source: str, relation: str, target: str, *, explanation: str = "") -> dict[str, Any]:
        if relation not in VALID_RELATIONS:
            raise ValueError(f"invalid relation: {relation}")
        if not self.get(source) or not self.get(target):
            raise ValueError("both source and target goals must exist")
        now = time.time()
        with self._db() as c:
            c.execute("INSERT OR REPLACE INTO goal_relationships VALUES(?,?,?,?,?)", (source, relation, target, explanation, now))
        return {"source_goal": source, "relation": relation, "target_goal": target, "explanation": explanation, "created": now}

    def events(self, gid: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._db() as c:
            rows = c.execute("SELECT * FROM goal_events WHERE goal_id=? ORDER BY seq DESC LIMIT ?", (gid, min(max(limit, 1), 500))).fetchall()
        out = []
        for r in rows:
            d = dict(r); d["data"] = _load(d.get("data"), {})
            out.append(d)
        return out
