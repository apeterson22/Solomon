from __future__ import annotations
from typing import Any
from .scheduler import recommended_roles

SAFE_COMPONENTS={
 "general-worker":["health","python-worker"],"cpu-simulation":["science-python","job-runner"],
 "cuda-simulation":["cuda-observer","science-python"],"vulkan-simulation":["vulkan-observer","science-python"],
 "llm-worker":["inference-adapter","metrics"],"memory-store":["memory-replica","backup-agent"],
 "vector-index":["vector-index"],"high-memory":["large-cache-policy"],"large-memory":["large-memory-policy"],
}

def make_profile(snapshot:dict[str,Any],*,llm_configured:bool=False)->dict[str,Any]:
    roles=recommended_roles(snapshot,llm_configured=llm_configured);components=sorted({x for r in roles for x in SAFE_COMPONENTS.get(r,[])})
    return {"roles":roles,"components":components,"auto_apply":{"directories":True,"user_space_python":True,"driver_changes":False,"kernel_changes":False,"firewall_changes":False,"destructive_storage":False},"risk":"reversible","note":"Hardware-derived profile. LLM may recommend among already-safe roles but cannot bypass hard resource or safety limits."}
