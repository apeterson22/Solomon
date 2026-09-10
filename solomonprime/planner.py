from __future__ import annotations
import json
from typing import Any
import httpx

class LLMAdvisor:
    """Bounded advisory use of the local LLM. Deterministic policy remains authoritative."""
    def __init__(self,endpoint:str,key:str=""):
        self.endpoint=endpoint.rstrip("/");self.key=key
    def suggest_node(self,workload:dict[str,Any],candidates:list[dict[str,Any]])->dict[str,Any]:
        if not self.endpoint or len(candidates)<2:return {}
        # Only ask when deterministic scores are close; never make an invalid node eligible.
        if abs(float(candidates[0].get("score",0))-float(candidates[1].get("score",0)))>.06:return {}
        sys="You are a workload placement advisor. Choose exactly one node_id from the allowed candidates. Prefer data locality, stable low-latency local links, resource headroom, and workload fit. Return JSON only: {\"node_id\":\"...\",\"reason\":\"...\"}."
        payload={"model":"local","stream":False,"temperature":0,"max_tokens":180,"messages":[{"role":"system","content":sys},{"role":"user","content":json.dumps({"workload":workload,"candidates":candidates[:4]},separators=(",",":"))}]}
        h={"Content-Type":"application/json"};
        if self.key:h["Authorization"]=f"Bearer {self.key}"
        try:
            r=httpx.post(self.endpoint+"/chat/completions",json=payload,headers=h,timeout=45);r.raise_for_status();txt=r.json()["choices"][0]["message"]["content"]
            start=txt.find("{");end=txt.rfind("}");d=json.loads(txt[start:end+1]);allowed={c["node_id"] for c in candidates[:4]};return d if d.get("node_id") in allowed else {}
        except Exception:return {}
