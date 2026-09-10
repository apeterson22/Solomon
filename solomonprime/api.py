from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse

from .availability import read_availability
from .host_skills import inspect_host, COMMANDS as HOST_COMMANDS
from .skills import EXECUTION_TOOLS, execute_skill
from .agents import AgentCatalog, MODEL_TO_AGENT
from .approvals import ApprovalStore
from .audit import AuditLog
from .config import load_settings
from .cloud_router import CloudRouter
from .discovery import Advertiser, DiscoveryLoop
from .hardware import profile as hardware_profile
from .goals import GoalStore
from .experiments import ExperimentLedger
from .jobs import (
    AUTO_RISKS,
    ApprovalRequiredResponse,
    JobExecutor,
    JobStore,
    JobSubmitRequest,
    JobSubmitResponse,
    new_job_id,
)
from .llm import api_headers, extract_text
from .memory import MemoryStore
from .models import LocalModelCatalog
from .energy import EnergyTracker
from .edge_devices import EdgeDeviceRegistry
from .rf import RFMonitor
from .voice import VoiceSecurity
from .calendars import CalendarPull
from .selfdev import DevelopmentLab
from .maintenance import Maintenance
from .mobile import MobileAccess
from .knowledge import KnowledgeStore, ObsidianBridge
from .planner import LLMAdvisor
from .provision import make_profile
from .registry import NodeRegistry
from .scheduler import Workload, plan as schedule_plan
from .security import ReplayGuard, ensure_key, sign, verify
from .storage import StorageIndex

settings=load_settings()

def stable_node_id(explicit:str="")->str:
    if explicit:return explicit
    seed=""
    for p in (Path("/etc/machine-id"),Path("/var/lib/dbus/machine-id")):
        if p.exists():seed=p.read_text().strip();break
    seed=seed or socket.gethostname()
    return f"{socket.gethostname()}-{hashlib.sha256(seed.encode()).hexdigest()[:10]}"

NODE_ID=stable_node_id(settings.node_id);NODE_NAME=settings.node_name or socket.gethostname()
cluster_key=ensure_key(settings.cluster_key_file);public_key=ensure_key(settings.public_api_key_file)
public_key_text=Path(settings.public_api_key_file).read_text().strip();state=settings.state_path
registry=NodeRegistry(str(state/"nodes.db"));approvals=ApprovalStore(str(state/"approvals.db"));memory=MemoryStore(str(state/"memory.db"));knowledge=KnowledgeStore(settings.knowledge_db,vector_backend=settings.knowledge_vector_backend);obsidian=ObsidianBridge(knowledge,settings.obsidian_vault_path);storage=StorageIndex(str(state/"storage-index.db"));audit=AuditLog(str(state/"audit.jsonl"));replay=ReplayGuard()
goals=GoalStore(settings.goals_db);experiments=ExperimentLedger(settings.experiments_db,settings.experiment_artifact_dir);jobs=JobStore(settings.jobs_db);job_executor=JobExecutor(jobs,settings.job_workspace_dir,settings.job_runner)
agents=AgentCatalog("/apps/solomonprime/app/agents",settings.enabled_agents)
local_models=LocalModelCatalog(settings.llm_model_hint,settings.ollama_endpoint)
cloud=CloudRouter(settings.cloud_provider_config,settings.cloud_quota_ledger,settings.cloud_training_dir,
    complexity_threshold=settings.cloud_complexity_threshold,quota_margin=settings.cloud_quota_margin,
    max_calls_per_request=settings.cloud_max_calls_per_request,capture_training=settings.cloud_capture_training,
    sensitive_policy=settings.cloud_sensitive_policy)
energy=EnergyTracker(settings.energy_config,settings.energy_ledger)
edge_devices=EdgeDeviceRegistry(settings.edge_device_catalog,settings.edge_device_state)
rf_monitor=RFMonitor(settings.rf_ledger)
voice_security=VoiceSecurity(settings.voice_config,settings.voice_ledger,public_key_text)
calendar_pull=CalendarPull(settings.calendar_config,settings.calendar_ledger)
development=DevelopmentLab(settings.self_development_config,settings.self_development_ledger)
maintenance=Maintenance(str(state/"builds"),development,job_executor,jobs,NODE_ID)
mobile_access=MobileAccess(settings.mobile_access_ledger)
app=FastAPI(title="SolomonPrime",version="1.0.0")
mdns:Advertiser|None=None;discovery:DiscoveryLoop|None=None
controller_urls=list(settings.controller_candidates)

BASE_SYSTEM="""You are operating inside SolomonPrime, a local-first Home/Farm/research AI system. Be precise, evidence-aware, and explicit about uncertainty. Prefer non-destructive inspection before mutation. Never claim a system change occurred unless a tool result confirms it. Local/direct Ethernet is the preferred data path, then wired LAN, then local Wi-Fi, with Tailscale as encrypted remote/fallback connectivity. Hardware/resource scheduling decisions are constrained by deterministic safety and fit rules; LLM advice can improve choices but cannot override those constraints. Destructive storage, firewall, kernel, driver, credential, or broad permission changes require explicit approval. Preserve provenance and reversibility."""


def current_info()->dict[str,Any]:
    info=hardware_profile(NODE_ID,NODE_NAME,settings.port);info["role"]=settings.role;info["availability"]=read_availability()
    if settings.llm_endpoint:
        info["services"]["llm"]={"configured":True,"model_hint":settings.llm_model_hint}
        if "llm-worker" not in info["capabilities"]:info["capabilities"].append("llm-worker")
    broker_socket=Path(settings.job_broker_socket)
    if Path(settings.job_runner).exists() and broker_socket.exists():
        info["services"]["job_executor"]={"configured":True,"launcher":settings.job_runner,"broker_socket":settings.job_broker_socket}
        if "job-executor" not in info["capabilities"]:info["capabilities"].append("job-executor")
    edge=edge_devices.inventory();rf=rf_monitor.status()
    info["edge_extensions"]={"counts":edge.get("counts",{}),"policy":edge.get("policy",{}),"action_capabilities":edge_devices.action_capabilities()}
    info["rf_monitoring"]={"counts":rf.get("counts",{}),"capabilities":rf.get("capabilities",{}),"policy":rf.get("policy",{}),"recent_observations":(rf.get("observations") or [])[:10]}
    if settings.edge_discovery_enabled and "edge-discovery" not in info["capabilities"]:info["capabilities"].append("edge-discovery")
    if rf.get("capabilities",{}).get("receive_monitor_available") and "rf-receive" not in info["capabilities"]:info["capabilities"].append("rf-receive")
    return info


def require_public(request:Request)->None:
    if request.headers.get("authorization","")!=f"Bearer {public_key_text}":raise HTTPException(401,"invalid api key")

def require_mobile_scope(scope:str):
    def dependency(request:Request)->None:
        authorization=request.headers.get("authorization","")
        if authorization==f"Bearer {public_key_text}":return
        token=authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if not mobile_access.authorize(token,scope):raise HTTPException(401,"invalid or insufficient mobile credential")
    return dependency

async def require_mesh(request:Request)->bytes:
    body=await request.body();headers={k.lower():v for k,v in request.headers.items()}
    if not verify(cluster_key,request.method,request.url.path,body,headers,replay):raise HTTPException(401,"invalid mesh authentication")
    return body


def _llm_key()->str:
    p=Path(settings.llm_api_key_file) if settings.llm_api_key_file else None
    return p.read_text().strip() if p and p.exists() else ""


def _agent_for(model:str,user_text:str)->tuple[str,bool]:
    mode=MODEL_TO_AGENT.get(model,"auto")
    if mode=="reviewed":return "solomon-core",True
    if mode=="auto":return agents.route(user_text),False
    return mode,False


def _memory_context(user_text:str,agent:str)->str:
    domain=agents.domain(agent);rows=memory.search(user_text,agent=agent,domain=domain,limit=settings.memory_retrieval_limit)
    governed=knowledge.search(user_text,domain=domain,limit=settings.memory_retrieval_limit) if settings.knowledge_hybrid_enabled else []
    if not rows and not governed:return ""
    parts=[]
    for r in governed:
        citation=(r.get("citations") or [{}])[0]
        text=str(r.get("content","")).replace("\x00","")[:1200]
        parts.append(f"- [approved-knowledge/{r.get('domain')} score={r.get('score')} citation={citation.get('knowledge_id')} hash={citation.get('content_hash','')[:12]}] {text}")
    for r in rows:
        text=str(r.get("content","")).replace("\x00","")[:900]
        parts.append(f"- [{r.get('tier')}/{r.get('domain')} score={r.get('score')}] {text}")
    return "Relevant retrieved memory (use only when pertinent; provenance is preserved in the memory store):\n"+"\n".join(parts)


def _inject(payload:dict[str,Any],agent:str,user_text:str,extra:str="")->dict[str,Any]:
    p=copy.deepcopy(payload);messages=list(p.get("messages") or [])
    policy=agents.prompt(agent);mem=_memory_context(user_text,agent)
    system="\n\n".join(x for x in (BASE_SYSTEM,policy,mem,extra) if x)
    messages.insert(0,{"role":"system","content":system});p["messages"]=messages
    # The gateway model alias is not meaningful to the single loaded backend.
    p["model"]=settings.llm_model_hint or "local"
    return p


def _last_user(payload:dict[str,Any])->str:
    for m in reversed(payload.get("messages") or []):
        if m.get("role")=="user":
            c=m.get("content","")
            if isinstance(c,str):return c
    return ""


def _local_registry_node()->dict[str,Any]:
    n=registry.get(NODE_ID)
    if n:return n
    info=current_info();registry.upsert(info,role=settings.role,trust="trusted",source="local",endpoints=(info.get("network") or {}).get("paths") or []);return registry.get(NODE_ID) or {}


def _select_llm()->dict[str,Any]|None:
    nodes=[n for n in registry.list(settings.stale_after) if "llm-worker" in n.get("capabilities",[]) and n.get("trust")=="trusted" and n.get("health") in {"online","healthy"}]
    if settings.llm_endpoint and not any(n.get("node_id")==NODE_ID for n in nodes):nodes.append(_local_registry_node())
    if not nodes:return None
    w=Workload(kind="llm_inference",min_ram_gb=1)
    first=schedule_plan(nodes,w,local_node_id=NODE_ID)
    # For inference, deterministic local-first/resource fit is authoritative; avoid recursive LLM routing advice.
    return first.get("selected")


async def _nonstream_to_selected(payload:dict[str,Any],selected:dict[str,Any])->tuple[int,bytes,str]:
    nid=selected.get("node_id")
    if nid==NODE_ID:
        url=settings.llm_endpoint.rstrip("/")+"/chat/completions"
        async with httpx.AsyncClient(timeout=httpx.Timeout(240,read=None)) as c:r=await c.post(url,json=payload,headers=api_headers(settings.llm_api_key_file))
    else:
        endpoint=((selected.get("path") or {}).get("endpoint") or "").rstrip("/")
        if not endpoint:return 503,b'{"error":"selected node has no reachable endpoint"}',"application/json"
        body=json.dumps(payload,separators=(",",":")).encode();path="/v1/inference/chat/completions";headers={"Content-Type":"application/json",**sign(cluster_key,"POST",path,body)}
        async with httpx.AsyncClient(timeout=httpx.Timeout(240,read=None)) as c:r=await c.post(endpoint+path,content=body,headers=headers)
    return r.status_code,r.content,r.headers.get("content-type","application/json")


