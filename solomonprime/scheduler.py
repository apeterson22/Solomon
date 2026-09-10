from __future__ import annotations
from dataclasses import dataclass,asdict
from typing import Any
import httpx,time

@dataclass
class Workload:
    kind:str
    min_ram_gb:float=1
    min_gpu_vram_gb:float=0
    preferred_gpu_vendor:str=""
    requires_gpu:bool=False
    locality_node_id:str=""
    stateful:bool=False
    priority:str="normal"
    max_cpu_util_pct:float=95

PATH_BONUS={"loopback":1.0,"direct":.95,"wired":.88,"wifi":.68,"tailscale":.50}
_probe_cache:dict[str,tuple[float,bool,float]]={}

def _reachable(url:str)->tuple[bool,float]:
    now=time.time();cached=_probe_cache.get(url)
    if cached and now-cached[0]<15:return cached[1],cached[2]
    t=time.perf_counter();ok=False
    try:ok=httpx.get(url.rstrip("/")+"/health",timeout=.45).status_code==200
    except Exception:ok=False
    ms=(time.perf_counter()-t)*1000;_probe_cache[url]=(now,ok,ms);return ok,ms

def choose_endpoint(node:dict[str,Any],local_node_id:str="")->dict[str,Any]|None:
    if node.get("node_id")==local_node_id:return {"endpoint":"http://127.0.0.1:8765","kind":"loopback","rank":100,"rtt_ms":0.0}
    eps=sorted(node.get("endpoints") or [],key=lambda e:(float(e.get("rank") or 0),float(e.get("speed_mbps") or 0)),reverse=True)
    for e in eps:
        url=e.get("endpoint")
        if not url:continue
        ok,ms=_reachable(url)
        if ok:return {**e,"rtt_ms":round(ms,2)}
    pref=node.get("preferred_endpoint")
    if pref:
        ok,ms=_reachable(pref)
        if ok:return {"endpoint":pref,"kind":"unknown","rank":0,"rtt_ms":round(ms,2)}
    return None

def _gpu_fit(s:dict[str,Any],w:Workload)->tuple[bool,float,float]:
    if not w.requires_gpu and w.min_gpu_vram_gb<=0:return True,0,.0
    best=0;vendor=0;matched=False
    for g in s.get("gpus") or []:
        free=float(g.get("vram_free_mb") or 0)/1024
        if free>0 and free>=w.min_gpu_vram_gb:
            matched=True
            best=max(best,free)
            if w.preferred_gpu_vendor and g.get("vendor")==w.preferred_gpu_vendor:vendor=1
    return matched,best,vendor

def score_node(node:dict[str,Any],w:Workload,*,local_node_id:str="")->tuple[float,list[str],dict[str,Any]|None]:
    if node.get("trust")!="trusted" or node.get("health") not in {"online","healthy"}:return -1e9,["untrusted_or_offline"],None
    if w.locality_node_id and node.get("node_id")!=w.locality_node_id:return -1e9,["locality_mismatch"],None
    s=node.get("snapshot") or {};ram=s.get("ram") or {};cpu=s.get("cpu") or {}
    if (s.get("availability") or {}).get("accepting_jobs", True) is not True:return -1e9,["node_unavailable"],None
    avail=float(ram.get("available_gb") or 0);total=max(float(ram.get("total_gb") or 1),1)
    if avail<w.min_ram_gb:return -1e9,["insufficient_ram"],None
    if float(cpu.get("util_pct") or 0)>w.max_cpu_util_pct:return -1e9,["cpu_saturated"],None
    ok,gfree,vbonus=_gpu_fit(s,w)
    if not ok:return -1e9,["insufficient_gpu_vram"],None
    ep=choose_endpoint(node,local_node_id)
    if not ep:return -1e9,["no_reachable_path"],None
    path=PATH_BONUS.get(ep.get("kind"),.4)
    ramh=min(avail/total,1);cpuh=max(0,1-float(cpu.get("util_pct") or 0)/100);gpuh=(min(gfree/max(w.min_gpu_vram_gb+1,1),2)/2 if (w.requires_gpu or w.min_gpu_vram_gb) else .5)
    locality=1 if w.locality_node_id and node.get("node_id")==w.locality_node_id else 0
    score=.23*ramh+.20*cpuh+.22*gpuh+.17*path+.08*vbonus+.10*locality
    if w.stateful and ep.get("kind") in {"wifi","tailscale"}:score-=.08
    reasons=[f"ram={ramh:.2f}",f"cpu={cpuh:.2f}",f"gpu={gpuh:.2f}",f"path={ep.get('kind')}:{path:.2f}",f"rtt={ep.get('rtt_ms',0):.1f}ms"]
    return score,reasons,ep

def plan(nodes:list[dict[str,Any]],w:Workload,*,local_node_id:str="",llm_preference:str="")->dict[str,Any]:
    rows=[]
    for n in nodes:
        score,reasons,ep=score_node(n,w,local_node_id=local_node_id)
        if score<=-1e8:continue
        if llm_preference and n.get("node_id")==llm_preference:
            score+=.025;reasons.append("bounded_llm_tiebreak=.025")
        rows.append({"node_id":n.get("node_id"),"name":n.get("name"),"score":round(score,4),"reasons":reasons,"path":ep})
    rows.sort(key=lambda r:r["score"],reverse=True)
    return {"workload":asdict(w),"selected":rows[0] if rows else None,"candidates":rows,"policy":"local_first_resource_fit_with_bounded_llm_tiebreak"}

def recommended_roles(snapshot:dict[str,Any],llm_configured:bool=False)->list[str]:
    roles={"general-worker"};ram=float((snapshot.get("ram") or {}).get("total_gb") or 0);phys=int((snapshot.get("cpu") or {}).get("physical") or 1);gpus=snapshot.get("gpus") or []
    if phys>=8:roles.add("cpu-simulation")
    if ram>=64:roles|={"memory-store","vector-index","cpu-simulation"}
    if ram>=128:roles.add("high-memory")
    if ram>=256:roles.add("large-memory")
    if llm_configured:roles.add("llm-worker")
    if any(g.get("vendor")=="nvidia" for g in gpus):roles.add("cuda-simulation")
    if any(g.get("vendor")=="amd" for g in gpus):roles.add("vulkan-simulation")
    return sorted(roles)
