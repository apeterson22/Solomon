from __future__ import annotations

import hashlib, json, os, sqlite3, time
from collections import defaultdict
from pathlib import Path
from typing import Any
try:
    from blake3 import blake3
except Exception:
    blake3=None

class StorageIndex:
    def __init__(self,path:str):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self._init()
    def _db(self):
        c=sqlite3.connect(self.path,check_same_thread=False);c.row_factory=sqlite3.Row;c.execute("PRAGMA journal_mode=WAL");return c
    def _init(self):
        with self._db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,size INTEGER,mtime REAL,ext TEXT,sample_hash TEXT,full_hash TEXT,scan_id TEXT)""")
            c.execute("CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY,started REAL,finished REAL,roots TEXT,file_count INTEGER,bytes INTEGER,errors INTEGER)")
    def _sample(self,p:Path,size:int)->str:
        h=blake3() if blake3 else hashlib.sha256();chunk=65536
        with p.open("rb") as f:
            h.update(f.read(chunk))
            if size>2*chunk:
                f.seek(max(0,size//2-chunk//2));h.update(f.read(chunk));f.seek(max(0,size-chunk));h.update(f.read(chunk))
        return h.hexdigest()
    def _full(self,p:Path)->str:
        h=blake3() if blake3 else hashlib.sha256()
        with p.open("rb") as f:
            while True:
                b=f.read(4*1024*1024)
                if not b:break
                h.update(b)
        return h.hexdigest()
    def scan(self,roots:list[str],*,min_size:int=1,max_files:int=0)->dict[str,Any]:
        sid=f"scan-{int(time.time())}";started=time.time();count=bytes_=errors=0;rows=[]
        skip_prefix=("/proc/","/sys/","/dev/","/run/","/snap/")
        for root in roots:
            rp=Path(root)
            if not rp.exists():continue
            for base,dirs,files in os.walk(rp,followlinks=False):
                dirs[:]=[d for d in dirs if not os.path.join(base,d).startswith(skip_prefix)]
                for fn in files:
                    if max_files and count>=max_files:break
                    p=Path(base)/fn
                    try:
                        if p.is_symlink() or not p.is_file():continue
                        st=p.stat()
                        if st.st_size<min_size:continue
                        sh=self._sample(p,st.st_size)
                        rows.append((str(p),st.st_size,st.st_mtime,p.suffix.lower(),sh,"",sid));count+=1;bytes_+=st.st_size
                    except Exception:errors+=1
                if max_files and count>=max_files:break
        with self._db() as c:
            c.executemany("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?)",rows)
            # Compute full hashes only for same-size + same-sample collisions.
            groups=c.execute("SELECT size,sample_hash,count(*) n FROM files WHERE scan_id=? GROUP BY size,sample_hash HAVING n>1",(sid,)).fetchall()
            for g in groups:
                cand=c.execute("SELECT path FROM files WHERE scan_id=? AND size=? AND sample_hash=?",(sid,g["size"],g["sample_hash"])).fetchall()
                for r in cand:
                    try:fh=self._full(Path(r["path"]));c.execute("UPDATE files SET full_hash=? WHERE path=?",(fh,r["path"]))
                    except Exception:errors+=1
            c.execute("INSERT INTO scans VALUES(?,?,?,?,?,?,?)",(sid,started,time.time(),json.dumps(roots),count,bytes_,errors))
        return {"scan_id":sid,"roots":roots,"files":count,"bytes":bytes_,"errors":errors,"mode":"read_only"}
    def duplicate_plan(self,scan_id:str="")->dict[str,Any]:
        with self._db() as c:
            if not scan_id:
                r=c.execute("SELECT id FROM scans ORDER BY finished DESC LIMIT 1").fetchone();scan_id=r[0] if r else ""
            if not scan_id:return {"sets":[],"recoverable_bytes":0}
            groups=c.execute("SELECT full_hash,size,count(*) n FROM files WHERE scan_id=? AND full_hash!='' GROUP BY full_hash,size HAVING n>1 ORDER BY size*n DESC",(scan_id,)).fetchall()
            sets=[];recover=0
            for g in groups:
                paths=[r[0] for r in c.execute("SELECT path FROM files WHERE scan_id=? AND full_hash=? ORDER BY path",(scan_id,g["full_hash"])).fetchall()]
                rb=int(g["size"])*(len(paths)-1);recover+=rb
                sets.append({"hash":g["full_hash"],"size":g["size"],"copies":len(paths),"paths":paths,"recoverable_bytes":rb,"action":"proposal_only"})
            return {"scan_id":scan_id,"sets":sets,"recoverable_bytes":recover,"destructive_actions_available":False}
    @staticmethod
    def classify_layout(block_devices:list[dict[str,Any]])->dict[str,Any]:
        flat=[]
        def walk(devs):
            for d in devs:
                flat.append(d);walk(d.get("children") or [])
        walk(block_devices)
        candidates=[]
        for d in flat:
            if d.get("type") not in {"disk","part","lvm"}:continue
            rota=d.get("rota");mounts=d.get("mountpoints") or []
            if isinstance(mounts,str):mounts=[mounts]
            speed_class="ssd" if rota in {False,0,"0"} else "hdd"
            candidates.append({"path":d.get("path"),"model":d.get("model"),"size":d.get("size"),"fstype":d.get("fstype"),"mountpoints":[m for m in mounts if m],"class":speed_class})
        return {"devices":candidates,"principles":{"hot":"SSD/NVMe: active models, indexes, caches, current work","bulk":"high-capacity mounted storage: datasets and simulation outputs","archive":"separate bulk disk: immutable evidence/backups/cold files","root":"OS/services only; avoid large model blobs"},"automatic_moves":False}
