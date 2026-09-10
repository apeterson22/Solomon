from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_KINDS = {"python", "blender", "openscad"}
AUTO_RISKS = {"read_only", "reversible"}
MAX_SOURCE_BYTES = 1024 * 1024


class JobResources(BaseModel):
    """Public resource envelope for a bounded job."""

    model_config = ConfigDict(extra="forbid")

    locality_node_id: str = ""
    min_ram_gb: float = Field(default=0.5, ge=0.25, le=4096)
    min_gpu_vram_gb: float = Field(default=0, ge=0, le=1024)
    preferred_gpu_vendor: str = ""
    requires_gpu: bool = False
    max_cpu_util_pct: float = Field(default=90, ge=1, le=100)
    max_runtime_seconds: int = Field(default=900, ge=1, le=86400)
    max_memory_gb: float = Field(default=4, ge=0.25, le=256)
    max_cpu_cores: float = Field(default=2, ge=0.1, le=64)
    max_disk_gb: float = Field(default=4, ge=0.1, le=512)


class JobSubmitRequest(BaseModel):
    """Typed public job request. Mesh requests remain signed raw bytes."""

    model_config = ConfigDict(extra="forbid")

    actor: str = "solomon-core"
    goal_id: str = ""
    experiment_id: str = ""
    kind: Literal["python", "blender", "openscad"]
    workload_kind: str = "job"
    risk: str = "reversible"
    priority: str = "background"
    source: str
    resources: JobResources = Field(default_factory=JobResources)
    allow_network: bool = False
    stateful: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source")
    @classmethod
    def source_within_limit(cls, value: str) -> str:
        if not value:
            raise ValueError("source is required")
        if len(value.encode()) > MAX_SOURCE_BYTES:
            raise ValueError("source exceeds 1 MiB limit")
        return value


class JobSubmitResponse(BaseModel):
    job: dict[str, Any]
    placement: dict[str, Any]
    policy: str


class ApprovalRequiredResponse(BaseModel):
    state: Literal["approval_required"]
    approval: dict[str, Any]
    note: str


def manifest_hash(v: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def new_job_id() -> str:
    return "JOB-" + time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:12]


