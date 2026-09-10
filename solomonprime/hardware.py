from __future__ import annotations

import ipaddress
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil


def _run(args: list[str], timeout: int = 5) -> str:
    try:
        return subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True, timeout=timeout).strip()
    except Exception:
        return ""


def _temp_c(path: Path) -> float | None:
    try:
        v = float(path.read_text().strip()); return v / 1000.0 if v > 500 else v
    except Exception:
        return None


def nvidia_gpus() -> list[dict[str, Any]]:
    out = _run([("/usr/lib/wsl/lib/nvidia-smi" if Path("/usr/lib/wsl/lib/nvidia-smi").exists() else "nvidia-smi"), "--query-gpu=name,memory.total,memory.free,utilization.gpu,temperature.gpu,pci.bus_id,driver_version", "--format=csv,noheader,nounits"], 8)
    gpus=[]
    for line in out.splitlines():
        p=[x.strip() for x in line.split(",")]
        if len(p) < 7: continue
        try:
            gpus.append({"vendor":"nvidia","name":p[0],"vram_total_mb":int(float(p[1])),"vram_free_mb":int(float(p[2])),"util_pct":float(p[3]) if p[3].replace(".","",1).isdigit() else None,"temp_c":float(p[4]) if p[4].replace(".","",1).isdigit() else None,"pci":p[5],"driver":p[6]})
        except Exception: pass
    return gpus


def amd_gpus() -> list[dict[str, Any]]:
    out=[]
    for card in sorted(Path("/sys/class/drm").glob("card*/device")):
        try:
            if (card/"vendor").read_text().strip().lower() != "0x1002": continue
        except Exception: continue
        total=used=free=None
        try:
            total=int((card/"mem_info_vram_total").read_text())//(1024*1024)
            used=int((card/"mem_info_vram_used").read_text())//(1024*1024); free=max(total-used,0)
        except Exception: pass
        util=None
        try: util=float((card/"gpu_busy_percent").read_text())
        except Exception: pass
        temp=None
        for t in card.glob("hwmon/hwmon*/temp1_input"):
            temp=_temp_c(t)
            if temp is not None: break
        pci=os.path.basename(os.path.realpath(card))
        name=_run(["bash","-lc",f"lspci -s {pci} 2>/dev/null | sed 's/^[^ ]* //'"],3) or "AMD GPU"
        out.append({"vendor":"amd","name":name,"vram_total_mb":total,"vram_free_mb":free,"util_pct":util,"temp_c":temp,"pci":pci})
    return out


def mounts() -> list[dict[str, Any]]:
    rows=[]
    for p in psutil.disk_partitions(all=False):
        if p.mountpoint.startswith(("/snap","/proc","/sys","/dev","/run")): continue
        try:
            u=psutil.disk_usage(p.mountpoint)
            rows.append({"device":p.device,"mount":p.mountpoint,"fstype":p.fstype,"total_gb":round(u.total/2**30,2),"free_gb":round(u.free/2**30,2)})
        except Exception: pass
    return rows


def block_devices() -> list[dict[str, Any]]:
    raw=_run(["lsblk","-J","-b","-o","NAME,PATH,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,ROTA,TRAN,UUID"],8)
    try: return json.loads(raw).get("blockdevices",[]) if raw else []
    except Exception: return []


def _prefix_for(addr: str, netmask: str | None) -> int:
    try: return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen if netmask else 24
    except Exception: return 24


def network_paths(port: int) -> list[dict[str, Any]]:
    stats=psutil.net_if_stats(); paths=[]
    for name, addrs in psutil.net_if_addrs().items():
        st=stats.get(name)
        if st and not st.isup: continue
        for a in addrs:
            if a.family != socket.AF_INET: continue
            ip=a.address
            if ip.startswith("127."): continue
            virtual_prefixes=("lo:","docker","virbr","br-","veth","cni","flannel","vxlan","cali","cilium","kube","microk8s","tunl")
            if name=="lo" or name.startswith(virtual_prefixes): continue
            if name.startswith("tailscale"):
                kind="tailscale"; rank=50
            elif Path(f"/sys/class/net/{name}/wireless").exists() or name.startswith(("wl","wlan")):
                kind="wifi"; rank=70
            else:
                prefix=_prefix_for(ip, getattr(a,"netmask",None))
                # Point-to-point/small dedicated networks get first data-plane priority.
                kind="direct" if prefix >= 29 else "wired"
                rank=95 if kind=="direct" else 90
            speed=int(st.speed) if st and getattr(st,"speed",0) and st.speed > 0 else 0
            paths.append({"interface":name,"ip":ip,"kind":kind,"rank":rank,"speed_mbps":speed,"endpoint":f"http://{ip}:{port}"})
    paths.sort(key=lambda x:(x["rank"],x["speed_mbps"]), reverse=True)
    return paths


def tailscale_info() -> dict[str, Any]:
    raw=_run(["tailscale","status","--json"],5)
    if not raw: return {"available":False,"state":"unavailable"}
    try:
        d=json.loads(raw); selfd=d.get("Self") or {}
        return {"available":True,"self_ips":d.get("TailscaleIPs") or [],"dns_name":selfd.get("DNSName", ""),"online":bool(selfd.get("Online", True))}
    except Exception: return {"available":False,"state":"parse-error"}


def service_probe() -> dict[str, Any]:
    s={}
    if Path("/opt/llama.cpp/build/bin/llama-server").exists(): s["llama_cpp"]={"installed":True}
    if shutil.which("ollama"): s["ollama"]={"installed":True}
    if shutil.which("docker"):
        s["docker"]={"installed":True}
        out=_run(["docker","ps","--format","{{.Names}}"],3); s["docker"]["containers"]=[x for x in out.splitlines() if x]
    return s


def profile(node_id: str, node_name: str, port: int = 8765) -> dict[str, Any]:
    vm=psutil.virtual_memory(); load=psutil.getloadavg() if hasattr(psutil,"getloadavg") else (0,0,0)
    gpus=amd_gpus()+nvidia_gpus(); paths=network_paths(port)
    caps={"cpu","storage","python-worker"}
    if gpus: caps.add("gpu")
    if any(g["vendor"]=="nvidia" for g in gpus): caps|={"cuda-candidate","simulation-cuda"}
    if any(g["vendor"]=="amd" for g in gpus): caps|={"vulkan-candidate","simulation-vulkan"}
    ram_gb=vm.total/2**30
    phys=psutil.cpu_count(False) or psutil.cpu_count(True) or 1
    if phys >= 8: caps.add("cpu-simulation")
    if ram_gb >= 64: caps|={"memory-server-candidate","vector-db-candidate"}
    if ram_gb >= 128: caps.add("high-memory-candidate")
    return {
      "node_id":node_id,"name":node_name or socket.gethostname(),"hostname":socket.gethostname(),"timestamp":time.time(),
      "os":{"system":platform.system(),"release":platform.release(),"machine":platform.machine()},
      "cpu":{"logical":psutil.cpu_count(True),"physical":phys,"util_pct":psutil.cpu_percent(interval=.12),"load1":load[0]},
      "ram":{"total_gb":round(ram_gb,2),"available_gb":round(vm.available/2**30,2),"used_pct":vm.percent},
      "gpus":gpus,"mounts":mounts(),"block_devices":block_devices(),
      "network":{"paths":paths,"tailscale":tailscale_info()},
      "capabilities":sorted(caps),"services":service_probe(),
    }
