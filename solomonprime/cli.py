from __future__ import annotations
import argparse,json,os
from pathlib import Path
import httpx

def _url(a):return a.url.rstrip("/")
def _key(a):
    if a.key:return a.key
    p=Path("/etc/solomonprime/api.key");return p.read_text().strip() if p.exists() else os.getenv("SOLOMON_API_KEY","")
def main():
    p=argparse.ArgumentParser();p.add_argument("--url",default=os.getenv("SOLOMON_URL","http://127.0.0.1:8765"));p.add_argument("--key",default="");sub=p.add_subparsers(dest="cmd",required=True)
    sub.add_parser("nodes");sub.add_parser("health");
    c=sub.add_parser("chat");c.add_argument("prompt",nargs="+");c.add_argument("--model",default="solomonprime")
    m=sub.add_parser("memory-search");m.add_argument("q",nargs="+")
    s=sub.add_parser("storage-scan");s.add_argument("roots",nargs="*",default=["/apps"]);s.add_argument("--max-files",type=int,default=0)
    a=p.parse_args();h={"Authorization":f"Bearer {_key(a)}","Content-Type":"application/json"}
    if a.cmd=="health":r=httpx.get(_url(a)+"/health",timeout=10)
    elif a.cmd=="nodes":r=httpx.get(_url(a)+"/v1/nodes",headers=h,timeout=10)
    elif a.cmd=="memory-search":r=httpx.get(_url(a)+"/v1/memory/search",headers=h,params={"q":" ".join(a.q)},timeout=10)
    elif a.cmd=="storage-scan":r=httpx.post(_url(a)+"/v1/storage/scan",headers=h,json={"roots":a.roots,"max_files":a.max_files},timeout=None)
    elif a.cmd=="chat":
        r=httpx.post(_url(a)+"/v1/chat/completions",headers=h,json={"model":a.model,"stream":False,"messages":[{"role":"user","content":" ".join(a.prompt)}]},timeout=240)
        if r.status_code==200:
            print(r.json().get("choices",[{}])[0].get("message",{}).get("content",""));return
    print(json.dumps(r.json(),indent=2) if "application/json" in r.headers.get("content-type","") else r.text)