async def _stream_to_selected(payload:dict[str,Any],selected:dict[str,Any],on_complete:Callable[[str],None]|None=None):
    nid=selected.get("node_id")
    if nid==NODE_ID:
        url=settings.llm_endpoint.rstrip("/")+"/chat/completions";headers=api_headers(settings.llm_api_key_file);content=json.dumps(payload,separators=(",",":")).encode()
    else:
        endpoint=((selected.get("path") or {}).get("endpoint") or "").rstrip("/");path="/v1/inference/chat/completions";content=json.dumps(payload,separators=(",",":")).encode();url=endpoint+path;headers={"Content-Type":"application/json",**sign(cluster_key,"POST",path,content)}
    async def gen():
        acc=[]
        async with httpx.AsyncClient(timeout=httpx.Timeout(240,read=None)) as c:
            async with c.stream("POST",url,content=content,headers=headers) as r:
                if r.status_code>=400:
                    yield await r.aread();return
                async for line in r.aiter_lines():
                    if line.startswith("data: "):
                        data=line[6:]
                        if data!="[DONE]":
                            try:
                                d=json.loads(data);delta=d.get("choices",[{}])[0].get("delta",{}).get("content")
                                if delta:acc.append(delta)
                            except Exception:pass
                    yield (line+"\n\n").encode()
        if on_complete:
            try:on_complete("".join(acc))
            except Exception:pass
    return StreamingResponse(gen(),media_type="text/event-stream")


@app.get("/health")
def health():return {"status":"ok","node_id":NODE_ID,"role":settings.role,"version":"1.0.0","release":"home-rc4"}

@app.get("/v1/node/info")
def node_info():
    i=current_info();return {k:i[k] for k in ("node_id","name","role","capabilities","cpu","ram","gpus","network","services","timestamp")}

@app.get("/v1/controller/endpoints")
def controller_endpoints():
    if settings.role!="controller":raise HTTPException(404)
    return {"node_id":NODE_ID,"endpoints":((current_info().get("network") or {}).get("paths") or [])}

@app.post("/v1/mesh/heartbeat")
async def heartbeat(request:Request,body:bytes=Depends(require_mesh)):
    if settings.role!="controller":raise HTTPException(404)
    try:info=json.loads(body or b"{}")
    except Exception:raise HTTPException(400,"invalid json")
    profile=make_profile(info,llm_configured=bool((info.get("services") or {}).get("llm")))
    registry.upsert(info,role=str(info.get("role") or "node"),trust="trusted",source="signed-heartbeat",endpoints=((info.get("network") or {}).get("paths") or []),assigned_profile=profile)
    await asyncio.to_thread(
        audit.emit,
        "mesh.heartbeat",
        actor=str(info.get("node_id") or "node"),
        data={"profile": profile},
    )
    return {"ok":True,"assigned_profile":profile,"controller_endpoints":((registry.get(NODE_ID) or {}).get("endpoints") or [])}

def _normalized_node(n:dict[str,Any])->dict[str,Any]:
    """Keep the canonical snapshot and expose common telemetry consistently."""
    out=dict(n);snapshot=dict(out.get("snapshot") or {})
    for key in ("cpu","ram","gpus","mounts","block_devices"):
        if key not in out:out[key]=snapshot.get(key)
    return out


@app.get("/v1/nodes")
def nodes(_:None=Depends(require_public)):return {"nodes":[_normalized_node(n) for n in registry.list(settings.stale_after)]}

@app.post("/v1/nodes/{node_id}/trust")
async def trust_node(node_id:str,request:Request,_:None=Depends(require_public)):
    p=await request.json();trust=str(p.get("trust","pending"));ok=registry.set_trust(node_id,trust);audit.emit("node.trust",actor=str(p.get("by","operator")),data={"node_id":node_id,"trust":trust,"ok":ok});return {"ok":ok}

@app.post("/v1/scheduler/plan")
async def scheduler_plan(request:Request,_:None=Depends(require_public)):
    p=await request.json();w=Workload(**{k:v for k,v in p.items() if k in Workload.__dataclass_fields__});nodes=registry.list(settings.stale_after);result=schedule_plan(nodes,w,local_node_id=NODE_ID)
    # Bounded LLM tie-break only for non-inference placement.
    if settings.llm_advisor and w.kind!="llm_inference" and result.get("selected") and len(result.get("candidates") or [])>=2 and settings.llm_endpoint:
        adv=LLMAdvisor(settings.llm_endpoint,_llm_key()).suggest_node(result["workload"],result["candidates"])
        if adv:
            result["llm_advice"]=adv
            result=schedule_plan(nodes,w,local_node_id=NODE_ID,llm_preference=adv.get("node_id", ""));result["llm_advice"]=adv
    audit.emit("scheduler.plan",data=result);return result

@app.post("/v1/memory/remember")
async def remember(request:Request,_:None=Depends(require_public)):
    p=await request.json();res=memory.remember(str(p.get("content","")),tier=str(p.get("tier","semantic")),agent=str(p.get("agent","solomon-core")),domain=str(p.get("domain","general")),source=str(p.get("source","operator")),importance=float(p.get("importance",.5)),confidence=float(p.get("confidence",.8)),tags=str(p.get("tags","")));audit.emit("memory.remember",actor=str(p.get("agent","solomon-core")),data={"result":res});return res

@app.get("/v1/memory/search")
def memory_search(q:str,agent:str="",domain:str="",limit:int=6,_:None=Depends(require_public)):return {"results":memory.search(q,agent=agent,domain=domain,limit=min(max(limit,1),20))}

@app.get("/v1/memory/stats")
def memory_stats(_:None=Depends(require_public)):return memory.stats()

def _safe_is_dir(path:Path)->tuple[bool,bool]:
    """Return (exists_as_directory, probe_accessible) for optional paths."""
    try:return path.is_dir(),True
    except OSError:return False,False

@app.get("/v1/improvement/status")
def improvement_status(_:None=Depends(require_public)):
    """Truthful backend status for the current/future improvement dashboard."""
    if settings.role!="controller":raise HTTPException(404)
    plan=Path(settings.improvement_plan_path)
    vault=Path(settings.obsidian_vault_path)
    vault_exists,vault_accessible=_safe_is_dir(vault)
    mem=memory.stats();kstatus=knowledge.status()
    return {
        "plan":{
            "present":plan.is_file(),
            "path":str(plan),
            "phase":"v1-stable-governed-development",
        },
        "memory":{
            "state":"active_hybrid_with_lexical_fallback",
            "configured_backend":settings.memory_backend,
            "auto_capture":settings.auto_memory,
            "retrieval_limit":settings.memory_retrieval_limit,
            **mem,
        },
        "rag":{
            "state":"active",
            "lexical_fts5":bool((mem.get("retrieval") or {}).get("fts5")),
            "prompt_injection":True,
            "vector_embeddings":True,
            "vector_backend":settings.knowledge_vector_backend,
            "neural_semantic_embeddings":False,
            "hybrid_retrieval":True,
            "reranker":"weighted_lexical_vector_scope_confidence",
            "citation_objects":True,
            "lexical_fallback":True,
            "note":"The active offline vector signal is deterministic feature hashing, not a neural semantic model. Promotion to a neural embedding backend remains benchmark- and approval-gated.",
        },
        "knowledge":kstatus,
        "obsidian":{
            "state":"available_manual_governed" if settings.obsidian_enabled else "implemented_disabled",
            "enabled":settings.obsidian_enabled,
            "configured_request":settings.obsidian_enabled,
            "vault_path":str(vault),
            "vault_exists":vault_exists,
            "vault_probe_accessible":vault_accessible,
            "sync_mode":settings.obsidian_sync_mode,
            "note":"Manual imports always enter as untrusted drafts; only human-approved records are exported. Automatic bidirectional sync is disabled.",
        },
        "dashboard":{
            "status_api":True,
            "visual_improvement_workspace":"active",
            "path":"/admin",
            "chat_workspace":"http://CONTROLLER-IP:3000",
            "open_webui_integration":"persistent_supported_banner_link",
            "panels":[
                "overview","fleet","models","edge devices","goals","jobs","experiments","knowledge governance",
                "approvals","TED FinOps and observability",
            ],
        },
    }

