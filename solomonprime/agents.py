from __future__ import annotations
from pathlib import Path
from typing import Any

AGENT_DOMAINS={
 "solomon-core":"general","storage-steward":"storage","memory-curator":"memory","critic-evaluator":"evaluation",
 "home-ops":"home","farm-ops":"farm","research-simulation":"research","infrastructure":"infrastructure",
}
MODEL_TO_AGENT={
 "solomonprime":"auto","solomonprime-reviewed":"reviewed","solomon-storage":"storage-steward","solomon-memory":"memory-curator",
 "solomon-critic":"critic-evaluator","solomon-home":"home-ops","solomon-farm":"farm-ops","solomon-research":"research-simulation","solomon-infrastructure":"infrastructure",
}

KEYWORDS={
 "storage-steward":("drive","disk","filesystem","file","duplicate","dedup","storage","folder","archive","mount","lvm"),
 "memory-curator":("memory","remember","forget","context","retrieval","knowledge","summarize history","long term","short term"),
 "home-ops":("home","house","household","hvac","thermostat","lighting","appliance","utility","security camera"),
 "farm-ops":("farm","crop","soil","irrigation","livestock","pasture","field","barn","equipment","harvest","planting"),
 "research-simulation":("simulation","simulate","monte carlo","paper","experiment","hypothesis","parameter sweep","modeling","inference","physics","folding"),
 "infrastructure":("systemd","docker","network","gpu","server","kernel","package","firewall","tailscale","service","driver","bios"),
 "critic-evaluator":("critique","review","evaluate","audit this answer","find errors","benchmark"),
}

class AgentCatalog:
    def __init__(self,root:str,enabled:list[str]):
        self.root=Path(root);self.enabled=set(enabled)
    def route(self,text:str)->str:
        t=text.lower();best=(0,"solomon-core")
        for agent,keys in KEYWORDS.items():
            if agent not in self.enabled:continue
            score=sum(2 if " " in k and k in t else 1 for k in keys if k in t)
            if score>best[0]:best=(score,agent)
        return best[1]
    def domain(self,agent:str)->str:return AGENT_DOMAINS.get(agent,"general")
    def prompt(self,agent:str)->str:
        if agent not in self.enabled:agent="solomon-core"
        p=self.root/agent
        chunks=[]
        for name in ("IDENTITY.md","SOUL.md","BOUNDARIES.md","SKILLS.md","MEMORY.md"):
            f=p/name
            if f.exists():chunks.append(f"## {name}\n{f.read_text(encoding='utf-8')[:6000]}")
        return "\n\n".join(chunks)
    def models(self)->list[dict[str,Any]]:
        labels={"solomonprime":"SolomonPrime","solomonprime-reviewed":"SolomonPrime Reviewed","solomon-storage":"Storage Steward","solomon-memory":"Memory Curator","solomon-critic":"Critic / Evaluator","solomon-home":"Home Ops","solomon-farm":"Farm Ops","solomon-research":"Research / Simulation","solomon-infrastructure":"Infrastructure (approval-first)"}
        return [{"id":k,"object":"model","owned_by":"solomonprime","name":v} for k,v in labels.items()]
