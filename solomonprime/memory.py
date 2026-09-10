from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

_WORD=re.compile(r"[A-Za-z0-9_./:-]+")

def _norm(s:str)->str:
    return " ".join(_WORD.findall(s.lower()))

def _tokens(s:str)->set[str]:
    return set(_norm(s).split())

def _jaccard(a:str,b:str)->float:
    aa=_tokens(a);bb=_tokens(b)
    if not aa or not bb:return 0.0
    return len(aa&bb)/len(aa|bb)

def _recency(ts:float,half_life_days:float=90)->float:
    age=max(0,time.time()-ts);return math.exp(-math.log(2)*age/(half_life_days*86400))

class MemoryStore:
    """Tiered lightweight memory optimized for small-host deployment.

    L0 scratch is intentionally not persisted here. Persisted tiers:
      working, episodic, semantic, domain, archive.
    Retrieval combines SQLite FTS relevance with importance, confidence,
    recency, reuse, and domain/agent matches. Near-duplicates are merged.
    """
    def __init__(self,path:str):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self._init()
    def _db(self):
        c=sqlite3.connect(self.path,check_same_thread=False);c.row_factory=sqlite3.Row;c.execute("PRAGMA journal_mode=WAL");c.execute("PRAGMA synchronous=NORMAL");return c
    def _init(self):
        with self._db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS memory(
              id INTEGER PRIMARY KEY, content TEXT NOT NULL, content_hash TEXT NOT NULL,
              tier TEXT, agent TEXT, domain TEXT, source TEXT, importance REAL, confidence REAL,
              tags TEXT, created REAL, updated REAL, last_access REAL, access_count INTEGER DEFAULT 0,
              supersedes INTEGER DEFAULT 0, archived INTEGER DEFAULT 0)""")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_hash_scope ON memory(content_hash,agent,domain,archived)")
            try:
                c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content, tags, content='memory', content_rowid='id')")
                c.executescript("""
                  CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memory BEGIN INSERT INTO memory_fts(rowid,content,tags) VALUES(new.id,new.content,new.tags); END;
                  CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memory BEGIN INSERT INTO memory_fts(memory_fts,rowid,content,tags) VALUES('delete',old.id,old.content,old.tags); END;
                  CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON memory BEGIN
                    INSERT INTO memory_fts(memory_fts,rowid,content,tags) VALUES('delete',old.id,old.content,old.tags);
                    INSERT INTO memory_fts(rowid,content,tags) VALUES(new.id,new.content,new.tags);
                  END;
                """)
            except sqlite3.OperationalError:pass
    def remember(self,content:str,*,tier:str="semantic",agent:str="solomon-core",domain:str="general",source:str="",importance:float=.5,confidence:float=.8,tags:str="")->dict[str,Any]:
        content=content.strip()
        if not content:return {"stored":False,"reason":"empty"}
        h=hashlib.sha256(_norm(content).encode()).hexdigest();now=time.time()
        with self._db() as c:
            ex=c.execute("SELECT * FROM memory WHERE content_hash=? AND agent=? AND domain=? AND archived=0",(h,agent,domain)).fetchone()
            if ex:
                c.execute("UPDATE memory SET updated=?,importance=max(importance,?),confidence=max(confidence,?) WHERE id=?",(now,importance,confidence,ex["id"]))
                return {"stored":False,"deduplicated":True,"id":ex["id"]}
            # semantic-near-dedup only among a few recent same-scope memories
            candidates=c.execute("SELECT id,content,importance,confidence FROM memory WHERE agent=? AND domain=? AND archived=0 ORDER BY updated DESC LIMIT 50",(agent,domain)).fetchall()
            for r in candidates:
                sim=_jaccard(content,r["content"])
                if sim>=.92:
                    # Keep the more informative version, preserving the existing id.
                    chosen=content if len(content)>len(r["content"]) else r["content"]
                    c.execute("UPDATE memory SET content=?,content_hash=?,updated=?,importance=max(importance,?),confidence=max(confidence,?) WHERE id=?",(chosen,hashlib.sha256(_norm(chosen).encode()).hexdigest(),now,importance,confidence,r["id"]))
                    return {"stored":False,"near_deduplicated":True,"id":r["id"],"similarity":round(sim,3)}
            cur=c.execute("INSERT INTO memory(content,content_hash,tier,agent,domain,source,importance,confidence,tags,created,updated,last_access) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(content,h,tier,agent,domain,source,max(0,min(1,importance)),max(0,min(1,confidence)),tags,now,now,now))
            return {"stored":True,"id":cur.lastrowid}
    def search(self,q:str,*,agent:str="",domain:str="",limit:int=6)->list[dict[str,Any]]:
        q=q.strip();rows=[]
        with self._db() as c:
            try:
                terms=" OR ".join(re.findall(r"[A-Za-z0-9_]+",q)[:12]) or q
                sql="""SELECT m.*, bm25(memory_fts) AS bm FROM memory_fts JOIN memory m ON m.id=memory_fts.rowid WHERE memory_fts MATCH ? AND m.archived=0"""
                args:[Any]=[terms]
                if agent:sql+=" AND (m.agent=? OR m.agent='solomon-core')";args.append(agent)
                if domain:sql+=" AND (m.domain=? OR m.domain='general')";args.append(domain)
                sql+=" ORDER BY bm LIMIT 40";rows=c.execute(sql,args).fetchall()
            except sqlite3.OperationalError:
                like=f"%{q[:80]}%";rows=c.execute("SELECT *,0 AS bm FROM memory WHERE archived=0 AND content LIKE ? ORDER BY updated DESC LIMIT 40",(like,)).fetchall()
            scored=[]
            for r in rows:
                bm=float(r["bm"] or 0);lex=1/(1+max(0,bm+10)) if bm>=0 else min(1,1/(1+abs(bm)))
                rec=_recency(float(r["updated"] or r["created"] or time.time()));reuse=min(math.log1p(int(r["access_count"] or 0))/4,1)
                scope=(.08 if domain and r["domain"]==domain else 0)+(.05 if agent and r["agent"]==agent else 0)
                score=.52*lex+.15*float(r["importance"] or .5)+.11*float(r["confidence"] or .8)+.10*rec+.04*reuse+scope
                d=dict(r);d["score"]=round(score,4);d.pop("bm",None);scored.append(d)
            scored.sort(key=lambda x:x["score"],reverse=True);out=scored[:limit]
            if out:c.executemany("UPDATE memory SET access_count=access_count+1,last_access=? WHERE id=?",[(time.time(),x["id"]) for x in out])
            return out
    def capture_interaction(self,user_text:str,assistant_text:str,*,agent:str,domain:str)->dict[str,Any]:
        u=user_text.strip();a=assistant_text.strip()
        if not u or not a:return {"stored":False}
        markers=("remember","decision","decided","configure","installed","path","ip ","server","model","drive","farm","home","schedule","project","goal","should")
        imp=.35+.18*any(m in u.lower() for m in markers)+.08*(len(u)>500)+.08*(len(a)>1000)
        # Store a bounded evidence-backed episode; later consolidation can promote durable facts.
        content=f"User: {u[:1800]}\nAssistant: {a[:2200]}"
        return self.remember(content,tier="episodic",agent=agent,domain=domain,source="conversation",importance=min(imp,.8),confidence=.72,tags="conversation")
    def stats(self)->dict[str,Any]:
        with self._db() as c:
            total=c.execute("SELECT count(*) FROM memory WHERE archived=0").fetchone()[0]
            by=c.execute("SELECT tier,count(*) n FROM memory WHERE archived=0 GROUP BY tier").fetchall()
            fts5=bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_fts'").fetchone())
        return {
            "active":total,
            "by_tier":{r[0]:r[1] for r in by},
            "retrieval":{
                "backend":"sqlite_fts5" if fts5 else "sqlite_like_fallback",
                "lexical":True,
                "fts5":fts5,
                "vector_embeddings":False,
                "hybrid_reranking":False,
            },
            "quality_controls":{
                "exact_deduplication":True,
                "near_deduplication":"jaccard_same_scope_recent",
                "importance_confidence_recency_scoring":True,
                "automatic_contradiction_resolution":False,
                "automatic_knowledge_compilation":False,
            },
        }
    def archive_low_value(self,*,older_days:int=180,max_importance:float=.25)->int:
        cutoff=time.time()-older_days*86400
        with self._db() as c:
            cur=c.execute("UPDATE memory SET archived=1 WHERE archived=0 AND updated<? AND importance<=? AND access_count<2",(cutoff,max_importance));return cur.rowcount