@app.post("/v1/knowledge")
async def knowledge_create(request:Request,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    p=await request.json()
    try:result=knowledge.create(dict(p or {}))
    except ValueError as e:raise HTTPException(400,str(e))
    audit.emit("knowledge.create",actor=str(p.get("author") or "operator"),data={"id":result.get("id"),"state":result.get("state")});return result

@app.get("/v1/knowledge")
def knowledge_list(state:str="",domain:str="",limit:int=100,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    return {"records":knowledge.list(state=state,domain=domain,limit=limit)}

@app.get("/v1/knowledge/search")
def knowledge_search(q:str,domain:str="",limit:int=8,include_drafts:bool=False,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    states=("approved","review","draft") if include_drafts else ("approved",)
    return {"results":knowledge.search(q,domain=domain,limit=limit,states=states),"default_scope":"approved_only"}

@app.get("/v1/knowledge/contradictions/list")
def contradiction_list(state:str="open",limit:int=100,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    return {"contradictions":knowledge.contradictions(state=state,limit=limit)}

@app.post("/v1/knowledge/contradictions/{contradiction_id}/resolve")
async def contradiction_resolve(contradiction_id:str,request:Request,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    p=await request.json()
    try:result=knowledge.resolve_contradiction(contradiction_id,resolution=str(p.get("resolution") or ""),actor=str(p.get("actor") or ""))
    except ValueError as e:raise HTTPException(400,str(e))
    if not result:raise HTTPException(404,"contradiction not found")
    audit.emit("knowledge.contradiction.resolve",actor=str(p.get("actor") or "operator"),data={"id":contradiction_id});return result

@app.get("/v1/knowledge/consolidation/preview")
def consolidation_preview(older_days:int=180,max_importance:float=.25,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    return knowledge.consolidation_preview(older_days=older_days,max_importance=max_importance)

@app.post("/v1/knowledge/evaluations")
async def evaluation_create(request:Request,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    p=await request.json()
    try:result=knowledge.evaluate(str(p.get("name") or ""),list(p.get("cases") or []),actor=str(p.get("actor") or "operator"),k=int(p.get("k") or 5))
    except (TypeError,ValueError) as e:raise HTTPException(400,str(e))
    audit.emit("knowledge.evaluation",actor=str(p.get("actor") or "operator"),data={"id":result["id"],"gate_passed":result["gate_passed"]});return result

@app.get("/v1/knowledge/evaluations")
def evaluation_list(limit:int=50,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    return {"evaluations":knowledge.evaluations(limit)}

@app.get("/v1/knowledge/{knowledge_id}")
def knowledge_get(knowledge_id:str,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    result=knowledge.get(knowledge_id)
    if not result:raise HTTPException(404,"knowledge record not found")
    return result

@app.post("/v1/knowledge/{knowledge_id}/state")
async def knowledge_state(knowledge_id:str,request:Request,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    p=await request.json()
    try:result=knowledge.transition(knowledge_id,str(p.get("state") or ""),actor=str(p.get("actor") or ""),note=str(p.get("note") or ""))
    except ValueError as e:raise HTTPException(400,str(e))
    if not result:raise HTTPException(404,"knowledge record not found")
    audit.emit("knowledge.state",actor=str(p.get("actor") or "operator"),data={"id":knowledge_id,"state":result.get("state")});return result

@app.post("/v1/knowledge/obsidian/export")
def obsidian_export(_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    if not settings.obsidian_enabled or settings.obsidian_sync_mode!="manual":raise HTTPException(409,"manual Obsidian bridge is not enabled")
    try:result=obsidian.export_approved()
    except (OSError,ValueError) as e:raise HTTPException(409,f"vault unavailable: {e}")
    audit.emit("knowledge.obsidian.export",actor="operator",data={"count":result["count"]});return result

@app.post("/v1/knowledge/obsidian/import")
async def obsidian_import(request:Request,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    if not settings.obsidian_enabled or settings.obsidian_sync_mode!="manual":raise HTTPException(409,"manual Obsidian bridge is not enabled")
    p=await request.json()
    try:result=obsidian.import_draft(str(p.get("path") or ""),actor=str(p.get("actor") or "operator"))
    except (OSError,ValueError) as e:raise HTTPException(400,str(e))
    audit.emit("knowledge.obsidian.import",actor=str(p.get("actor") or "operator"),data={"id":result.get("id"),"path":p.get("path")});return result

WEB_ROOT=Path(__file__).with_name("web")

@app.get("/admin",response_class=FileResponse)
def admin_workspace():
    return FileResponse(WEB_ROOT/"admin.html",media_type="text/html",headers={"Cache-Control":"no-store"})

@app.get("/admin/admin.css",response_class=FileResponse)
def admin_styles():
    return FileResponse(WEB_ROOT/"admin.css",media_type="text/css")

@app.get("/admin/admin.js",response_class=FileResponse)
def admin_script():
    return FileResponse(WEB_ROOT/"admin.js",media_type="text/javascript",headers={"Cache-Control":"no-store"})

@app.get("/v1/improvement/dashboard",include_in_schema=False)
def improvement_dashboard():
    return RedirectResponse("/admin",status_code=307)

@app.post("/v1/storage/scan")
async def storage_scan(request:Request,_:None=Depends(require_public)):
    p=await request.json();roots=list(p.get("roots") or ["/apps"]);res=await asyncio.to_thread(storage.scan,roots,min_size=int(p.get("min_size",1)),max_files=int(p.get("max_files",0)));audit.emit("storage.scan",actor="storage-steward",data=res);return res

@app.get("/v1/storage/duplicates")
def storage_duplicates(_:None=Depends(require_public)):return storage.duplicate_plan()

@app.get("/v1/storage/layout")
def storage_layout(_:None=Depends(require_public)):return storage.classify_layout(current_info().get("block_devices") or [])


# --- Goal Engine -----------------------------------------------------------
@app.post("/v1/goals")
async def goal_create(request:Request,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    try:p=await request.json();g=goals.create(dict(p or {}),actor=str((p or {}).get("owner") or "operator"))
    except ValueError as e:raise HTTPException(400,str(e))
    audit.emit("goal.create",actor=str(g.get("owner") or "operator"),data={"goal_id":g.get("id"),"name":g.get("name"),"status":g.get("status")})
    return g

@app.get("/v1/goals")
def goal_list(status:str="",limit:int=100,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    return {"goals":goals.list(status=status,limit=limit)}

@app.get("/v1/goals/{goal_id}")
def goal_get(goal_id:str,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    g=goals.get(goal_id)
    if not g:raise HTTPException(404,"goal not found")
    return g

@app.post("/v1/goals/{goal_id}/status")
async def goal_status(goal_id:str,request:Request,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    p=await request.json()
    try:g=goals.update_status(goal_id,str(p.get("status") or ""),actor=str(p.get("actor") or "operator"),note=str(p.get("note") or ""))
    except ValueError as e:raise HTTPException(400,str(e))
    if not g:raise HTTPException(404,"goal not found")
    audit.emit("goal.status",actor=str(p.get("actor") or "operator"),data={"goal_id":goal_id,"status":g.get("status")})
    return g

@app.post("/v1/goals/{goal_id}/relationships")
async def goal_relationship(goal_id:str,request:Request,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    p=await request.json()
    try:r=goals.relate(goal_id,str(p.get("relation") or ""),str(p.get("target_goal") or ""),explanation=str(p.get("explanation") or ""))
    except ValueError as e:raise HTTPException(400,str(e))
    audit.emit("goal.relationship",actor=str(p.get("actor") or "operator"),data=r);return r

@app.get("/v1/goals/{goal_id}/events")
def goal_events(goal_id:str,limit:int=100,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    return {"events":goals.events(goal_id,limit)}

# --- Governed Edge Devices -----------------------------------------------
@app.get("/v1/edge-devices")
def edge_device_list(_:None=Depends(require_public)):
    return edge_devices.inventory()

@app.get("/v1/edge-devices/discovery/preview")
def edge_device_discovery_preview(_:None=Depends(require_public)):
    return edge_devices.discovery_preview()

@app.post("/v1/edge-devices/discovery/scan")
async def edge_device_discovery_scan(request:Request,_:None=Depends(require_public)):
    p=await request.json()
    if p.get("confirmed") is not True or not str(p.get("actor") or "").strip():raise HTTPException(400,"confirmed operator identity is required")
    result=await asyncio.to_thread(edge_devices.scan,bluetooth=bool(p.get("bluetooth",True)),bluetooth_timeout=settings.edge_bluetooth_scan_seconds,rssi_threshold=settings.edge_bluetooth_nearby_rssi)
    audit.emit("edge-device.scan",actor=str(p.get("actor")),data={"usb":result.get("usb"),"bluetooth":result.get("bluetooth")})
    return result

@app.post("/v1/edge-devices/discoveries/{fingerprint}/decision")
async def edge_device_discovery_decision(fingerprint:str,request:Request,_:None=Depends(require_public)):
    p=await request.json()
    try:d=edge_devices.decide(fingerprint,str(p.get("decision") or ""),actor=str(p.get("actor") or ""),note=str(p.get("note") or ""),confirmed=p.get("confirmed") is True)
    except ValueError as e:raise HTTPException(400,str(e))
    audit.emit("edge-device.discovery-decision",actor=str(p.get("actor")),data={"fingerprint":fingerprint,"decision":d.get("decision")})
    return d

@app.get("/v1/edge-devices/actions")
def edge_device_actions(_:None=Depends(require_public)):
    return edge_devices.actions()

@app.get("/v1/skills")
def skills_catalog(_:None=Depends(require_public)):
    return {"tools":READONLY_TOOLS+EXECUTION_TOOLS,"approval_authority":"Admin only"}

@app.get("/v1/edge-devices/{fingerprint}/lab-plan")
def device_lab_plan(fingerprint:str,_:None=Depends(require_public)):
    try:return edge_devices.lab_plan(fingerprint)
    except ValueError as exc:raise HTTPException(404,str(exc))

@app.post("/v1/edge-devices/actions")
async def edge_device_action_request(request:Request,_:None=Depends(require_public)):
    p=await request.json()
    try:a=edge_devices.request_action(str(p.get("fingerprint") or ""),str(p.get("action") or ""),actor=str(p.get("actor") or ""),note=str(p.get("note") or ""),parameters=dict(p.get("parameters") or {}),ttl_seconds=int(p.get("ttl_seconds") or 900))
    except (ValueError,TypeError) as e:raise HTTPException(400,str(e))
    audit.emit("edge-device.action-request",actor=str(p.get("actor")),data={"id":a.get("id"),"fingerprint":a.get("fingerprint"),"action":a.get("action"),"plan_hash":hashlib.sha256(json.dumps(a.get("parameters") or {},sort_keys=True).encode()).hexdigest()})
    return a

@app.post("/v1/edge-devices/actions/{action_id}/decision")
async def edge_device_action_decision(action_id:str,request:Request,_:None=Depends(require_public)):
    p=await request.json()
    try:a=edge_devices.decide_action(action_id,str(p.get("decision") or ""),actor=str(p.get("actor") or ""),note=str(p.get("note") or ""),confirmed=p.get("confirmed") is True)
    except ValueError as e:raise HTTPException(400,str(e))
    audit.emit("edge-device.action-decision",actor=str(p.get("actor")),data={"id":action_id,"decision":a.get("state")})
    return a

@app.post("/v1/edge-devices/actions/{action_id}/execute")
async def edge_device_action_execute(action_id:str,request:Request,_:None=Depends(require_public)):
    p=await request.json()
    try:a=await asyncio.to_thread(edge_devices.execute_action,action_id,actor=str(p.get("actor") or ""),confirmed=p.get("confirmed") is True)
    except ValueError as e:raise HTTPException(400,str(e))
    audit.emit("edge-device.action-execute",actor=str(p.get("actor")),data={"id":action_id,"state":a.get("state"),"result":a.get("result")})
    return a

@app.post("/v1/edge-devices/{device_id}/state")
async def edge_device_state(device_id:str,request:Request,_:None=Depends(require_public)):
    p=await request.json()
    try:
        d=edge_devices.transition(device_id,str(p.get("state") or ""),actor=str(p.get("actor") or ""),note=str(p.get("note") or ""),confirmed=p.get("confirmed") is True)
    except ValueError as e:raise HTTPException(400,str(e))
    audit.emit("edge-device.state",actor=str(p.get("actor")),data={"device_id":device_id,"state":d.get("state")})
    return d

# --- RF receive monitoring ------------------------------------------------
@app.get("/v1/rf/status")
def rf_status(_:None=Depends(require_public)):return {"node_id":NODE_ID,"name":NODE_NAME,**rf_monitor.status()}

@app.post("/v1/rf/scan")
async def rf_scan(request:Request,_:None=Depends(require_public)):
    p=await request.json()
    if p.get("confirmed") is not True or not str(p.get("actor") or "").strip():raise HTTPException(400,"confirmed operator identity is required")
    result=await asyncio.to_thread(rf_monitor.scan_receive,int(p.get("seconds") or settings.rf_receive_window))
    audit.emit("rf.receive-scan",actor=str(p.get("actor")),data={k:v for k,v in result.items() if k!="stderr_tail"})
    return result

@app.get("/v1/rf/fleet")
def rf_fleet(_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    nodes=[]
    for n in registry.list(settings.stale_after):
        snap=n.get("snapshot") or {}
        nodes.append({"node_id":n.get("node_id"),"name":n.get("name"),"health":n.get("health"),"trust":n.get("trust"),"edge_extensions":snap.get("edge_extensions") or {},"rf_monitoring":snap.get("rf_monitoring") or {}})
    return {"nodes":nodes,"policy":{"controller_aggregates_signed_heartbeats":True,"remote_transmit":False}}

@app.get("/v1/documentation")
def documentation(_:None=Depends(require_public)):
    path=Path(settings.admin_docs_path)
    try:data=__import__("yaml").safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError,ValueError):data={"title":"SolomonPrime Operations Guide","sections":[]}
    return {"path":str(path),"editable_on_host":True,**data}

@app.get("/v1/voice/status")
def voice_status(_:None=Depends(require_public)):return voice_security.status()

def _voice_secure_context(request:Request)->bool:
    # Do not trust forwarded headers from arbitrary LAN clients. A reverse
    # proxy must terminate TLS so the application receives an HTTPS scheme.
    peer=(request.client.host if request.client else "")
    return request.url.scheme=="https" or peer in {"127.0.0.1","::1"}

@app.post("/v1/voice/approval-challenge")
async def voice_challenge(request:Request,_:None=Depends(require_mobile_scope("voice"))):
    if not _voice_secure_context(request):
        raise HTTPException(426,"Voice approval challenges require HTTPS or a loopback client")
    p=await request.json()
    action_id=str(p.get("action_id") or "")
    action=next((x for x in edge_devices.actions().get("actions",[]) if x.get("id")==action_id),None)
    if not action or action.get("state") not in {"pending","approved"}:
        raise HTTPException(400,"voice challenge must reference an existing pending or approved device action")
    try:result=voice_security.challenge(str(p.get("action_id") or ""),str(p.get("device_session") or ""))
    except ValueError as exc:raise HTTPException(400,str(exc))
    audit.emit("voice.challenge",actor=str(p.get("actor") or "operator"),data={k:v for k,v in result.items() if k!="phrase"})
    return result

@app.post("/v1/voice/device-session")
async def voice_device_session(request:Request,_:None=Depends(require_mobile_scope("voice"))):
    if not _voice_secure_context(request):raise HTTPException(426,"Voice device sessions require HTTPS or a loopback client")
    p=await request.json()
    if p.get("confirmed") is not True:raise HTTPException(400,"confirmed=true is required")
    try:result=voice_security.issue_session(str(p.get("actor") or ""),str(p.get("device_id") or ""),int(p.get("ttl_seconds") or 900))
    except ValueError as exc:raise HTTPException(400,str(exc))
    audit.emit("voice.device-session",actor=str(p.get("actor") or "operator"),data={"device_id":result["device_id"],"expires":result["expires"]})
    return result

@app.post("/v1/voice/verify-challenge")
async def voice_verify_challenge(request:Request,challenge_id:str=Form(...),action_id:str=Form(...),device_session:str=Form(...),transcript:str=Form(...),file:UploadFile=File(...),_:None=Depends(require_mobile_scope("voice"))):
    if not _voice_secure_context(request):raise HTTPException(426,"Voice verification requires HTTPS or a loopback client")
    try:result=await asyncio.to_thread(voice_security.verify_challenge,challenge_id,action_id,device_session,transcript,await file.read(),Path(file.filename or "voice.wav").suffix.lower())
    except ValueError as exc:raise HTTPException(400,str(exc))
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    audit.emit("voice.verify",actor="voice-device",data=result)
    return result

@app.post("/v1/audio/transcriptions")
async def audio_transcription(file:UploadFile=File(...),model:str=Form("whisper"),_:None=Depends(require_mobile_scope("audio"))):
    try:text=await asyncio.to_thread(voice_security.transcribe,await file.read(),Path(file.filename or "audio.wav").suffix.lower())
    except ValueError as exc:raise HTTPException(400,str(exc))
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    return {"text":text,"model":model,"local":True}

@app.post("/v1/audio/speech")
async def audio_speech(request:Request,_:None=Depends(require_mobile_scope("audio"))):
    p=await request.json()
    try:audio=await asyncio.to_thread(voice_security.synthesize,str(p.get("input") or ""))
    except ValueError as exc:raise HTTPException(400,str(exc))
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    return Response(audio,media_type="audio/wav",headers={"Cache-Control":"no-store"})

@app.get("/v1/calendars/status")
def calendar_status(_:None=Depends(require_public)):return calendar_pull.status()

@app.get("/v1/calendars/events")
def calendar_events(limit:int=200,_:None=Depends(require_public)):return {"events":calendar_pull.events(limit),"cloud_export":False}

@app.post("/v1/calendars/sync")
async def calendar_sync(request:Request,_:None=Depends(require_public)):
    p=await request.json();actor=str(p.get("actor") or "").strip()
    if not actor or p.get("confirmed") is not True:raise HTTPException(400,"actor and confirmed=true are required")
    result=await asyncio.to_thread(calendar_pull.sync);audit.emit("calendar.sync",actor=actor,data=result);return result

@app.get("/v1/development/status")
def development_status(_:None=Depends(require_public)):
    cfg=development.config()
    return {"enabled":bool(cfg.get("enabled")),"repositories":development.repositories(),
            "proposals":development.list(),"builds":maintenance.list(),"policy":cfg.get("policy") or {}}

@app.get("/v1/mobile/devices")
def mobile_devices(_:None=Depends(require_public)):return {"devices":mobile_access.list(),"tokens_displayed":False}

@app.post("/v1/mobile/devices")
async def mobile_enroll(request:Request,_:None=Depends(require_public)):
    p=await request.json()
    if p.get("confirmed") is not True or not str(p.get("actor") or "").strip():raise HTTPException(400,"confirmed operator identity is required")
    try:result=mobile_access.issue(str(p.get("device_id") or ""),str(p.get("label") or "Flip5 Tricorder"),list(p.get("scopes") or []))
    except ValueError as exc:raise HTTPException(400,str(exc))
    audit.emit("mobile.enroll",actor=str(p["actor"]),data={k:v for k,v in result.items() if k!="token"})
    return result

@app.post("/v1/mobile/devices/{device_id}/revoke")
async def mobile_revoke(device_id:str,request:Request,_:None=Depends(require_public)):
    p=await request.json()
    if p.get("confirmed") is not True or not str(p.get("actor") or "").strip():raise HTTPException(400,"confirmed operator identity is required")
    ok=mobile_access.revoke(device_id);audit.emit("mobile.revoke",actor=str(p["actor"]),data={"device_id":device_id,"ok":ok});return {"ok":ok}

@app.post("/v1/development/read")
async def development_read(request:Request,_:None=Depends(require_public)):
    p=await request.json()
    try:return development.read(str(p.get("repository") or ""),str(p.get("path") or ""))
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.post("/v1/development/search")
async def development_search(request:Request,_:None=Depends(require_public)):
    p=await request.json()
    try:return development.search(str(p.get("repository") or ""),str(p.get("query") or ""),int(p.get("limit") or 100))
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.post("/v1/development/proposals")
async def development_propose(request:Request,_:None=Depends(require_public)):
    p=await request.json()
    try:result=development.propose(str(p.get("repository") or ""),str(p.get("title") or ""),str(p.get("patch") or ""),str(p.get("actor") or "solomon-core"))
    except ValueError as exc:raise HTTPException(400,str(exc))
    audit.emit("development.propose",actor=result.get("actor","solomon-core"),data={k:v for k,v in result.items() if k!="patch"})
    return result

@app.post("/v1/development/proposals/{proposal_id}/validate")
async def development_validate(proposal_id:str,_:None=Depends(require_public)):
    try:result=await asyncio.to_thread(development.validate,proposal_id)
    except ValueError as exc:raise HTTPException(400,str(exc))
    audit.emit("development.validate",actor="solomon-core",data=result)
    return result

@app.post("/v1/development/proposals/{proposal_id}/request-apply")
async def development_request_apply(proposal_id:str,request:Request,_:None=Depends(require_public)):
    p=await request.json();proposal=development.get(proposal_id,include_patch=False)
    if not proposal or proposal.get("state")!="validated":raise HTTPException(400,"validated proposal not found")
    payload={"proposal_id":proposal_id,"repository":proposal["repository"],"patch_sha256":proposal["patch_sha256"]}
    approval=approvals.request(actor=str(p.get("actor") or "solomon-core"),action="development.apply",payload=payload,risk="mutating")
    audit.emit("approval.request",actor=approval["actor"],data=approval)
    return approval

@app.post("/v1/development/proposals/{proposal_id}/apply")
async def development_apply(proposal_id:str,request:Request,_:None=Depends(require_public)):
    p=await request.json();proposal=development.get(proposal_id,include_patch=False)
    expected={"proposal_id":proposal_id,"repository":proposal.get("repository") if proposal else "","patch_sha256":proposal.get("patch_sha256") if proposal else ""}
    approval=approvals.get(str(p.get("approval_id") or "")) if p.get("approval_id") else approvals.find_approved(action="development.apply",payload=expected)
    if not approval or approval.get("state")!="approved" or approval.get("action")!="development.apply" or approval.get("payload")!=expected:
        raise HTTPException(403,"a matching approved development.apply request is required")
    if not approvals.consume(approval["id"],action="development.apply",payload=expected):raise HTTPException(403,"approval expired or already consumed")
    try:result=await asyncio.to_thread(development.apply,proposal_id,expected["patch_sha256"])
    except ValueError as exc:raise HTTPException(400,str(exc))
    audit.emit("development.apply",actor=str(approval.get("approved_by") or "operator"),data=result)
    return result

@app.post("/v1/development/test/{repository_id}")
async def development_test(repository_id:str,_:None=Depends(require_public)):
    try:result=await asyncio.to_thread(maintenance.start,repository_id)
    except ValueError as exc:raise HTTPException(400,str(exc))
    audit.emit("development.test",actor="solomon-core",data={"repository":repository_id,"state":result.get("state")})
    return result

@app.get("/v1/development/builds/{build_id}")
def development_build_status(build_id:str,_:None=Depends(require_public)):
    try:return maintenance.status(build_id)
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.get("/v1/development/builds/{build_id}/archive")
def development_build_download(build_id:str,_:None=Depends(require_public)):
    try:result=maintenance.status(build_id)
    except ValueError as exc:raise HTTPException(400,str(exc))
    if result["state"]!="package_ready":raise HTTPException(409,"build package is not ready")
    return FileResponse(result["archive_path"],filename=build_id+".tar.gz",media_type="application/gzip")

@app.get("/v1/integration/status")
def integration_status(_:None=Depends(require_public)):
    checks={"solomonprime_api":{"state":"healthy","version":"1.0.0","endpoint":"http://127.0.0.1:8765"},"admin_workspace":{"state":"healthy","path":"/admin"}}
    if settings.role=="controller":
        try:
            r=httpx.get("http://127.0.0.1:3000/api/version",timeout=2);body=r.json() if r.status_code==200 else {}
            checks["open_webui"]={"state":"healthy" if r.status_code==200 else "degraded","http_status":r.status_code,"version":body.get("version")}
        except Exception as exc:checks["open_webui"]={"state":"unreachable","error":type(exc).__name__}
        env=Path("/etc/solomonprime/open-webui.env")
        try:linked="/admin" in env.read_text(encoding="utf-8",errors="replace")
        except OSError:linked=False
        checks["open_webui_admin_link"]={"state":"configured" if linked else "not_verified","secrets_exposed":False}
    else:checks["open_webui"]={"state":"not_applicable_on_node"}
    checks["local_inference"]={"state":"configured" if settings.llm_endpoint else "not_configured","endpoint_configured":bool(settings.llm_endpoint),"model_hint":settings.llm_model_hint or None}
    ollama_state=local_models.inventory().get("ollama_runtime") or {}
    checks["ollama"]={"state":ollama_state.get("state","unknown"),"endpoint":ollama_state.get("endpoint"),"reason":ollama_state.get("reason")}
    checks["tool_bridge"]={"state":tool_self_test(None).get("state","failed"),"schema":"/v1/tools/openapi.json"}
    checks["voice"]={"state":voice_security.status().get("state","unknown"),"https_required":True}
    checks["calendars"]={"state":"configured" if calendar_pull.status().get("enabled") else "not_configured","providers":calendar_pull.status().get("providers")}
    checks["development_lab"]={"state":"enabled" if development.config().get("enabled") else "disabled","repositories":development.repositories()}
    checks["edge_discovery"]={"state":"enabled" if settings.edge_discovery_enabled else "disabled","pending":edge_devices.inventory().get("counts",{}).get("pending_approval",0)}
    checks["rf_receive"]={"state":"enabled" if settings.rf_monitor_enabled else "disabled","backend_available":rf_monitor.capabilities().get("receive_monitor_available",False)}
    return {"node_id":NODE_ID,"role":settings.role,"checks":checks,"functional":checks["solomonprime_api"]["state"]=="healthy" and (settings.role!="controller" or checks["open_webui"].get("state")=="healthy")}

# --- Experiment Ledger ----------------------------------------------------
@app.post("/v1/experiments")
async def experiment_create(request:Request,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    p=await request.json()
    gid=str(p.get("goal_id") or "")
    if gid and not goals.get(gid):raise HTTPException(400,"goal_id does not exist")
    try:e=experiments.create(dict(p or {}))
    except ValueError as ex:raise HTTPException(400,str(ex))
    audit.emit("experiment.create",actor=str(p.get("actor") or "research-simulation"),data={"experiment_id":e.get("id"),"goal_id":gid,"manifest_hash":e.get("manifest_hash")})
    return e

@app.get("/v1/experiments")
def experiment_list(goal_id:str="",limit:int=100,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    return {"experiments":experiments.list(goal_id=goal_id,limit=limit)}

@app.get("/v1/experiments/{experiment_id}")
def experiment_get(experiment_id:str,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    e=experiments.get(experiment_id)
    if not e:raise HTTPException(404,"experiment not found")
    return e

# --- Distributed bounded Job Executor ------------------------------------
def _job_workload(m:dict[str,Any])->Workload:
    r=dict(m.get("resources") or {})
    minimum_ram=max(float(r.get("min_ram_gb") or .5),float(r.get("max_memory_gb") or .25))
    return Workload(
        kind=str(m.get("workload_kind") or m.get("kind") or "job"),
        min_ram_gb=minimum_ram,
        min_gpu_vram_gb=float(r.get("min_gpu_vram_gb") or 0),
        preferred_gpu_vendor=str(r.get("preferred_gpu_vendor") or ""),
        requires_gpu=bool(r.get("requires_gpu",False) or float(r.get("min_gpu_vram_gb") or 0)>0),
        locality_node_id=str(r.get("locality_node_id") or ""),
        stateful=bool(m.get("stateful",False)),
        priority=str(m.get("priority") or "background"),
        max_cpu_util_pct=float(r.get("max_cpu_util_pct") or 90),
    )

async def _dispatch_job(m:dict[str,Any])->dict[str,Any]:
    try:m=JobExecutor.validate(dict(m))
    except ValueError as e:raise HTTPException(400,str(e))
    gid=str(m.get("goal_id") or "");eid=str(m.get("experiment_id") or "")
    if gid and not goals.get(gid):raise HTTPException(400,"goal_id does not exist")
    if eid and not experiments.get(eid):raise HTTPException(400,"experiment_id does not exist")
    w=_job_workload(m);eligible=[n for n in registry.list(settings.stale_after) if "job-executor" in (n.get("capabilities") or [])];plan=schedule_plan(eligible,w,local_node_id=NODE_ID)
    selected=plan.get("selected")
    if not selected:raise HTTPException(409,"no trusted healthy node satisfies the job requirements")
    jid=str(m.get("job_id") or new_job_id());m["job_id"]=jid
    endpoint=str(((selected.get("path") or {}).get("endpoint") or "")).rstrip("/")
    nid=str(selected.get("node_id") or "")
    # Resource state is revalidated by the same deterministic scheduler immediately before dispatch.
    if nid==NODE_ID:
        try:job=job_executor.submit(jid,m,node_id=NODE_ID)
        except ValueError as e:raise HTTPException(400,str(e))
    else:
        if not endpoint:raise HTTPException(503,"selected node has no reachable endpoint")
        body=json.dumps(m,separators=(",",":"),default=str).encode();path="/v1/mesh/jobs/submit";headers={"Content-Type":"application/json",**sign(cluster_key,"POST",path,body)}
        async with httpx.AsyncClient(timeout=20) as c:r=await c.post(endpoint+path,content=body,headers=headers)
        if r.status_code>=400:raise HTTPException(r.status_code,f"worker rejected job: {r.text[:500]}")
        jobs.create(jid,m,node_id=nid,endpoint=endpoint,status="queued");job=r.json()
    if eid:experiments.bind_job(eid,job_id=jid,node_id=nid)
    audit.emit("job.dispatch",actor=str(m.get("actor") or "research-simulation"),data={"job_id":jid,"goal_id":gid,"experiment_id":eid,"node_id":nid,"path":selected.get("path"),"manifest_hash":jobs.get(jid).get("manifest_hash") if jobs.get(jid) else ""})
    return {"job":job,"placement":selected,"policy":plan.get("policy")}

@app.post(
    "/v1/jobs/submit",
    response_model=JobSubmitResponse,
    responses={202:{"model":ApprovalRequiredResponse,"description":"Human approval is required"}},
)
async def job_submit(payload:JobSubmitRequest,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    p=payload.model_dump(exclude_none=True)
    risk=str(p.get("risk") or "reversible")
    if risk not in AUTO_RISKS:
        approval=approvals.request(actor=str(p.get("actor") or "solomon-core"),action="job.submit",payload={k:v for k,v in p.items() if k!="source"},risk=risk)
        audit.emit("approval.request",actor=approval["actor"],data=approval)
        return Response(json.dumps({"state":"approval_required","approval":approval,"note":"v0.3 bounded executor intentionally does not execute mutating/destructive jobs"}),status_code=202,media_type="application/json")
    return await _dispatch_job(p)

@app.get("/v1/jobs")
def job_list(limit:int=100,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    return {"jobs":jobs.list(limit)}

async def _refresh_remote_job(j:dict[str,Any])->dict[str,Any]:
    if not j or j.get("node_id")==NODE_ID or not j.get("endpoint"):return j
    path=f"/v1/mesh/jobs/{j['id']}";headers=sign(cluster_key,"GET",path,b"")
    try:
        async with httpx.AsyncClient(timeout=8) as c:r=await c.get(str(j["endpoint"]).rstrip("/")+path,headers=headers)
        if r.status_code==200:
            remote=r.json();jobs.update(j["id"],status=remote.get("status"),started=remote.get("started"),finished=remote.get("finished"),exit_code=remote.get("exit_code"),result=remote.get("result") or {},error=remote.get("error") or "");return jobs.get(j["id"]) or remote
    except Exception:pass
    return j

@app.get("/v1/jobs/{job_id}")
async def job_get(job_id:str,_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    j=jobs.get(job_id)
    if not j:raise HTTPException(404,"job not found")
    j=await _refresh_remote_job(j)
    if j.get("experiment_id"):experiments.update_from_job(str(j.get("experiment_id")),j)
    return j

# Signed node-local job interface. No public API key can invoke this directly.
@app.post("/v1/mesh/jobs/submit")
async def mesh_job_submit(request:Request,body:bytes=Depends(require_mesh)):
    if not read_availability()["accepting_jobs"]:raise HTTPException(409,"worker unavailable")
    try:m=json.loads(body or b"{}")
    except Exception:raise HTTPException(400,"invalid json")
    jid=str(m.get("job_id") or new_job_id())
    try:j=job_executor.submit(jid,m,node_id=NODE_ID)
    except ValueError as e:raise HTTPException(400,str(e))
    audit.emit("job.accept",actor="mesh-controller",data={"job_id":jid,"kind":m.get("kind"),"risk":m.get("risk")})
    return j

@app.get("/v1/mesh/jobs/{job_id}")
async def mesh_job_get(job_id:str,_:bytes=Depends(require_mesh)):
    j=jobs.get(job_id)
    if not j:raise HTTPException(404,"job not found")
    return j

@app.get("/v1/approvals/pending")
def pending(_:None=Depends(require_public)):return {"approvals":approvals.list_pending()}

@app.post("/v1/approvals/request")
async def request_approval(request:Request,_:None=Depends(require_public)):
    p=await request.json();res=approvals.request(actor=str(p.get("actor","solomon-core")),action=str(p.get("action","")),payload=dict(p.get("payload") or {}),risk=str(p.get("risk","mutating")));audit.emit("approval.request",actor=res["actor"],data=res);return res

@app.post("/v1/approvals/{aid}/approve")
async def approve(aid:str,request:Request,_:None=Depends(require_public)):
    p=await request.json();ok=approvals.approve(aid,by=str(p.get("by","operator")),note=str(p.get("note","")));audit.emit("approval.approve",actor=str(p.get("by","operator")),data={"id":aid,"ok":ok});return {"ok":ok}

# Node-local inference adapter; only signed cluster calls can use it.
@app.post("/v1/mesh/host/inspect")
async def mesh_host_inspect(request:Request,body:bytes=Depends(require_mesh)):
    try:
        payload=json.loads(body)
        return await asyncio.to_thread(inspect_host,str(payload.get("skill","")))
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))

async def host_inspect_on_node(node_id:str,skill:str):
    if skill not in HOST_COMMANDS:raise ValueError("unknown host inspection skill")
    if node_id==NODE_ID:return await asyncio.to_thread(inspect_host,skill)
    from .scheduler import choose_endpoint
    node=next((n for n in registry.list(settings.stale_after) if n["node_id"]==node_id and n["trust"]=="trusted" and n["health"]=="online"),None)
    if not node:raise ValueError("trusted online node not found")
    endpoint=choose_endpoint(node,NODE_ID)
    if not endpoint:raise ValueError("node not reachable")
    path="/v1/mesh/host/inspect";body=json.dumps({"skill":skill}).encode()
    async with httpx.AsyncClient(timeout=15) as client:
        result=await client.post(endpoint["endpoint"].rstrip("/")+path,content=body,headers={"Content-Type":"application/json",**sign(cluster_key,"POST",path,body)})
    result.raise_for_status()
    return {"node_id":node_id,**result.json()}

@app.get("/v1/inference/models")
async def inference_models(_:bytes=Depends(require_mesh)):
    if not settings.llm_endpoint:raise HTTPException(503,"no local inference configured")
    async with httpx.AsyncClient(timeout=20) as c:r=await c.get(settings.llm_endpoint.rstrip("/")+"/models",headers=api_headers(settings.llm_api_key_file))
    return Response(r.content,status_code=r.status_code,media_type=r.headers.get("content-type","application/json"))

@app.post("/v1/inference/chat/completions")
async def inference_chat(request:Request,body:bytes=Depends(require_mesh)):
    if not read_availability()["accepting_jobs"]:raise HTTPException(409,"worker unavailable")
    if not settings.llm_endpoint:raise HTTPException(503,"no local inference configured")
    try:p=json.loads(body or b"{}")
    except Exception:raise HTTPException(400,"invalid json")
    p["model"]=settings.llm_model_hint or p.get("model","local")
    body=json.dumps(p,separators=(",",":")).encode()
    url=settings.llm_endpoint.rstrip("/")+"/chat/completions";headers=api_headers(settings.llm_api_key_file)
    if p.get("stream"):
        async def gen():
            async with httpx.AsyncClient(timeout=httpx.Timeout(240,read=None)) as c:
                async with c.stream("POST",url,content=body,headers=headers) as r:
                    async for b in r.aiter_bytes():yield b
        return StreamingResponse(gen(),media_type="text/event-stream")
    async with httpx.AsyncClient(timeout=240) as c:r=await c.post(url,content=body,headers=headers)
    return Response(r.content,status_code=r.status_code,media_type=r.headers.get("content-type","application/json"))

@app.get("/v1/cloud/status")
def cloud_status(_:None=Depends(require_public)):
    if settings.role!="controller": raise HTTPException(404)
    status=cloud.status();status["enabled"]=settings.cloud_routing_enabled
    return status

@app.post("/v1/orchestration/config")
async def orchestration_configure(request:Request,_:None=Depends(require_public)):
    if settings.role!="controller": raise HTTPException(404)
    payload=await request.json();actor=str(payload.pop("actor","")).strip();confirmed=payload.pop("confirmed",False)
    if not actor or confirmed is not True:raise HTTPException(400,"actor and confirmed=true are required")
    try:result=cloud.configure_runtime(payload)
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))
    audit.emit("orchestration.config",actor=actor,data={"routing":result.get("routing")});return result

@app.get("/v1/energy/status")
def energy_status(_:None=Depends(require_public)):
    if settings.role!="controller": raise HTTPException(404)
    return energy.status()

@app.post("/v1/energy/config")
async def energy_configure(request:Request,_:None=Depends(require_public)):
    if settings.role!="controller": raise HTTPException(404)
    payload=await request.json();actor=str(payload.pop("actor","")).strip();confirmed=payload.pop("confirmed",False)
    if not actor or confirmed is not True:raise HTTPException(400,"actor and confirmed=true are required")
    try:result=energy.configure(payload)
    except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))
    audit.emit("energy.config",actor=actor,data={"provider_id":result.get("provider_id"),"tariff":result.get("tariff")})
    return result

@app.post("/v1/energy/refresh")
async def energy_refresh(request:Request,_:None=Depends(require_public)):
    if settings.role!="controller": raise HTTPException(404)
    payload=await request.json();actor=str(payload.get("actor") or "").strip()
    if not actor or payload.get("confirmed") is not True:raise HTTPException(400,"actor and confirmed=true are required")
    try:result=energy.refresh_rate(force=bool(payload.get("force",False)))
    except (ValueError,RuntimeError,httpx.HTTPError) as exc:raise HTTPException(502,str(exc))
    audit.emit("energy.refresh",actor=actor,data=result);return result


@app.get("/v1/models")
async def public_models(_:None=Depends(require_mobile_scope("models"))):
    models=agents.models()
    models.insert(1,{"id":"solomonprime-local","object":"model","owned_by":"solomonprime","name":"SolomonPrime Local Only"})
    provider_labels={"openai":"OpenAI Gated Advisor","openrouter":"OpenRouter Free Advisor","gemini":"Gemini Free Advisor",
                     "ollama_local":"Ollama Local Reviewer","ollama_cloud":"Ollama Included Cloud Reviewer"}
    for p in cloud.providers():
        if p.enabled and p.kind in provider_labels:
            models.append({"id":f"solomon-cloud-{p.kind}","object":"model","owned_by":"solomonprime","name":provider_labels[p.kind]})
    return {"object":"list","data":models}

@app.get("/v1/models/local")
def local_model_list(_:None=Depends(require_public)):
    if settings.role!="controller":raise HTTPException(404)
    return local_models.inventory()

@app.get("/v1/tools/self-test")
def tool_self_test(_:None=Depends(require_public)):
    checks={}
    for name,args in (("solomon_list_nodes",{}),("solomon_local_hardware",{}),("solomon_storage_layout",{})):
        try:checks[name]={"state":"ok","result_type":type(_execute_readonly_tool(name,args)).__name__}
        except Exception as exc:checks[name]={"state":"failed","error":f"{type(exc).__name__}: {str(exc)[:160]}"}
    return {"state":"ok" if all(x["state"]=="ok" for x in checks.values()) else "failed","checks":checks,"mutated":False}

@app.get("/v1/tools/openapi.json")
def readonly_tool_openapi(_:None=Depends(require_public)):
    """Minimal supported OpenAPI tool surface; all operations are local/read-only."""
    paths={
      "/v1/nodes":{"get":{"operationId":"solomon_list_nodes","summary":"List live SolomonPrime nodes","responses":{"200":{"description":"Live node registry"}}}},
      "/v1/models/local":{"get":{"operationId":"solomon_list_local_models","summary":"List GGUF and Ollama models","responses":{"200":{"description":"Local model inventory"}}}},
      "/v1/storage/layout":{"get":{"operationId":"solomon_storage_layout","summary":"Inspect block device layout","responses":{"200":{"description":"Read-only storage layout"}}}},
      "/v1/rf/status":{"get":{"operationId":"solomon_rf_status","summary":"Inspect receive-only RF capability state","responses":{"200":{"description":"RF state"}}}},
    }
    return {"openapi":"3.1.0","info":{"title":"SolomonPrime Read-only Tools","version":"1.0.0"},"paths":paths,
            "components":{"securitySchemes":{"bearerAuth":{"type":"http","scheme":"bearer"}}},"security":[{"bearerAuth":[]}]}

READONLY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "solomon_list_nodes",
            "description": "Return the live SolomonPrime node registry, including trust, health, capabilities, hardware, and ranked reachable paths.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solomon_plan_workload",
            "description": "Run SolomonPrime's deterministic resource scheduler against live trusted/healthy nodes. Use this before claiming where a workload should run.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "description": "Workload type, e.g. simulation, llm_inference, cpu_job, storage_scan"},
                    "min_ram_gb": {"type": "number", "minimum": 0},
                    "min_gpu_vram_gb": {"type": "number", "minimum": 0},
                    "preferred_gpu_vendor": {"type": "string", "description": "nvidia, amd, or empty"},
                    "requires_gpu": {"type": "boolean"},
                    "locality_node_id": {"type": "string"},
                    "stateful": {"type": "boolean"},
                    "priority": {"type": "string", "description": "interactive, operational, background, research, or other policy label"}
                },
                "required": ["kind"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solomon_memory_search",
            "description": "Search SolomonPrime durable memory. Read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "agent": {"type": "string"},
                    "domain": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20}
                },
                "required": ["q"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solomon_storage_layout",
            "description": "Inspect the controller's current block-device/storage layout. Read-only; does not scan file contents or modify disks.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solomon_storage_duplicates",
            "description": "Return the current verified duplicate-file plan from the Storage Steward index. Read-only; never deletes files.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solomon_local_hardware",
            "description": "Return current live hardware/resource information for this SolomonPrime node. Read-only.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solomon_list_goals",
            "description": "List persistent SolomonPrime goals and measurable outcome definitions. Read-only.",
            "parameters": {"type":"object","properties":{"status":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":100}},"additionalProperties":False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solomon_list_experiments",
            "description": "List recorded experiments, optionally for one goal. Read-only.",
            "parameters": {"type":"object","properties":{"goal_id":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":100}},"additionalProperties":False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solomon_job_status",
            "description": "Read the controller's current record for a distributed job. Read-only.",
            "parameters": {"type":"object","properties":{"job_id":{"type":"string"}},"required":["job_id"],"additionalProperties":False},
        },
    },
    {
        "type":"function",
        "function":{"name":"solomon_calendar_events","description":"List locally synchronized read-only Google and M365 calendar events. Calendar data never routes to cloud advisors.",
                    "parameters":{"type":"object","properties":{"limit":{"type":"integer","minimum":1,"maximum":200}},"additionalProperties":False}},
    },
    {
        "type":"function",
        "function":{"name":"solomon_development_read","description":"Read one bounded text file from an explicitly allowlisted development repository. Secrets, live runtime paths, binary files, symlinks, and path traversal are blocked.",
                    "parameters":{"type":"object","properties":{"repository":{"type":"string"},"path":{"type":"string"}},"required":["repository","path"],"additionalProperties":False}},
    },
    {
        "type":"function",
        "function":{"name":"solomon_development_search","description":"Search text in an explicitly allowlisted development repository. Read-only and bounded.",
                    "parameters":{"type":"object","properties":{"repository":{"type":"string"},"query":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":200}},"required":["repository","query"],"additionalProperties":False}},
    },
]

TOOL_SYSTEM = """You have access to SolomonPrime read-only system tools. When a request depends on current node health, hardware, resource availability, scheduling, memory contents, or storage state, USE the appropriate tool before answering. Never ask the user to provide information that an available read-only tool can retrieve. Never claim a node selection or live system state without tool evidence. Tool results are authoritative for current state. Executable skills can propose sandboxed jobs and serial bench sessions and execute exact existing Admin approvals. You cannot approve actions. Report approval_required without claiming execution. General host mutation remains unavailable."""


def _tool_node_view(n:dict[str,Any])->dict[str,Any]:
    # Registry hardware lives under the signed/live snapshot. Keep tool context bounded.
    snap=n.get("snapshot") or {}
    return {
        "name": n.get("name"),
        "node_id": n.get("node_id"),
        "role": n.get("role"),
        "trust": n.get("trust"),
        "health": n.get("health"),
        "capabilities": n.get("capabilities") or [],
        "cpu": snap.get("cpu") or {},
        "ram": snap.get("ram") or {},
        "gpus": snap.get("gpus") or [],
        "endpoints": n.get("endpoints") or [],
        "preferred_endpoint": n.get("preferred_endpoint") or "",
        "assigned_profile": n.get("assigned_profile") or {},
    }


def _execute_readonly_tool(name:str,args:dict[str,Any])->dict[str,Any]:
    if name=="solomon_list_nodes":
        return {"nodes": [_tool_node_view(n) for n in registry.list(settings.stale_after)]}
    if name=="solomon_plan_workload":
        clean={k:v for k,v in (args or {}).items() if k in Workload.__dataclass_fields__}
        w=Workload(**clean)
        nodes=registry.list(settings.stale_after)
        result=schedule_plan(nodes,w,local_node_id=NODE_ID)
        result["policy"]="deterministic_local_first_resource_fit"
        return result
    if name=="solomon_memory_search":
        q=str((args or {}).get("q") or "").strip()
        if not q:return {"results":[],"error":"q is required"}
        limit=min(max(int((args or {}).get("limit") or 6),1),20)
        return {"results": memory.search(q,agent=str((args or {}).get("agent") or ""),domain=str((args or {}).get("domain") or ""),limit=limit)}
    if name=="solomon_storage_layout":
        return storage.classify_layout(current_info().get("block_devices") or [])
    if name=="solomon_storage_duplicates":
        return storage.duplicate_plan()
    if name=="solomon_local_hardware":
        i=current_info()
        return {k:i.get(k) for k in ("node_id","name","role","capabilities","cpu","ram","gpus","network","services","block_devices","timestamp")}
    if name=="solomon_list_goals":
        return {"goals":goals.list(status=str((args or {}).get("status") or ""),limit=min(max(int((args or {}).get("limit") or 50),1),100))}
    if name=="solomon_list_experiments":
        return {"experiments":experiments.list(goal_id=str((args or {}).get("goal_id") or ""),limit=min(max(int((args or {}).get("limit") or 50),1),100))}
    if name=="solomon_job_status":
        jid=str((args or {}).get("job_id") or "")
        return {"job":jobs.get(jid)} if jid else {"error":"job_id is required"}
    if name=="solomon_calendar_events":
        return {"events":calendar_pull.events(min(max(int((args or {}).get("limit") or 50),1),200)),"cloud_export":False}
    if name=="solomon_development_read":
        return development.read(str((args or {}).get("repository") or ""),str((args or {}).get("path") or ""))
    if name=="solomon_development_search":
        return development.search(str((args or {}).get("repository") or ""),str((args or {}).get("query") or ""),int((args or {}).get("limit") or 100))
    return {"error":f"unknown or disallowed tool: {name}"}


def _parse_tool_args(raw:Any)->dict[str,Any]:
    if isinstance(raw,dict):return raw
    if not raw:return {}
    try:
        v=json.loads(str(raw))
        return v if isinstance(v,dict) else {}
    except Exception:
        return {}


def _tool_relevant_request(text:str)->bool:
    t=(text or "").lower()
    keys=("node","scheduler","gpu","vram","ram","hardware","resource","simulation","storage","disk","drive","filesystem","duplicate","memory","healthy trusted","goal","experiment","job","rf","radio","ollama","calendar","meeting","appointment","repository","source code","codebase","development")
    return any(k in t for k in keys)


def _fallback_live_context(text:str)->dict[str,Any]:
    """Deterministic fallback if a backend accepts tool schemas but fails to emit tool_calls.
    It never mutates state. For resource-selection language, derive only explicit/simple
    constraints and run the same scheduler against live registry data.
    """
    import re
    t=(text or "").lower()
    out={"nodes":[_tool_node_view(n) for n in registry.list(settings.stale_after)]}
    if any(k in t for k in ("disk","drive","filesystem","storage")):
        out["local_storage"]=storage.classify_layout(current_info().get("block_devices") or [])
    if "ollama" in t:out["local_models"]=local_models.inventory()
    if any(k in t for k in ("rf","radio")):out["rf_status"]=rf_monitor.status()
    if any(k in t for k in ("calendar","meeting","appointment")):out["calendar_events"]={"events":calendar_pull.events(100),"cloud_export":False}
    if any(k in t for k in ("repository","source code","codebase","development")):out["development_repositories"]=development.repositories()
    if any(k in t for k in ("find a","select","choose","schedule","run on","workload","simulation")):
        def num(patterns):
            for pat in patterns:
                m=re.search(pat,t)
                if m:
                    try:return float(m.group(1))
                    except Exception:pass
            return 0.0
        ram=num((r"([0-9]+(?:\.[0-9]+)?)\s*(?:gb|gib)\s*(?:of\s*)?(?:free\s*)?ram",r"ram[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*(?:gb|gib)"))
        vram=num((r"([0-9]+(?:\.[0-9]+)?)\s*(?:gb|gib)\s*(?:of\s*)?(?:free\s*)?(?:gpu\s*)?vram",r"vram[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*(?:gb|gib)"))
        w=Workload(
            kind="simulation" if "simulat" in t else "general",
            min_ram_gb=ram,
            min_gpu_vram_gb=vram,
            preferred_gpu_vendor="nvidia" if "nvidia" in t else ("amd" if "amd" in t else ""),
            requires_gpu=bool(vram or "gpu" in t),
            priority="background" if "background" in t else ("interactive" if "interactive" in t else "normal"),
        )
        out["scheduler_plan"]=schedule_plan(registry.list(settings.stale_after),w,local_node_id=NODE_ID)
        out["scheduler_plan"]["policy"]="deterministic_local_first_resource_fit"
    return out


def _buffered_sse(body:bytes):
    """Convert a completed OpenAI response into valid SSE for WebUI clients.
    Tool turns are resolved server-side; the final answer is emitted as one buffered delta.
    """
    try:obj=json.loads(body or b"{}")
    except Exception:obj={}
    text=extract_text(obj) or "The selected inference backend returned an empty answer. SolomonPrime recorded this as an integration failure; retry with SolomonPrime Local Only and inspect Admin → Overview."
    rid=str(obj.get("id") or f"chatcmpl-solomon-{int(time.time())}")
    model=str(obj.get("model") or "solomonprime")
    async def gen():
        first={"id":rid,"object":"chat.completion.chunk","created":int(time.time()),"model":model,"choices":[{"index":0,"delta":{"role":"assistant","content":text},"finish_reason":None}]}
        last={"id":rid,"object":"chat.completion.chunk","created":int(time.time()),"model":model,"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}
        yield ("data: "+json.dumps(first,separators=(",",":"))+"\n\n").encode()
        yield ("data: "+json.dumps(last,separators=(",",":"))+"\n\n").encode()
        yield b"data: [DONE]\n\n"
    return StreamingResponse(gen(),media_type="text/event-stream")


async def _agentic_readonly_chat(payload:dict[str,Any],selected:dict[str,Any],agent:str,user_text:str,extra:str=""):
    """Bounded tool loop; execution is restricted to exact operator approvals."""
    requested_stream=bool(payload.get("stream"))
    base={**payload,"stream":False}
    p=_inject(base,agent,user_text,"\n\n".join(x for x in (TOOL_SYSTEM,extra) if x))
    p["tools"]=READONLY_TOOLS + EXECUTION_TOOLS
    p["tool_choice"]="auto"
    messages=list(p.get("messages") or [])
    last_ct="application/json"

    for step in range(5):
        q=copy.deepcopy(p);q["messages"]=messages;q["stream"]=False
        st,b,ct=await _nonstream_to_selected(q,selected);last_ct=ct
        if st>=400:
            # Backend/chat-template compatibility fallback: give the model a live
            # read-only snapshot rather than allowing it to invent current state.
            if step==0:
                snapshot={"nodes":[_tool_node_view(n) for n in registry.list(settings.stale_after)]}
                fallback=_inject(base,agent,user_text,"\n\n".join(x for x in (extra,"LIVE SOLOMONPRIME NODE SNAPSHOT (read-only):\n"+json.dumps(snapshot,default=str)[:14000]) if x))
                st,b,ct=await _nonstream_to_selected(fallback,selected)
                return _buffered_sse(b) if requested_stream and st<400 else Response(b,status_code=st,media_type=ct)
            return Response(b,status_code=st,media_type=ct)
        try:obj=json.loads(b or b"{}")
        except Exception:
            return Response(b,status_code=st,media_type=ct)
        msg=((obj.get("choices") or [{}])[0].get("message") or {})
        calls=msg.get("tool_calls") or []
        if not calls:
            # Some OpenAI-compatible chat templates accept the tools field but do not
            # emit structured tool_calls. Do one deterministic live-context retry so
            # SolomonPrime still never responds "I cannot query the nodes" when the
            # controller itself has the evidence.
            if step==0 and _tool_relevant_request(user_text):
                live=_fallback_live_context(user_text)
                fallback=_inject(base,agent,user_text,"\n\n".join(x for x in (extra,"LIVE SOLOMONPRIME READ-ONLY TOOL EVIDENCE:\n"+json.dumps(live,default=str)[:20000],"Answer from this evidence. Do not ask the user to supply live state that is already present above.") if x))
                st2,b2,ct2=await _nonstream_to_selected(fallback,selected)
                if st2<400 and not extract_text(json.loads(b2 or b"{}")):
                    answer="SolomonPrime queried its local read-only tools, but the language backend returned no synthesis. Verified evidence: "+json.dumps(live,default=str,separators=(",",":"))[:12000]
                    b2=json.dumps({"id":f"chatcmpl-solomon-{int(time.time())}","object":"chat.completion","model":"solomonprime","choices":[{"index":0,"message":{"role":"assistant","content":answer},"finish_reason":"stop"}]}).encode();ct2="application/json"
                return _buffered_sse(b2) if requested_stream and st2<400 else Response(b2,status_code=st2,media_type=ct2)
            return _buffered_sse(b) if requested_stream else Response(b,status_code=st,media_type=ct)

        messages.append(msg)
        for call in calls[:6]:
            fn=(call.get("function") or {})
            name=str(fn.get("name") or "")
            args=_parse_tool_args(fn.get("arguments"))
            try:
                if name=="solomon_host_inspect":
                    result=await host_inspect_on_node(str(args.get("node_id") or NODE_ID),str(args.get("skill") or ""))
                elif name in {t["function"]["name"] for t in EXECUTION_TOOLS}:
                    result=await execute_skill(name,args,approvals=approvals,edge=edge_devices,dispatch=_dispatch_job,development=development,maintenance=maintenance)
                elif name=="solomon_job_status":
                    result=await _refresh_remote_job(jobs.get(str(args.get("job_id") or ""))) or {"error":"job not found"}
                else:result=_execute_readonly_tool(name,args)
            except Exception as e:result={"error":f"{type(e).__name__}: {e}"}
            audit.emit("tool.invoke",actor=agent,data={"tool":name,"args":args,"result_summary":str(result)[:1200]})
            messages.append({
                "role":"tool",
                "tool_call_id":str(call.get("id") or f"tool-{step}-{name}"),
                "name":name,
                "content":json.dumps(result,default=str,separators=(",",":"))[:30000],
            })

    # Tool budget exhausted. Force a final evidence-based synthesis without more calls.
    q=copy.deepcopy(p);q.pop("tools",None);q.pop("tool_choice",None);q["messages"]=messages+[{"role":"system","content":"Read-only tool-call budget exhausted. Produce the best final answer from the evidence already returned. Do not invent missing current-state facts."}]
    st,b,ct=await _nonstream_to_selected(q,selected)
    return _buffered_sse(b) if requested_stream and st<400 else Response(b,status_code=st,media_type=ct)


async def _bounded_cloud_context(user_text:str,preferred_provider:str="")->tuple[str,dict[str,Any]]:
    if not settings.cloud_routing_enabled:
        return "", {"used":False,"reason":"cloud routing disabled"}
    result=await cloud.advise(user_text,force=bool(preferred_provider),preferred_provider=preferred_provider)
    audit.emit("cloud.route",actor="solomon-core",data={k:v for k,v in result.items() if k!="content"})
    if not result.get("used"):
        return "", result
    text=str(result.get("content") or "")[:12000]
    extra=("BOUNDED CLOUD ADVISORY (quota-controlled, not authoritative):\n"+text+
           "\n\nUse this only as external expert advice. Verify it against local tools/memory and synthesize the final response locally. "
           "Do not claim the cloud advisor had access to local state.")
    return extra,result


@app.post("/v1/chat/completions")
async def public_chat(request:Request,_:None=Depends(require_mobile_scope("chat"))):
    if settings.role!="controller":raise HTTPException(404)
    try:payload=await request.json()
    except Exception:raise HTTPException(400,"invalid json")
    model=str(payload.get("model") or "solomonprime");user_text=_last_user(payload);agent,reviewed=_agent_for(model,user_text);domain=agents.domain(agent);selected=_select_llm()
    if not selected:raise HTTPException(503,"no trusted LLM worker available")
    audit.emit("inference.route",actor=agent,data={"model_alias":model,"node":selected.get("node_id"),"path":selected.get("path"),"reviewed":reviewed})
    selected_provider={"solomon-cloud-openai":"openai","solomon-cloud-openrouter":"openrouter","solomon-cloud-gemini":"gemini",
                       "solomon-cloud-ollama_local":"ollama_local","solomon-cloud-ollama_cloud":"ollama_cloud"}.get(model,"")
    if model=="solomonprime-local":cloud_extra,cloud_result="",{"used":False,"reason":"operator selected local-only"}
    else:cloud_extra,cloud_result=await _bounded_cloud_context(user_text,selected_provider)

    if reviewed:
        draft_payload={**payload,"stream":False,"model":"solomonprime"}
        draft_extra="Produce a strong first-pass answer. Use live read-only tools whenever current system state matters."
        if cloud_extra: draft_extra += "\n\n"+cloud_extra
        draft_resp=await _agentic_readonly_chat(draft_payload,selected,"solomon-core",user_text,draft_extra)
        if not isinstance(draft_resp,Response):
            return draft_resp
        if draft_resp.status_code>=400:return draft_resp
        draft=extract_text(json.loads(draft_resp.body or b"{}"))
        critic_input=f"Original request:\n{user_text}\n\nDraft answer:\n{draft}\n\nIdentify concrete errors, unsupported assumptions, omissions, safety issues, and improvements. Be concise and actionable."
        critic_base={"model":"solomon-critic","stream":False,"messages":[{"role":"user","content":critic_input}],"temperature":0.2}
        critic_p=_inject(critic_base,"critic-evaluator",critic_input)
        st2,b2,ct2=await _nonstream_to_selected(critic_p,selected)
        critique=extract_text(json.loads(b2 or b"{}")) if st2<400 else "Critic unavailable; independently verify the draft before finalizing."
        final_extra=f"An internal draft and independent critique were produced. Rewrite the answer from scratch using the useful criticism; do not mention internal agents unless asked. Treat tool-derived live-system facts in the draft as evidence.\n\nDRAFT:\n{draft[:7000]}\n\nCRITIQUE:\n{critique[:4000]}"
        if cloud_extra: final_extra += "\n\n"+cloud_extra
        final_payload={**payload,"stream":False}
        final_p=_inject(final_payload,"solomon-core",user_text,final_extra)
        st3,b3,ct3=await _nonstream_to_selected(final_p,selected)
        if st3<400 and settings.auto_memory:
            try:memory.capture_interaction(user_text,extract_text(json.loads(b3)),agent="solomon-core",domain="general")
            except Exception:pass
        return _buffered_sse(b3) if payload.get("stream") and st3<400 else Response(b3,status_code=st3,media_type=ct3)

    resp=await _agentic_readonly_chat(payload,selected,agent,user_text,cloud_extra)
    if isinstance(resp,Response) and resp.status_code<400 and settings.auto_memory and not payload.get("stream"):
        try:memory.capture_interaction(user_text,extract_text(json.loads(resp.body or b"{}")),agent=agent,domain=domain)
        except Exception:pass
    return resp

def _on_discovered(info:dict[str,Any],url:str,source:str):
    if info.get("node_id")==NODE_ID:return
    # Unsigned discovery is visibility only; trust requires a cluster-signed heartbeat.
    registry.upsert(info,role=str(info.get("role") or "node"),trust="pending",source=source,endpoints=((info.get("network") or {}).get("paths") or []),preferred_endpoint=url)


def _choose_controller()->str:
    # Explicit order is expected to be direct -> wired LAN -> Wi-Fi -> Tailscale.
    for u in controller_urls:
        try:
            r=httpx.get(u.rstrip("/")+"/health",timeout=.7)
            if r.status_code==200 and (r.json() or {}).get("role")=="controller":
                return u.rstrip("/")
        except Exception:pass
    return ""


def _apply_safe_profile(profile:dict[str,Any]):
    (state/"assigned-profile.json").write_text(json.dumps(profile,indent=2),encoding="utf-8")
    if not settings.auto_apply_safe_profiles:return
    root=Path("/apps/solomonprime/workspace")
    for role in profile.get("roles") or []:(root/role).mkdir(parents=True,exist_ok=True)


def _heartbeat_loop():
    while True:
        try:
            controller=_choose_controller()
            if controller:
                info=current_info();body=json.dumps(info,separators=(",",":")).encode();path="/v1/mesh/heartbeat";headers={"Content-Type":"application/json",**sign(cluster_key,"POST",path,body)}
                r=httpx.post(controller+path,content=body,headers=headers,timeout=8)
                if r.status_code==200:
                    d=r.json();profile=d.get("assigned_profile") or {};_apply_safe_profile(profile)
                    # Merge newly advertised controller paths, preserving current local-first order.
                    for e in d.get("controller_endpoints") or []:
                        u=e.get("endpoint")
                        if u and u not in controller_urls:controller_urls.append(u)
        except Exception:pass
        time.sleep(settings.heartbeat_interval)


def _controller_self_heartbeat_loop():
    """Refresh the controller's own registry record so it never becomes falsely stale."""
    while True:
        try:
            info=current_info();profile=make_profile(info,llm_configured=bool(settings.llm_endpoint))
            registry.upsert(info,role=settings.role,trust="trusted",source="local-heartbeat",endpoints=((info.get("network") or {}).get("paths") or []),assigned_profile=profile)
        except Exception:pass
        time.sleep(max(5,settings.heartbeat_interval))


def _maintenance_loop():
    while True:
        try:
            archived=memory.archive_low_value();
            if archived:audit.emit("memory.archive",actor="memory-curator",data={"count":archived})
        except Exception:pass
        time.sleep(6*3600)

def _calendar_loop():
    while True:
        try:
            cfg=calendar_pull.config()
            if cfg.get("enabled"):calendar_pull.sync()
            interval=max(5,int(cfg.get("sync_interval_minutes",15)))
        except Exception:interval=15
        time.sleep(interval*60)

def _energy_loop():
    while True:
        try: energy.maybe_refresh();energy.sample()
        except Exception as exc: audit.emit("energy.sample_failed",actor="ted",data={"error":type(exc).__name__})
        time.sleep(max(10,int(settings.energy_sample_interval)))

def _edge_discovery_loop():
    last_bluetooth=0.0
    last_pending_fingerprints:tuple[str,...]|None=None
    while True:
        now=time.time();do_bluetooth=now-last_bluetooth>=max(30,int(settings.edge_bluetooth_scan_interval))
        try:
            result=edge_devices.scan(bluetooth=do_bluetooth,bluetooth_timeout=settings.edge_bluetooth_scan_seconds,rssi_threshold=settings.edge_bluetooth_nearby_rssi)
            if do_bluetooth:last_bluetooth=now
            inventory=edge_devices.inventory()
            pending_fingerprints=tuple(sorted(str(d.get("fingerprint") or "") for d in inventory.get("discoveries",[]) if d.get("decision")=="pending" and d.get("fingerprint")))
            if pending_fingerprints != last_pending_fingerprints:
                if pending_fingerprints:
                    audit.emit("edge-device.candidates",actor="edge-discovery",data={"pending":len(pending_fingerprints),"usb_seen":result.get("usb",{}).get("seen",0),"bluetooth_seen":result.get("bluetooth",{}).get("seen",0),"fingerprints":list(pending_fingerprints)})
                last_pending_fingerprints=pending_fingerprints
        except Exception as exc:audit.emit("edge-device.scan_failed",actor="edge-discovery",data={"error":type(exc).__name__})
        time.sleep(max(3,int(settings.edge_usb_scan_interval)))

def _rf_monitor_loop():
    while True:
        try:
            result=rf_monitor.scan_receive(settings.rf_receive_window)
            if result.get("state") not in {"active","unavailable"}:audit.emit("rf.receive-failed",actor="rf-monitor",data={k:v for k,v in result.items() if k!="stderr_tail"})
        except Exception as exc:audit.emit("rf.receive-failed",actor="rf-monitor",data={"error":type(exc).__name__})
        time.sleep(max(60,int(settings.rf_monitor_interval)))

@app.on_event("startup")
def startup():
    global mdns,discovery
    info=current_info();registry.upsert(info,role=settings.role,trust="trusted",source="local",endpoints=((info.get("network") or {}).get("paths") or []),assigned_profile=make_profile(info,llm_configured=bool(settings.llm_endpoint)));registry.recompute_preferred()
    lan_ips=[e["ip"] for e in ((info.get("network") or {}).get("paths") or []) if e.get("kind")!="tailscale"]
    mdns=Advertiser(NODE_ID,NODE_NAME,settings.port,lan_ips) if settings.mdns else None
    if settings.role=="controller":
        discovery=DiscoveryLoop(settings.port,settings.discovery_interval,settings.static_peers,_on_discovered,mdns=settings.mdns,tailscale=settings.tailscale_discovery);discovery.start()
        threading.Thread(target=_controller_self_heartbeat_loop,daemon=True).start()
    else:threading.Thread(target=_heartbeat_loop,daemon=True).start()
    threading.Thread(target=_maintenance_loop,daemon=True).start()
    threading.Thread(target=_calendar_loop,daemon=True).start()
    if settings.role=="controller":threading.Thread(target=_energy_loop,daemon=True).start()
    if settings.edge_discovery_enabled:threading.Thread(target=_edge_discovery_loop,daemon=True).start()
    if settings.rf_monitor_enabled:threading.Thread(target=_rf_monitor_loop,daemon=True).start()
    audit.emit("service.start",data={"node_id":NODE_ID,"role":settings.role,"paths":((info.get("network") or {}).get("paths") or [])})

@app.on_event("shutdown")
def shutdown():
    if discovery:discovery.close()
    if mdns:mdns.close()

def main():uvicorn.run("solomonprime.api:app",host=settings.bind_host,port=settings.port,workers=1)

if __name__=="__main__":main()
