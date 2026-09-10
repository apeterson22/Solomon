from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

_WORD = re.compile(r"[A-Za-z0-9_./:-]+")
_NEG = {"not", "never", "no", "disabled", "false", "without", "cannot", "won't"}
_STATES = {"draft", "review", "approved", "rejected", "retired"}
_KINDS = {"fact", "standard", "sop", "decision", "note", "proposal", "reference"}


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _hash_vector(text: str, dimensions: int = 384) -> dict[int, float]:
    """Dependency-free, deterministic sparse feature vector.

    This is deliberately identified as feature_hash_v1 rather than claiming a
    neural semantic model. It provides an offline vector signal and a stable
    fallback until an operator approves a production embedding provider.
    """
    out: dict[int, float] = {}
    tokens = _tokens(text)
    features = tokens + [f"{a}::{b}" for a, b in zip(tokens, tokens[1:])]
    for feature in features:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        idx = value % dimensions
        out[idx] = out.get(idx, 0.0) + (-1.0 if value & 1 else 1.0)
    norm = math.sqrt(sum(v * v for v in out.values())) or 1.0
    return {k: v / norm for k, v in out.items()}


def _cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(value * b.get(idx, 0.0) for idx, value in a.items())


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class KnowledgeStore:
    """Governed knowledge ledger with hybrid retrieval and provenance."""

    def __init__(self, path: str, *, vector_backend: str = "feature_hash_v1"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.vector_backend = vector_backend
        self._init()

    def _db(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init(self):
        with self._db() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
              kind TEXT NOT NULL, state TEXT NOT NULL, domain TEXT NOT NULL,
              canonical_key TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
              content_hash TEXT NOT NULL, vector_json TEXT NOT NULL,
              source_uri TEXT NOT NULL DEFAULT '', source_type TEXT NOT NULL DEFAULT 'operator',
              source_hash TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '',
              confidence REAL NOT NULL DEFAULT .8, importance REAL NOT NULL DEFAULT .5,
              tags_json TEXT NOT NULL DEFAULT '[]', supersedes TEXT NOT NULL DEFAULT '',
              approved_by TEXT NOT NULL DEFAULT '', approved_at REAL NOT NULL DEFAULT 0,
              created REAL NOT NULL, updated REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_knowledge_state ON knowledge(state,domain,updated);
            CREATE INDEX IF NOT EXISTS idx_knowledge_key ON knowledge(canonical_key,state);
            CREATE TABLE IF NOT EXISTS knowledge_events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, knowledge_id TEXT NOT NULL,
              event TEXT NOT NULL, actor TEXT NOT NULL, data_json TEXT NOT NULL,
              created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contradictions(
              id TEXT PRIMARY KEY, left_id TEXT NOT NULL, right_id TEXT NOT NULL,
              reason TEXT NOT NULL, score REAL NOT NULL, state TEXT NOT NULL DEFAULT 'open',
              resolution TEXT NOT NULL DEFAULT '', resolved_by TEXT NOT NULL DEFAULT '',
              created REAL NOT NULL, updated REAL NOT NULL,
              UNIQUE(left_id,right_id,reason)
            );
            CREATE TABLE IF NOT EXISTS retrieval_evaluations(
              id TEXT PRIMARY KEY, name TEXT NOT NULL, baseline_json TEXT NOT NULL,
              candidate_json TEXT NOT NULL, promoted INTEGER NOT NULL DEFAULT 0,
              approved_by TEXT NOT NULL DEFAULT '', created REAL NOT NULL
            );
            """)
            try:
                c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(title,content,tags,content='knowledge',content_rowid='rowid')")
                c.executescript("""
                CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
                  INSERT INTO knowledge_fts(rowid,title,content,tags) VALUES(new.rowid,new.title,new.content,new.tags_json);
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
                  INSERT INTO knowledge_fts(knowledge_fts,rowid,title,content,tags) VALUES('delete',old.rowid,old.title,old.content,old.tags_json);
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
                  INSERT INTO knowledge_fts(knowledge_fts,rowid,title,content,tags) VALUES('delete',old.rowid,old.title,old.content,old.tags_json);
                  INSERT INTO knowledge_fts(rowid,title,content,tags) VALUES(new.rowid,new.title,new.content,new.tags_json);
                END;
                """)
            except sqlite3.OperationalError:
                pass

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(row)
        for source, target in (("tags_json", "tags"),):
            try: out[target] = json.loads(out.pop(source))
            except Exception: out[target] = []
        out.pop("vector_json", None)
        return out

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        content = str(payload.get("content") or "").strip()
        if not title or not content:
            raise ValueError("title and content are required")
        kind = str(payload.get("kind") or "note")
        if kind not in _KINDS:
            raise ValueError(f"kind must be one of {sorted(_KINDS)}")
        requested_state = str(payload.get("state") or "draft")
        if requested_state not in {"draft", "review"}:
            raise ValueError("new knowledge can only start as draft or review")
        now = time.time()
        kid = str(payload.get("id") or f"KN-{time.strftime('%Y%m%d', time.gmtime(now))}-{uuid.uuid4().hex[:10]}")
        tags = sorted({str(x).strip() for x in payload.get("tags", []) if str(x).strip()})
        source_uri = str(payload.get("source_uri") or "")
        source_hash = str(payload.get("source_hash") or "")
        if source_uri and not source_hash:
            source_hash = hashlib.sha256(source_uri.encode()).hexdigest()
        digest = hashlib.sha256(content.encode()).hexdigest()
        vector = _hash_vector(title + "\n" + content)
        supersedes = str(payload.get("supersedes") or "")
        version = 1
        canonical_key = str(payload.get("canonical_key") or "")
        with self._db() as c:
            if supersedes:
                previous = c.execute("SELECT * FROM knowledge WHERE id=?", (supersedes,)).fetchone()
                if not previous:
                    raise ValueError("supersedes record does not exist")
                version = int(previous["version"]) + 1
                canonical_key = canonical_key or str(previous["canonical_key"])
            duplicate = c.execute("SELECT id,state FROM knowledge WHERE content_hash=? AND state!='retired'", (digest,)).fetchone()
            if duplicate:
                return {"inserted": False, "deduplicated": True, "id": duplicate["id"], "state": duplicate["state"]}
            c.execute("""INSERT INTO knowledge(id,title,content,kind,state,domain,canonical_key,version,content_hash,vector_json,
                source_uri,source_type,source_hash,author,confidence,importance,tags_json,supersedes,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                kid, title, content, kind, requested_state, str(payload.get("domain") or "general"),
                canonical_key, version, digest, _json(vector), source_uri,
                str(payload.get("source_type") or "operator"), source_hash, str(payload.get("author") or "operator"),
                max(0.0, min(1.0, float(payload.get("confidence", .8)))),
                max(0.0, min(1.0, float(payload.get("importance", .5)))), _json(tags),
                supersedes, now, now))
            c.execute("INSERT INTO knowledge_events(knowledge_id,event,actor,data_json,created) VALUES(?,?,?,?,?)",
                      (kid, "created", str(payload.get("author") or "operator"), _json({"state": requested_state}), now))
        self.detect_contradictions(kid)
        return {**(self.get(kid) or {}), "inserted": True}

    def get(self, kid: str) -> dict[str, Any] | None:
        with self._db() as c:
            return self._row(c.execute("SELECT * FROM knowledge WHERE id=?", (kid,)).fetchone())

    def list(self, *, state: str = "", domain: str = "", limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM knowledge WHERE 1=1"; args: list[Any] = []
        if state: sql += " AND state=?"; args.append(state)
        if domain: sql += " AND domain=?"; args.append(domain)
        sql += " ORDER BY updated DESC LIMIT ?"; args.append(max(1, min(limit, 500)))
        with self._db() as c:
            return [self._row(r) for r in c.execute(sql, args).fetchall()]

    def transition(self, kid: str, state: str, *, actor: str, note: str = "") -> dict[str, Any] | None:
        if state not in _STATES:
            raise ValueError(f"state must be one of {sorted(_STATES)}")
        allowed = {"draft": {"review", "retired"}, "review": {"draft", "approved", "rejected"},
                   "approved": {"retired"}, "rejected": {"draft", "retired"}, "retired": set()}
        with self._db() as c:
            row = c.execute("SELECT * FROM knowledge WHERE id=?", (kid,)).fetchone()
            if not row: return None
            if state not in allowed.get(row["state"], set()):
                raise ValueError(f"invalid transition {row['state']} -> {state}")
            if state == "approved" and not actor.strip():
                raise ValueError("approved knowledge requires an identified human reviewer")
            now = time.time()
            approved_by, approved_at = (actor, now) if state == "approved" else (row["approved_by"], row["approved_at"])
            c.execute("UPDATE knowledge SET state=?,approved_by=?,approved_at=?,updated=? WHERE id=?",
                      (state, approved_by, approved_at, now, kid))
            c.execute("INSERT INTO knowledge_events(knowledge_id,event,actor,data_json,created) VALUES(?,?,?,?,?)",
                      (kid, "state_changed", actor, _json({"from": row["state"], "to": state, "note": note}), now))
            if state == "approved" and row["supersedes"]:
                prior = c.execute("SELECT state FROM knowledge WHERE id=?", (row["supersedes"],)).fetchone()
                if prior and prior["state"] == "approved":
                    c.execute("UPDATE knowledge SET state='retired',updated=? WHERE id=?", (now, row["supersedes"]))
                    c.execute("INSERT INTO knowledge_events(knowledge_id,event,actor,data_json,created) VALUES(?,?,?,?,?)",
                              (row["supersedes"], "superseded", actor, _json({"by": kid}), now))
        return self.get(kid)

    def search(self, query: str, *, domain: str = "", limit: int = 8,
               states: tuple[str, ...] = ("approved",), mode: str = "hybrid") -> list[dict[str, Any]]:
        query = query.strip()
        if not query: return []
        if mode not in {"hybrid", "lexical"}: raise ValueError("mode must be hybrid or lexical")
        qvec = _hash_vector(query)
        with self._db() as c:
            placeholders = ",".join("?" for _ in states)
            sql = f"SELECT rowid,* FROM knowledge WHERE state IN ({placeholders})"
            args: list[Any] = list(states)
            if domain: sql += " AND (domain=? OR domain='general')"; args.append(domain)
            rows = c.execute(sql + " ORDER BY updated DESC LIMIT 1000", args).fetchall()
            lexical: dict[str, float] = {}
            try:
                # FTS5 MATCH has its own query grammar. Only emit plain word
                # tokens so punctuation such as the dot in "v0.4" cannot turn
                # a normal operator query into invalid MATCH syntax.
                terms = " OR ".join(re.findall(r"[A-Za-z0-9_]+", query)[:16])
                if terms:
                    for r in c.execute("SELECT k.id,bm25(knowledge_fts) bm FROM knowledge_fts JOIN knowledge k ON k.rowid=knowledge_fts.rowid WHERE knowledge_fts MATCH ?", (terms,)).fetchall():
                        lexical[r["id"]] = 1.0 / (1.0 + max(0.0, float(r["bm"]) + 10.0)) if float(r["bm"]) >= 0 else 1.0 / (1.0 + abs(float(r["bm"])))
            except sqlite3.OperationalError:
                pass
        scored = []
        for row in rows:
            raw = dict(row)
            try: vec = {int(k): float(v) for k, v in json.loads(raw["vector_json"]).items()}
            except Exception: vec = _hash_vector(raw["title"] + "\n" + raw["content"])
            vector_score = max(0.0, _cosine(qvec, vec))
            lex = lexical.get(raw["id"], 0.0)
            scope = .05 if domain and raw["domain"] == domain else 0.0
            score = ((.55 * lex + .30 * vector_score) if mode == "hybrid" else (.85 * lex)) + .06 * raw["confidence"] + .04 * raw["importance"] + scope
            item = self._row(row) or {}
            item["score"] = round(score, 5)
            item["retrieval"] = {"lexical": round(lex, 5), "vector": round(vector_score, 5), "backend": self.vector_backend}
            item["citations"] = [{"knowledge_id": raw["id"], "title": raw["title"], "source_uri": raw["source_uri"],
                                  "source_hash": raw["source_hash"], "content_hash": raw["content_hash"], "version": raw["version"]}]
            scored.append(item)
        return sorted(scored, key=lambda x: x["score"], reverse=True)[:max(1, min(limit, 50))]

    def evaluate(self, name: str, cases: list[dict[str, Any]], *, actor: str = "operator", k: int = 5) -> dict[str, Any]:
        if not name.strip() or not cases: raise ValueError("name and at least one evaluation case are required")
        k = max(1, min(int(k), 20))
        def run(mode: str) -> dict[str, Any]:
            hits = 0; reciprocal = 0.0; citation_ok = 0
            details = []
            for case in cases:
                query = str(case.get("query") or "").strip(); expected = {str(x) for x in case.get("expected_ids", [])}
                if not query or not expected: raise ValueError("each case requires query and expected_ids")
                results = self.search(query, domain=str(case.get("domain") or ""), limit=k, mode=mode)
                ids = [r["id"] for r in results]; ranks = [i + 1 for i, item in enumerate(ids) if item in expected]
                if ranks: hits += 1; reciprocal += 1.0 / min(ranks)
                if results and all((r.get("citations") or [{}])[0].get("content_hash") for r in results): citation_ok += 1
                details.append({"query": query, "expected_ids": sorted(expected), "returned_ids": ids, "first_relevant_rank": min(ranks) if ranks else None})
            n = len(cases)
            return {"cases": n, "k": k, "recall_at_k": round(hits / n, 5), "mrr_at_k": round(reciprocal / n, 5),
                    "citation_completeness": round(citation_ok / n, 5), "details": details}
        baseline = run("lexical"); candidate = run("hybrid")
        passed = candidate["recall_at_k"] >= baseline["recall_at_k"] and candidate["mrr_at_k"] >= baseline["mrr_at_k"] and candidate["citation_completeness"] == 1.0
        eid = "EVAL-" + uuid.uuid4().hex[:16]; now = time.time()
        with self._db() as c:
            c.execute("INSERT INTO retrieval_evaluations(id,name,baseline_json,candidate_json,promoted,approved_by,created) VALUES(?,?,?,?,?,?,?)",
                      (eid, name, _json(baseline), _json(candidate), 0, "", now))
        return {"id": eid, "name": name, "baseline": baseline, "candidate": candidate, "gate_passed": passed,
                "promoted": False, "note": "A passing benchmark records evidence but does not itself approve a backend promotion.", "actor": actor}

    def evaluations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._db() as c:
            rows = c.execute("SELECT * FROM retrieval_evaluations ORDER BY created DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        out=[]
        for row in rows:
            item=dict(row);item["baseline"]=json.loads(item.pop("baseline_json"));item["candidate"]=json.loads(item.pop("candidate_json"));item["promoted"]=bool(item["promoted"]);out.append(item)
        return out

    def detect_contradictions(self, kid: str) -> list[dict[str, Any]]:
        current = self.get(kid)
        if not current: return []
        ctokens = set(_tokens(current["content"]))
        if not ctokens: return []
        created: list[dict[str, Any]] = []
        with self._db() as c:
            rows = c.execute("SELECT * FROM knowledge WHERE id!=? AND state NOT IN ('rejected','retired') AND (domain=? OR canonical_key=?)",
                             (kid, current["domain"], current["canonical_key"] or "__none__")).fetchall()
            for row in rows:
                other = dict(row); otokens = set(_tokens(other["content"]))
                overlap = len(ctokens & otokens) / max(1, len(ctokens | otokens))
                same_key = bool(current["canonical_key"] and current["canonical_key"] == other["canonical_key"])
                negation_flip = bool((ctokens & _NEG) != (otokens & _NEG))
                if not ((same_key and current["content_hash"] != other["content_hash"]) or (overlap >= .55 and negation_flip)):
                    continue
                left, right = sorted((kid, other["id"]))
                reason = "canonical_key_conflict" if same_key else "possible_negation_conflict"
                cid = "CON-" + hashlib.sha256(f"{left}|{right}|{reason}".encode()).hexdigest()[:16]
                now = time.time(); score = 1.0 if same_key else overlap
                c.execute("INSERT OR IGNORE INTO contradictions(id,left_id,right_id,reason,score,created,updated) VALUES(?,?,?,?,?,?,?)",
                          (cid, left, right, reason, score, now, now))
                if c.execute("SELECT changes()").fetchone()[0]:
                    created.append({"id": cid, "left_id": left, "right_id": right, "reason": reason, "score": round(score, 4), "state": "open"})
        return created

    def contradictions(self, state: str = "open", limit: int = 100) -> list[dict[str, Any]]:
        with self._db() as c:
            rows = c.execute("SELECT * FROM contradictions WHERE (?='' OR state=?) ORDER BY updated DESC LIMIT ?",
                             (state, state, max(1, min(limit, 500)))).fetchall()
            return [dict(r) for r in rows]

    def resolve_contradiction(self, cid: str, *, resolution: str, actor: str) -> dict[str, Any] | None:
        if not resolution.strip() or not actor.strip():
            raise ValueError("resolution and actor are required")
        with self._db() as c:
            now = time.time()
            c.execute("UPDATE contradictions SET state='resolved',resolution=?,resolved_by=?,updated=? WHERE id=?",
                      (resolution, actor, now, cid))
            if not c.execute("SELECT changes()").fetchone()[0]: return None
            return dict(c.execute("SELECT * FROM contradictions WHERE id=?", (cid,)).fetchone())

    def consolidation_preview(self, *, older_days: int = 180, max_importance: float = .25) -> dict[str, Any]:
        cutoff = time.time() - max(1, older_days) * 86400
        with self._db() as c:
            rows = c.execute("SELECT id,title,state,importance,updated FROM knowledge WHERE state IN ('draft','rejected') AND updated<? AND importance<=? ORDER BY updated",
                             (cutoff, max_importance)).fetchall()
        return {"mode": "preview_only", "destructive": False, "candidates": [dict(r) for r in rows],
                "note": "No record is retired or deleted without a separate operator-approved transition."}

    def status(self) -> dict[str, Any]:
        with self._db() as c:
            by_state = {r[0]: r[1] for r in c.execute("SELECT state,count(*) FROM knowledge GROUP BY state")}
            open_conflicts = c.execute("SELECT count(*) FROM contradictions WHERE state='open'").fetchone()[0]
            fts = bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_fts'").fetchone())
        return {"records": sum(by_state.values()), "by_state": by_state, "open_contradictions": open_conflicts,
                "retrieval": {"hybrid": True, "lexical_fts5": fts, "vector": True,
                              "vector_backend": self.vector_backend, "neural_semantic_embeddings": False,
                              "citation_objects": True},
                "governance": {"human_approval_before_promotion": True, "append_only_events": True,
                               "automatic_conflict_resolution": False, "automatic_destructive_consolidation": False}}


class ObsidianBridge:
    """Manual, one-way-at-a-time Markdown exchange with traversal protection."""

    def __init__(self, store: KnowledgeStore, vault: str):
        self.store = store; self.vault = Path(vault)

    def _root(self) -> Path:
        root = self.vault.resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def export_approved(self) -> dict[str, Any]:
        root = self._root(); destination = root / "SolomonPrime" / "Approved"
        destination.mkdir(parents=True, exist_ok=True)
        written = []
        for row in self.store.list(state="approved", limit=500):
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", row["id"]).strip("-") + ".md"
            target = (destination / safe).resolve()
            if root not in target.parents: raise ValueError("vault path escape rejected")
            front = {"solomon_id": row["id"], "state": row["state"], "kind": row["kind"], "domain": row["domain"],
                     "version": row["version"], "content_hash": row["content_hash"], "source_uri": row["source_uri"],
                     "approved_by": row["approved_by"], "approved_at": row["approved_at"]}
            body = "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in front.items()) + "\n---\n\n# " + row["title"] + "\n\n" + row["content"] + "\n"
            target.write_text(body, encoding="utf-8")
            written.append({"knowledge_id": row["id"], "path": str(target.relative_to(root)), "sha256": hashlib.sha256(body.encode()).hexdigest()})
        return {"mode": "manual_export", "written": written, "count": len(written)}

    def import_draft(self, relative_path: str, *, actor: str = "operator") -> dict[str, Any]:
        root = self._root(); source = (root / relative_path).resolve()
        if root != source and root not in source.parents: raise ValueError("vault path escape rejected")
        if not source.is_file() or source.suffix.lower() != ".md": raise ValueError("a Markdown file inside the vault is required")
        raw = source.read_text(encoding="utf-8", errors="strict")
        if len(raw.encode()) > 2_000_000: raise ValueError("note exceeds 2 MB import limit")
        content = re.sub(r"\A---\n.*?\n---\n", "", raw, flags=re.S).strip()
        title_match = re.search(r"^#\s+(.+)$", content, re.M)
        title = title_match.group(1).strip() if title_match else source.stem
        return self.store.create({"title": title, "content": content, "kind": "note", "state": "draft",
                                  "domain": "obsidian", "source_type": "obsidian_manual_import",
                                  "source_uri": str(source.relative_to(root)), "source_hash": hashlib.sha256(raw.encode()).hexdigest(),
                                  "author": actor, "tags": ["obsidian", "untrusted-draft"]})
