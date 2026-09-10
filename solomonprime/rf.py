from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any


class RFMonitor:
    """Local receive-only RF capability detector and bounded observation ledger."""

    def __init__(self, db_path: str):
        self.path=Path(db_path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._db() as c:c.execute("""CREATE TABLE IF NOT EXISTS observations(
            id TEXT PRIMARY KEY, backend TEXT NOT NULL, protocol TEXT, model TEXT,
            device_ref TEXT, summary TEXT NOT NULL, first_seen REAL NOT NULL,
            last_seen REAL NOT NULL, count INTEGER NOT NULL)""")

    def _db(self):
        c=sqlite3.connect(self.path,check_same_thread=False);c.row_factory=sqlite3.Row;return c

    @staticmethod
    def capabilities() -> dict[str,Any]:
        names=("rtl_433","rtl_test","hackrf_info","hackrf_sweep","SoapySDRUtil","uhd_find_devices","ubertooth-rx",
               "iw","bluetoothctl","btmon","tshark","dumpcap","sigrok-cli","minicom","avrdude","flashrom")
        tools={name:bool(shutil.which(name)) for name in names}
        radios=[]
        if tools["rtl_433"] or tools["rtl_test"] :radios.append({"family":"RTL-SDR","receive":True,"transmit":False,"detected_by":"installed-tool-candidate"})
        if tools["hackrf_info"] or tools["hackrf_sweep"]:radios.append({"family":"HackRF","receive":True,"transmit":True,"detected_by":"installed-tool-candidate"})
        if tools["SoapySDRUtil"] :radios.append({"family":"SoapySDR","receive":True,"transmit":"device-dependent","detected_by":"installed-tool-candidate"})
        if tools["uhd_find_devices"]:radios.append({"family":"USRP","receive":True,"transmit":True,"detected_by":"installed-tool-candidate"})
        if tools["ubertooth-rx"]:radios.append({"family":"Ubertooth","receive":True,"transmit":"adapter-dependent","bands":["2.4GHz"],"detected_by":"installed-tool-candidate"})
        wifi=[p.name for p in Path("/sys/class/net").glob("*") if (p/"wireless").exists()]
        monitor_support=False
        if tools["iw"]:
            try:
                probe=subprocess.run(["iw","list"],text=True,capture_output=True,timeout=5,check=False)
                monitor_support="* monitor" in (probe.stdout or "")
            except (OSError,subprocess.TimeoutExpired):pass
        coverage={
            "sub_ghz_receive":tools["rtl_433"],
            "bluetooth_ble_observation":tools["btmon"] or tools["bluetoothctl"],
            "wifi_monitor_candidate":bool(wifi and monitor_support),
            "two_point_four_ghz_sdr_candidate":any(x["family"] in {"HackRF","SoapySDR","USRP","Ubertooth"} for x in radios),
        }
        return {"tools":tools,"radio_candidates":radios,"wifi_interfaces":wifi,"wifi_monitor_mode_reported":monitor_support,
                "coverage":coverage,"receive_monitor_available":any(coverage.values()),"transmit_executor_enabled":False,
                "truth_note":"Tool presence is not hardware proof. RTL-SDR/rtl_433 is sub-GHz and does not provide full 2.4 GHz coverage; a successful adapter probe is required."}

    def scan_receive(self, seconds: int=10) -> dict[str,Any]:
        exe=shutil.which("rtl_433")
        if not exe:return {"state":"unavailable","backend":"rtl_433","observations":0,"reason":"rtl_433 is not installed","transmitted":False}
        duration=max(3,min(int(seconds),30))
        try:p=subprocess.run([exe,"-F","json","-M","protocol","-T",str(duration)],text=True,capture_output=True,timeout=duration+12,check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:return {"state":"failed","backend":"rtl_433","observations":0,"reason":type(exc).__name__,"transmitted":False}
        count=0
        for line in (p.stdout or "").splitlines():
            try:item=json.loads(line)
            except json.JSONDecodeError:continue
            if not isinstance(item,dict):continue
            protocol=str(item.get("protocol") or "");model=str(item.get("model") or "unknown");device_ref=str(item.get("id") or item.get("channel") or "")
            stable=hashlib.sha256(f"{protocol}|{model}|{device_ref}".encode()).hexdigest()[:20]
            summary={k:item[k] for k in sorted(item) if k in {"model","protocol","id","channel","battery_ok","temperature_C","humidity","moisture","wind_avg_km_h","rain_mm","status"}}
            now=time.time()
            with self._db() as c:
                old=c.execute("SELECT first_seen,count FROM observations WHERE id=?",(stable,)).fetchone()
                c.execute("INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?,?,?,?,?)",(stable,"rtl_433",protocol,model,device_ref,json.dumps(summary,sort_keys=True),float(old["first_seen"]) if old else now,now,int(old["count"])+1 if old else 1))
            count+=1
        return {"state":"active" if p.returncode in {0,1} else "failed","backend":"rtl_433","observations":count,"exit_code":p.returncode,"transmitted":False,"stderr_tail":(p.stderr or "")[-500:]}

    def observations(self, limit: int=100) -> list[dict[str,Any]]:
        with self._db() as c:rows=c.execute("SELECT * FROM observations ORDER BY last_seen DESC LIMIT ?",(min(max(limit,1),500),)).fetchall()
        out=[]
        for row in rows:
            d=dict(row);d["summary"]=json.loads(d["summary"]);out.append(d)
        return out

    def status(self) -> dict[str,Any]:
        caps=self.capabilities();obs=self.observations()
        return {"capabilities":caps,"observations":obs,"counts":{"observations":len(obs)},"policy":{"owned_or_explicitly_authorized_devices_only":True,"receive_only_automatic":True,"cloud_export":False,"credential_capture":False,"wifi_deauthentication":False,"unknown_signals":"untrusted","transmit_requires_verified_adapter":True,"transmit_requires_frequency_policy":True,"transmit_requires_action_approval":True}}