class JobStore:
    def __init__(self, path: str):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self._init()

    def _db(self):
        c=sqlite3.connect(self.path,check_same_thread=False);c.row_factory=sqlite3.Row;c.execute("PRAGMA journal_mode=WAL");return c

    def _init(self):
        with self._db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, node_id TEXT, endpoint TEXT, kind TEXT, risk TEXT, status TEXT,
              manifest TEXT, manifest_hash TEXT, goal_id TEXT, experiment_id TEXT,
              created REAL, started REAL, finished REAL, exit_code INTEGER, result TEXT, error TEXT
            )""")

    def create(self, jid: str, manifest: dict[str, Any], *, node_id: str = "", endpoint: str = "", status: str = "queued") -> dict[str, Any]:
        now=time.time();mh=manifest_hash(manifest)
        with self._db() as c:
            c.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
                jid,node_id,endpoint,str(manifest.get("kind") or ""),str(manifest.get("risk") or "reversible"),status,
                json.dumps(manifest),mh,str(manifest.get("goal_id") or ""),str(manifest.get("experiment_id") or ""),now,None,None,None,"{}",""))
        return self.get(jid) or {}

    def update(self,jid:str,**fields:Any)->None:
        allowed={"node_id","endpoint","status","started","finished","exit_code","result","error"}
        vals=[];sets=[]
        for k,v in fields.items():
            if k not in allowed:continue
            if k=="result" and not isinstance(v,str):v=json.dumps(v)
            sets.append(f"{k}=?");vals.append(v)
        if not sets:return
        vals.append(jid)
        with self._db() as c:c.execute(f"UPDATE jobs SET {','.join(sets)} WHERE id=?",vals)

    def get(self,jid:str)->dict[str,Any]|None:
        with self._db() as c:r=c.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone()
        if not r:return None
        d=dict(r)
        for k,default in (("manifest",{}),("result",{})):
            try:d[k]=json.loads(d.get(k) or json.dumps(default))
            except Exception:d[k]=default
        return d

    def list(self,limit:int=100)->list[dict[str,Any]]:
        with self._db() as c:rows=c.execute("SELECT id FROM jobs ORDER BY created DESC LIMIT ?",(min(max(limit,1),500),)).fetchall()
        return [j for r in rows if (j:=self.get(r[0]))]


class JobExecutor:
    """Node-local bounded executor.

    The API never accepts an arbitrary command line. It accepts one of three fixed
    executor types and source content. A root-owned helper launches the job under a
    dedicated low-privilege account and systemd resource/sandbox policy.
    """
    def __init__(self, store: JobStore, workspace_root: str, launcher: str):
        self.store=store;self.root=Path(workspace_root);self.root.mkdir(parents=True,exist_ok=True);self.launcher=launcher

    @staticmethod
    def validate(manifest:dict[str,Any])->dict[str,Any]:
        kind=str(manifest.get("kind") or "").lower();risk=str(manifest.get("risk") or "reversible").lower()
        if kind not in ALLOWED_KINDS:raise ValueError(f"unsupported job kind: {kind}")
        if risk not in AUTO_RISKS:raise ValueError("worker executor only accepts read_only/reversible jobs")
        src=str(manifest.get("source") or "")
        if not src:raise ValueError("source is required")
        if len(src.encode())>MAX_SOURCE_BYTES:raise ValueError("source exceeds 1 MiB limit")
        r=dict(manifest.get("resources") or {})
        max_runtime=min(max(int(r.get("max_runtime_seconds") or 900),1),86400)
        max_memory=min(max(float(r.get("max_memory_gb") or 4),0.25),256.0)
        max_cpu=min(max(float(r.get("max_cpu_cores") or 2),0.1),64.0)
        allow_network=bool(manifest.get("allow_network",False))
        return {**manifest,"kind":kind,"risk":risk,"resources":{**r,"max_runtime_seconds":max_runtime,"max_memory_gb":max_memory,"max_cpu_cores":max_cpu},"allow_network":allow_network}

    def submit(self,jid:str,manifest:dict[str,Any],*,node_id:str)->dict[str,Any]:
        if not re.fullmatch(r"JOB-[A-Za-z0-9_-]{1,100}", jid):raise ValueError("invalid job id")
        m=self.validate(manifest);jobdir=self.root/jid
        if jobdir.exists():raise ValueError("job workspace already exists")
        jobdir.mkdir(parents=True,mode=0o750)
        ext={"python":"py","blender":"py","openscad":"scad"}[m["kind"]]
        source_path=jobdir/f"main.{ext}";source_path.write_text(str(m["source"]),encoding="utf-8")
        safe={k:v for k,v in m.items() if k!="source"};safe["source_file"]=source_path.name;safe["source_sha256"]=hashlib.sha256(source_path.read_bytes()).hexdigest();safe["job_id"]=jid;safe["workspace"]=str(jobdir)
        (jobdir/"manifest.json").write_text(json.dumps(safe,indent=2,sort_keys=True),encoding="utf-8")
        self.store.create(jid,m,node_id=node_id,status="queued")
        threading.Thread(target=self._run,args=(jid,jobdir),daemon=True).start()
        return self.store.get(jid) or {}

    def _run(self,jid:str,jobdir:Path)->None:
        self.store.update(jid,status="running",started=time.time())
        try:
            # The launcher is an unprivileged Unix-socket client.  A separately
            # hardened root broker revalidates the manifest and invokes the
            # privileged runner; the network-facing daemon never calls sudo.
            p=subprocess.run([self.launcher,str(jobdir/"manifest.json")],text=True,capture_output=True,timeout=87000)
            (jobdir/"runner.stdout.log").write_text(p.stdout or "",encoding="utf-8")
            (jobdir/"runner.stderr.log").write_text(p.stderr or "",encoding="utf-8")
            result_path=jobdir/"result.json"
            if result_path.exists():
                try:result=json.loads(result_path.read_text(encoding="utf-8"))
                except Exception:result={"stdout":(p.stdout or "")[-12000:],"stderr":(p.stderr or "")[-12000:]}
            else:result={"stdout":(p.stdout or "")[-12000:],"stderr":(p.stderr or "")[-12000:]}
            self.store.update(jid,status="completed" if p.returncode==0 else "failed",finished=time.time(),exit_code=p.returncode,result=result,error="" if p.returncode==0 else (p.stderr or "")[-4000:])
        except Exception as e:
            self.store.update(jid,status="failed",finished=time.time(),exit_code=255,error=f"{type(e).__name__}: {e}")
