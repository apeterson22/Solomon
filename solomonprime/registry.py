from __future__ import annotations
import json, sqlite3, time
from pathlib import Path
from typing import Any


def preferred_from_endpoints(endpoints:list[dict[str,Any]]|None, explicit:str="")->str:
    eps=[e for e in (endpoints or []) if e.get("endpoint")]
    if eps:
        best=max(eps,key=lambda e:(float(e.get("rank") or 0),float(e.get("speed_mbps") or 0)))
        return str(best.get("endpoint") or explicit or "")
    return explicit or ""


class NodeRegistry:
    def __init__(self,path:str):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
    def _db(self):
        c=sqlite3.connect(self.path,check_same_thread=False); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); return c
    def _init(self):
        with self._db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS nodes(
              node_id TEXT PRIMARY KEY,name TEXT,role TEXT,trust TEXT,capabilities TEXT,snapshot TEXT,endpoints TEXT,
              preferred_endpoint TEXT,last_seen REAL,health TEXT,source TEXT,assigned_profile TEXT)""")
    def upsert(self,info:dict[str,Any],*,role:str="node",trust:str="trusted",source:str="heartbeat",endpoints:list[dict[str,Any]]|None=None,preferred_endpoint:str="",assigned_profile:dict[str,Any]|None=None):
        nid=str(info.get("node_id") or "");
        if not nid:return
        eps=endpoints if endpoints is not None else ((info.get("network") or {}).get("paths") or [])
        pref=preferred_from_endpoints(eps,preferred_endpoint)
        caps=info.get("capabilities") or []
        with self._db() as c:
            old=c.execute("SELECT trust FROM nodes WHERE node_id=?",(nid,)).fetchone(); oldtrust=old[0] if old else ""
            effective=oldtrust if oldtrust in {"trusted","blocked"} else trust
            c.execute("""INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET
              name=excluded.name,role=excluded.role,trust=?,capabilities=excluded.capabilities,snapshot=excluded.snapshot,
              endpoints=excluded.endpoints,preferred_endpoint=excluded.preferred_endpoint,
              last_seen=excluded.last_seen,health='online',source=excluded.source,assigned_profile=CASE WHEN excluded.assigned_profile!='{}' THEN excluded.assigned_profile ELSE nodes.assigned_profile END""",
              (nid,str(info.get("name") or nid),role,effective,json.dumps(caps),json.dumps(info),json.dumps(eps),pref,time.time(),"online",source,json.dumps(assigned_profile or {}),effective))
    def set_trust(self,nid:str,trust:str)->bool:
        if trust not in {"trusted","pending","blocked"}:raise ValueError(trust)
        with self._db() as c:return c.execute("UPDATE nodes SET trust=? WHERE node_id=?",(trust,nid)).rowcount==1
    def recompute_preferred(self)->int:
        changed=0
        with self._db() as c:
            rows=c.execute("SELECT node_id,endpoints,preferred_endpoint FROM nodes").fetchall()
            for r in rows:
                try:eps=json.loads(r[1] or "[]")
                except Exception:eps=[]
                pref=preferred_from_endpoints(eps,str(r[2] or ""))
                if pref!=str(r[2] or ""):
                    c.execute("UPDATE nodes SET preferred_endpoint=? WHERE node_id=?",(pref,r[0]));changed+=1
        return changed
    def list(self,stale_after:int=90)->list[dict[str,Any]]:
        now=time.time(); out=[]
        with self._db() as c: rows=c.execute("SELECT * FROM nodes ORDER BY name").fetchall()
        for r in rows:
            d=dict(r); d["capabilities"]=json.loads(d["capabilities"] or "[]"); d["snapshot"]=json.loads(d["snapshot"] or "{}"); d["endpoints"]=json.loads(d["endpoints"] or "[]"); d["assigned_profile"]=json.loads(d["assigned_profile"] or "{}")
            if now-float(d["last_seen"] or 0)>stale_after:d["health"]="stale"
            out.append(d)
        return out
    def get(self,nid:str)->dict[str,Any]|None:
        with self._db() as c:r=c.execute("SELECT * FROM nodes WHERE node_id=?",(nid,)).fetchone()
        if not r:return None
        d=dict(r); d["capabilities"]=json.loads(d["capabilities"] or "[]"); d["snapshot"]=json.loads(d["snapshot"] or "{}"); d["endpoints"]=json.loads(d["endpoints"] or "[]"); d["assigned_profile"]=json.loads(d["assigned_profile"] or "{}"); return d
