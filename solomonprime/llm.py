from __future__ import annotations
import json
from pathlib import Path
from typing import Any, AsyncIterator, Callable
import httpx
from .security import sign


def api_headers(key_file:str)->dict[str,str]:
    h={"Content-Type":"application/json"}
    p=Path(key_file) if key_file else None
    if p and p.exists():
        k=p.read_text().strip()
        if k:h["Authorization"]=f"Bearer {k}"
    return h

async def local_chat(endpoint:str,key_file:str,payload:dict[str,Any])->httpx.Response:
    async with httpx.AsyncClient(timeout=httpx.Timeout(180,read=None)) as c:
        return await c.post(endpoint.rstrip("/")+"/chat/completions",json=payload,headers=api_headers(key_file))

async def remote_chat(endpoint:str,cluster_key:bytes,payload:dict[str,Any])->httpx.Response:
    body=json.dumps(payload,separators=(",",":")).encode();path="/v1/inference/chat/completions";h={"Content-Type":"application/json",**sign(cluster_key,"POST",path,body)}
    async with httpx.AsyncClient(timeout=httpx.Timeout(180,read=None)) as c:return await c.post(endpoint.rstrip("/")+path,content=body,headers=h)

def extract_text(resp:dict[str,Any])->str:
    try:return str(resp["choices"][0]["message"]["content"] or "")
    except Exception:return ""
