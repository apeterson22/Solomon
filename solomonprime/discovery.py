from __future__ import annotations
import json, socket, subprocess, threading
from typing import Callable, Any
import httpx
try:
    from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, ServiceListener, IPVersion
except Exception:
    Zeroconf=ServiceInfo=ServiceBrowser=ServiceListener=IPVersion=None  # type: ignore

SERVICE="_solomonprime._tcp.local."

class Advertiser:
    def __init__(self,node_id:str,name:str,port:int,ips:list[str]):
        self.zc=self.info=None
        if Zeroconf is None:return
        addrs=[]
        for ip in ips:
            try:addrs.append(socket.inet_aton(ip))
            except Exception:pass
        if not addrs:return
        try:
            self.zc=Zeroconf(ip_version=IPVersion.V4Only)
            self.info=ServiceInfo(SERVICE,f"{node_id}.{SERVICE}",addresses=addrs,port=port,properties={b"node_id":node_id.encode(),b"name":name.encode()},server=f"{socket.gethostname()}.local.")
            self.zc.register_service(self.info)
        except Exception:self.close()
    def close(self):
        try:
            if self.zc and self.info:self.zc.unregister_service(self.info)
            if self.zc:self.zc.close()
        except Exception:pass

class _Listener:
    def __init__(self,cb:Callable[[str],None]):self.cb=cb
    def add_service(self,zc,type_,name):
        info=zc.get_service_info(type_,name,timeout=1200)
        if not info:return
        for ip in info.parsed_addresses():self.cb(f"http://{ip}:{info.port}")
    update_service=add_service
    def remove_service(self,*_):pass

class Browser:
    def __init__(self,cb:Callable[[str],None]):
        self.zc=self.browser=None
        if Zeroconf is None:return
        try:
            self.zc=Zeroconf(ip_version=IPVersion.V4Only); self.browser=ServiceBrowser(self.zc,SERVICE,_Listener(cb))
        except Exception:self.close()
    def close(self):
        try:
            if self.zc:self.zc.close()
        except Exception:pass

def tailscale_peer_urls(port:int)->list[str]:
    try:
        raw=subprocess.check_output(["tailscale","status","--json"],stderr=subprocess.DEVNULL,text=True,timeout=4); d=json.loads(raw); out=[]
        for p in (d.get("Peer") or {}).values():
            for ip in (p or {}).get("TailscaleIPs") or []:
                if ":" not in ip:out.append(f"http://{ip}:{port}")
        return sorted(set(out))
    except Exception:return []

def fetch_info(url:str,timeout:float=1.1)->dict[str,Any]|None:
    try:
        r=httpx.get(url.rstrip("/")+"/v1/node/info",timeout=timeout)
        if r.status_code==200:return r.json()
    except Exception:pass
    return None

class DiscoveryLoop:
    def __init__(self,port:int,interval:int,static_peers:list[str],on_info:Callable[[dict[str,Any],str,str],None],mdns:bool=True,tailscale:bool=True):
        self.port=port;self.interval=interval;self.static=static_peers;self.on_info=on_info;self.mdnson=mdns;self.tson=tailscale;self.stop=threading.Event();self.browser=Browser(self._mdns) if mdns else None;self.thread=None
    def _consume(self,url:str,source:str):
        info=fetch_info(url)
        if info:self.on_info(info,url,source)
    def _mdns(self,url:str):threading.Thread(target=self._consume,args=(url,"mdns"),daemon=True).start()
    def start(self):
        if self.thread:return
        def loop():
            while not self.stop.is_set():
                urls=set(self.static)
                if self.tson:urls.update(tailscale_peer_urls(self.port))
                for u in urls:self._consume(u,"tailscale" if "100." in u else "static")
                self.stop.wait(self.interval)
        self.thread=threading.Thread(target=loop,daemon=True);self.thread.start()
    def close(self):
        self.stop.set();
        if self.browser:self.browser.close()
