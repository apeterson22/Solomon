from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import uuid
import time
from pathlib import Path
from typing import Any

from .device_lab import serial_exchange, investigation_plan

import yaml

STATES = {"inventory", "detected", "paired", "verified", "trusted", "quarantined", "retired"}
DECISIONS = {"pending", "approved_for_analysis", "denied"}
DEVICE_ACTIONS = {
    "serial_exchange": {"risk":"critical", "executor":"serial_bench", "transport":"serial"},
    "pairing": {"risk":"mutating", "executor":"bluez_pair", "transport":"bluetooth"},
    "authentication_attempt": {"risk":"mutating", "executor":"bluez_connect", "transport":"bluetooth"},
    "usb_endpoint_write": {"risk":"critical", "executor":"verified_adapter", "transport":"usb"},
    "driver_detachment": {"risk":"critical", "executor":"verified_adapter", "transport":"usb"},
    "firmware_flashing": {"risk":"critical", "executor":"verified_adapter", "transport":"any"},
    "radio_command": {"risk":"critical", "executor":"verified_adapter", "transport":"any"},
    "location_access": {"risk":"critical", "executor":"verified_adapter", "transport":"any"},
    "physical_movement": {"risk":"critical", "executor":"verified_adapter", "transport":"any"},
}
USB_CAPABILITIES = {
    "01": ["audio"], "02": ["communications"], "03": ["human-interface"],
    "06": ["imaging"], "07": ["printer"], "08": ["mass-storage"],
    "09": ["usb-hub"], "0a": ["data-interface"], "0e": ["video"],
    "e0": ["wireless-controller"],
}
TRANSITIONS = {
    "inventory": {"detected", "quarantined", "retired"},
    "detected": {"inventory", "paired", "verified", "quarantined"},
    "paired": {"detected", "verified", "quarantined"},
    "verified": {"trusted", "quarantined"},
    "trusted": {"verified", "quarantined", "retired"},
    "quarantined": {"inventory", "retired"},
    "retired": {"inventory"},
}


class EdgeDeviceRegistry:
    """Photo-seeded inventory with explicit, audited lifecycle transitions.

    This registry never scans, pairs, flashes, transmits, or actuates hardware.
    Those operations must be implemented as separately approved jobs.
    """

    def __init__(self, catalog_path: str, state_path: str):
        self.catalog_path = Path(catalog_path)
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS device_state(
                device_id TEXT PRIMARY KEY, state TEXT NOT NULL, actor TEXT NOT NULL,
                note TEXT, updated REAL NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS device_events(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL,
                old_state TEXT, new_state TEXT NOT NULL, actor TEXT NOT NULL,
                note TEXT, created REAL NOT NULL)""")
            c.execute("""CREATE TABLE IF NOT EXISTS discovered_devices(
                fingerprint TEXT PRIMARY KEY, transport TEXT NOT NULL, address TEXT,
                name TEXT, vendor TEXT, product TEXT, device_class TEXT, rssi INTEGER,
                proximity TEXT, capabilities TEXT NOT NULL, risk TEXT NOT NULL,
                decision TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL,
                evidence TEXT NOT NULL, analysis_plan TEXT NOT NULL, actor TEXT, note TEXT)""")
            c.execute("""CREATE TABLE IF NOT EXISTS device_actions(
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, action TEXT NOT NULL,
                parameters TEXT NOT NULL, risk TEXT NOT NULL, state TEXT NOT NULL,
                requested_by TEXT NOT NULL, request_note TEXT NOT NULL, created REAL NOT NULL,
                expires REAL NOT NULL, decided_by TEXT, decision_note TEXT, decided REAL,
                executed REAL, result TEXT)""")

    def _db(self):
        c = sqlite3.connect(self.state_path)
        c.row_factory = sqlite3.Row
        return c

    def _catalog(self) -> dict[str, Any]:
        if not self.catalog_path.exists():
            return {"policy": {}, "devices": []}
        return yaml.safe_load(self.catalog_path.read_text(encoding="utf-8")) or {"policy": {}, "devices": []}

    def inventory(self) -> dict[str, Any]:
        catalog = self._catalog()
        with self._db() as c:
            rows = {r["device_id"]: dict(r) for r in c.execute("SELECT * FROM device_state")}
        devices = []
        for item in catalog.get("devices") or []:
            device = dict(item)
            saved = rows.get(str(device.get("id")))
            if saved:
                device.update({"state": saved["state"], "state_actor": saved["actor"], "state_note": saved["note"], "state_updated": saved["updated"]})
            devices.append(device)
        discoveries = self.discoveries()
        return {"policy": catalog.get("policy") or {}, "devices": devices, "discoveries": discoveries, "counts": {"total": len(devices), "trusted": sum(d.get("state") == "trusted" for d in devices), "unverified": sum(d.get("state") not in {"verified", "trusted"} for d in devices), "discovered": len(discoveries), "pending_approval": sum(d.get("decision") == "pending" for d in discoveries)}}

    @staticmethod
    def _read(path: Path) -> str:
        try:return path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:return ""

    @staticmethod
    def _fingerprint(transport: str, *parts: str) -> str:
        raw="|".join([transport, *(str(x).strip().lower() for x in parts)])
        return f"{transport}-{hashlib.sha256(raw.encode()).hexdigest()[:20]}"

    def _record_discovery(self, item: dict[str, Any]) -> None:
        now=time.time(); fingerprint=str(item["fingerprint"])
        with self._db() as c:
            old=c.execute("SELECT decision,first_seen,actor,note FROM discovered_devices WHERE fingerprint=?",(fingerprint,)).fetchone()
            decision=old["decision"] if old else "pending"
            first_seen=float(old["first_seen"]) if old else now
            actor=old["actor"] if old else "";note=old["note"] if old else ""
            c.execute("INSERT OR REPLACE INTO discovered_devices VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
                fingerprint,item["transport"],item.get("address",""),item.get("name",""),item.get("vendor",""),item.get("product",""),item.get("device_class",""),item.get("rssi"),item.get("proximity","unknown"),json.dumps(item.get("capabilities") or []),item.get("risk","unknown"),decision,first_seen,now,json.dumps(item.get("evidence") or {},sort_keys=True),json.dumps(item.get("analysis_plan") or [],sort_keys=True),actor,note))

    def scan_usb(self) -> dict[str, Any]:
        found=0
        for path in sorted(Path("/sys/bus/usb/devices").glob("*")):
            vid=self._read(path/"idVendor");pid=self._read(path/"idProduct")
            if not vid or not pid:continue
            vendor=self._read(path/"manufacturer");product=self._read(path/"product");serial=self._read(path/"serial")
            klass=self._read(path/"bDeviceClass").lower() or "00"
            interface_classes=sorted({self._read(p/"bInterfaceClass").lower() for p in path.parent.glob(path.name+":*") if self._read(p/"bInterfaceClass")})
            classes=interface_classes or [klass]
            caps=sorted({cap for code in classes for cap in USB_CAPABILITIES.get(code,["composite-or-vendor-specific" if code in {"00","ff"} else f"usb-class-{code}"])})
            risk="protected-host-device" if any(x in caps for x in ("mass-storage","human-interface","communications","wireless-controller")) else "unknown-device"
            identity=serial or f"{vendor}|{product}|{self._read(path/'bcdDevice')}|{path.name}"
            fingerprint=self._fingerprint("usb",vid,pid,identity)
            self._record_discovery({"fingerprint":fingerprint,"transport":"usb","address":path.name,"name":product or f"USB {vid}:{pid}","vendor":vendor,"product":product,"device_class":klass,"capabilities":caps,"risk":risk,"evidence":{"vid":vid,"pid":pid,"device_class":klass,"interface_classes":interface_classes,"serial_present":bool(serial),"fingerprint_collision_possible":not bool(serial),"sysfs_path":str(path)},"analysis_plan":["match VID/PID and interface classes against local databases","enumerate descriptors read-only","identify documented protocol and bound driver","propose isolated bench test; do not detach kernel driver or write endpoints"]})
            found+=1
        return {"transport":"usb","seen":found,"mutations":["candidate registry only"]}

    def scan_serial(self) -> dict[str, Any]:
        found = 0
        for port in sorted(Path("/sys/class/tty").glob("*")):
            if not re.fullmatch(r"tty(?:USB|ACM|S)[0-9]+", port.name): continue
            if not (port / "device").exists() or not Path("/dev", port.name).exists(): continue
            physical = (port / "device").resolve()
            ancestors = [physical, *physical.parents]
            usb = next((p for p in ancestors if (p / "idVendor").exists()), None)
            vid = self._read(usb / "idVendor") if usb else ""
            pid = self._read(usb / "idProduct") if usb else ""
            serial = self._read(usb / "serial") if usb else ""
            identity = str(physical)  # port-bound; a serial number alone is not proof of identity
            fp = self._fingerprint("serial", vid, pid, serial, identity)
            self._record_discovery({"fingerprint":fp,"transport":"serial","address":"/dev/"+port.name,
                "name": self._read(usb / "product") if usb else port.name,
                "capabilities":["serial-bench-exchange"],"risk":"opening-port-may-reset-device",
                "evidence":{"sysfs_path":str(physical),"vid":vid,"pid":pid,"serial_present":bool(serial),
                            "functionality_validated":False,"driver":str((physical/"driver").resolve()) if (physical/"driver").exists() else ""},
                "analysis_plan":["confirm device ownership, electrical levels, and port mapping",
                                 "approve one bounded listening/exchange session", "validate response against documented protocol"]})
            found += 1
        return {"transport":"serial","seen":found,"ports_opened":0}

    def lab_plan(self, fingerprint: str) -> dict[str, Any]:
        device=next((d for d in self.discoveries() if d["fingerprint"]==fingerprint),None)
        if not device: raise ValueError("device not found")
        return investigation_plan(device)

    def scan_bluetooth(self, timeout_seconds: int = 8, rssi_threshold: int = -70) -> dict[str, Any]:
        try:
            p=subprocess.run(["bluetoothctl","--timeout",str(max(3,min(timeout_seconds,20))),"scan","on"],text=True,capture_output=True,timeout=max(8,timeout_seconds+5),check=False)
            output=(p.stdout or "")+"\n"+(p.stderr or "")
        except (OSError,subprocess.TimeoutExpired) as exc:
            return {"transport":"bluetooth","seen":0,"error":type(exc).__name__,"mutations":["none"]}
        records:dict[str,dict[str,Any]]={}
        for line in output.splitlines():
            m=re.search(r"Device ([0-9A-Fa-f:]{17})(?: RSSI: (-?\d+)| (.+))",line)
            if not m:continue
            mac=m.group(1).upper();rec=records.setdefault(mac,{"name":"","rssi":None})
            if m.group(2):rec["rssi"]=int(m.group(2))
            elif m.group(3) and not m.group(3).startswith(("TxPower:","ManufacturerData","ServicesResolved")):rec["name"]=m.group(3).strip()
        for mac,rec in records.items():
            rssi=rec.get("rssi"); nearby=(rssi is not None and rssi>=rssi_threshold)
            self._record_discovery({"fingerprint":self._fingerprint("bluetooth",mac),"transport":"bluetooth","address":mac,"name":rec.get("name") or "Unnamed Bluetooth device","device_class":"advertisement","rssi":rssi,"proximity":"nearby-estimate" if nearby else "observed-distance-unknown","capabilities":["bluetooth-advertisement","services-unverified"],"risk":"private-or-third-party-device","evidence":{"rssi_dbm":rssi,"threshold_dbm":rssi_threshold,"distance_claim":False},"analysis_plan":["identify vendor from local OUI data","enumerate advertised service UUIDs without pairing","classify ownership and consent","after approval, propose pairing or protocol capture in an isolated lab"]})
        return {"transport":"bluetooth","seen":len(records),"nearby_estimate":sum((r.get("rssi") is not None and r["rssi"]>=rssi_threshold) for r in records.values()),"rssi_threshold_dbm":rssi_threshold,"distance_guaranteed":False,"mutations":["candidate registry only"]}

    def scan(self, *, bluetooth: bool = True, bluetooth_timeout: int = 8, rssi_threshold: int = -70) -> dict[str, Any]:
        result={"usb":self.scan_usb(),"serial":self.scan_serial(),"policy":"fingerprint and quarantine only; no pairing, endpoint writes, driver detach, authentication, or actuation"}
        if bluetooth:result["bluetooth"]=self.scan_bluetooth(bluetooth_timeout,rssi_threshold)
        return result

    def discoveries(self) -> list[dict[str, Any]]:
        with self._db() as c:rows=c.execute("SELECT * FROM discovered_devices ORDER BY last_seen DESC").fetchall()
        out=[]
        for row in rows:
            d=dict(row);d["capabilities"]=json.loads(d["capabilities"]);d["evidence"]=json.loads(d["evidence"]);d["analysis_plan"]=json.loads(d["analysis_plan"]);d["present"]=(Path(d["address"]).exists() if d["transport"]=="serial" else Path(d["evidence"].get("sysfs_path","/nonexistent")).exists() if d["transport"]=="usb" else None);out.append(d)
        return out

    def decide(self, fingerprint: str, decision: str, *, actor: str, note: str, confirmed: bool) -> dict[str, Any]:
        if decision not in {"approved_for_analysis","denied"}:raise ValueError("decision must approve analysis or deny")
        if not confirmed or not actor.strip() or not note.strip():raise ValueError("confirmed operator identity and reason are required")
        with self._db() as c:
            cur=c.execute("UPDATE discovered_devices SET decision=?,actor=?,note=? WHERE fingerprint=?",(decision,actor.strip(),note.strip(),fingerprint))
            if not cur.rowcount:raise ValueError("discovered fingerprint not found")
        return next(d for d in self.discoveries() if d["fingerprint"]==fingerprint)

    def _action_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:return None
        d=dict(row);d["parameters"]=json.loads(d["parameters"] or "{}");d["result"]=json.loads(d["result"] or "{}")
        spec=DEVICE_ACTIONS.get(d["action"],{});d["executor"]=spec.get("executor");d["execution_available"]=(spec.get("executor") == "serial_bench") or (spec.get("executor") in {"bluez_pair","bluez_connect"} and bool(self._which("bluetoothctl")))
        if spec.get("executor")=="verified_adapter":d["unavailable_reason"]="A signed, fingerprint-scoped adapter has not been installed and validated."
        elif not d["execution_available"]:d["unavailable_reason"]="bluetoothctl/BlueZ is unavailable on controller host."
        return d

    @staticmethod
    def _which(name: str) -> str:
        for base in ("/usr/bin","/usr/sbin","/bin","/sbin"):
            p=Path(base)/name
            if p.is_file():return str(p)
        return ""

    def action_capabilities(self) -> list[dict[str, Any]]:
        return [{"action":name,**spec,"execution_available":(spec["executor"] == "serial_bench" or (spec["executor"] in {"bluez_pair","bluez_connect"} and bool(self._which("bluetoothctl")))),"authorization_available":True} for name,spec in DEVICE_ACTIONS.items()]

    def request_action(self, fingerprint: str, action: str, *, actor: str, note: str, parameters: dict[str, Any] | None=None, ttl_seconds: int=900) -> dict[str, Any]:
        candidate=next((d for d in self.discoveries() if d["fingerprint"]==fingerprint),None)
        if not candidate:raise ValueError("discovered fingerprint not found")
        if candidate["decision"]!="approved_for_analysis":raise ValueError("candidate must first be approved for local analysis")
        spec=DEVICE_ACTIONS.get(action)
        if not spec:raise ValueError("unsupported device action")
        if spec["transport"] not in {"any",candidate["transport"]}:raise ValueError("action is incompatible with candidate transport")
        if not actor.strip() or not note.strip():raise ValueError("requester identity and purpose are required")
        aid=f"EDGE-{uuid.uuid4().hex[:16]}";now=time.time();ttl=max(60,min(int(ttl_seconds),3600))
        safe_parameters=self._validate_action_parameters(action,dict(parameters or {}))
        if action in {"pairing","authentication_attempt"}:safe_parameters={"address":candidate["address"]}
        with self._db() as c:c.execute("INSERT INTO device_actions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(aid,fingerprint,action,json.dumps(safe_parameters,sort_keys=True),spec["risk"],"pending",actor.strip(),note.strip(),now,now+ttl,"","",0.0,0.0,"{}"))
        with self._db() as c:return self._action_row(c.execute("SELECT * FROM device_actions WHERE id=?",(aid,)).fetchone()) or {}

    @staticmethod
    def _validate_action_parameters(action: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if action == "serial_exchange":
            baud=int(parameters.get("baud",9600));duration=int(parameters.get("duration_seconds",2));limit=int(parameters.get("max_bytes",4096))
            payload=str(parameters.get("payload_hex", ""))
            if baud not in (1200,2400,4800,9600,19200,38400,57600,115200) or not 1<=duration<=10 or not 1<=limit<=16384:
                raise ValueError("invalid serial bounds")
            if not re.fullmatch(r"(?:[0-9a-fA-F]{2}){0,256}",payload):raise ValueError("invalid serial payload")
            return {"baud":baud,"duration_seconds":duration,"max_bytes":limit,"payload_hex":payload.lower()}
        if action in {"pairing","authentication_attempt"}:return {}
        adapter=str(parameters.get("adapter_id") or "")
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}",adapter):raise ValueError("a verified adapter_id is required")
        out={"adapter_id":adapter}
        if action=="usb_endpoint_write":
            endpoint=int(parameters.get("endpoint",-1));payload=str(parameters.get("payload_hex") or "")
            if not 1<=endpoint<=255 or not re.fullmatch(r"(?:[0-9a-fA-F]{2}){1,512}",payload):raise ValueError("endpoint 1..255 and 1..512 bytes of payload_hex are required")
            out.update(endpoint=endpoint,payload_hex=payload.lower())
        elif action=="driver_detachment":
            driver=str(parameters.get("driver") or "");interface=str(parameters.get("interface") or "");delay=int(parameters.get("rebind_after_seconds",30))
            if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}",driver) or not re.fullmatch(r"[a-zA-Z0-9:._-]{1,96}",interface) or not 1<=delay<=300:raise ValueError("driver, interface, and rebind_after_seconds 1..300 are required")
            out.update(driver=driver,interface=interface,rebind_after_seconds=delay)
        elif action=="firmware_flashing":
            image=str(parameters.get("image_id") or "");digest=str(parameters.get("artifact_sha256") or "")
            if not re.fullmatch(r"[a-zA-Z0-9._-]{1,96}",image) or not re.fullmatch(r"[0-9a-f]{64}",digest):raise ValueError("image_id and lowercase artifact_sha256 are required")
            out.update(image_id=image,artifact_sha256=digest)
        elif action=="radio_command":
            command=str(parameters.get("command") or "");payload=str(parameters.get("payload_hex") or "")
            if not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}",command) or (payload and not re.fullmatch(r"(?:[0-9a-fA-F]{2}){1,256}",payload)):raise ValueError("bounded command and optional payload_hex are required")
            out.update(command=command,payload_hex=payload.lower())
        elif action=="location_access":
            duration=int(parameters.get("max_duration_seconds",60));scope=str(parameters.get("scope") or "one_time")
            if scope not in {"one_time","nearby_only"} or not 1<=duration<=300:raise ValueError("location scope and duration 1..300 seconds are required")
            out.update(scope=scope,max_duration_seconds=duration)
        elif action=="physical_movement":
            motion=str(parameters.get("motion") or "");duration=int(parameters.get("duration_ms",0));speed=int(parameters.get("speed_percent",0))
            if motion not in {"forward","reverse","left","right","stop"} or not 1<=duration<=2000 or not 0<=speed<=25:raise ValueError("bounded motion, duration_ms 1..2000, and speed_percent 0..25 are required")
            out.update(motion=motion,duration_ms=duration,speed_percent=speed)
        return out

    def actions(self) -> dict[str, Any]:
        with self._db() as c:rows=c.execute("SELECT * FROM device_actions ORDER BY created DESC LIMIT 500").fetchall()
        return {"actions":[self._action_row(r) for r in rows],"capabilities":self.action_capabilities(),"policy":{"approval_is_action_specific":True,"approval_expires":True,"arbitrary_commands":False,"secrets_in_parameters":False}}

    def decide_action(self, action_id: str, decision: str, *, actor: str, note: str, confirmed: bool) -> dict[str, Any]:
        if decision not in {"approved","denied"}:raise ValueError("decision must be approved or denied")
        if not confirmed or not actor.strip() or not note.strip():raise ValueError("confirmed operator identity and decision note are required")
        now=time.time()
        with self._db() as c:
            row=c.execute("SELECT * FROM device_actions WHERE id=?",(action_id,)).fetchone()
            if not row:raise ValueError("device action not found")
            if row["state"]!="pending":raise ValueError("only pending actions can be decided")
            if now>row["expires"]:c.execute("UPDATE device_actions SET state='expired' WHERE id=?",(action_id,));raise ValueError("device action approval window expired")
            c.execute("UPDATE device_actions SET state=?,decided_by=?,decision_note=?,decided=? WHERE id=?",(decision,actor.strip(),note.strip(),now,action_id))
            return self._action_row(c.execute("SELECT * FROM device_actions WHERE id=?",(action_id,)).fetchone()) or {}

    def execute_action(self, action_id: str, *, actor: str, confirmed: bool) -> dict[str, Any]:
        if not confirmed or not actor.strip():raise ValueError("confirmed executor identity is required")
        with self._db() as c:row=c.execute("SELECT * FROM device_actions WHERE id=?",(action_id,)).fetchone()
        action=self._action_row(row)
        if not action:raise ValueError("device action not found")
        if action["state"]!="approved":raise ValueError("device action is not approved")
        if time.time()>action["expires"]:raise ValueError("device action approval expired")
        if not action["execution_available"]:raise ValueError(action.get("unavailable_reason") or "executor unavailable")
        if action["action"] == "serial_exchange":
            candidate=next((d for d in self.discoveries() if d["fingerprint"]==action["fingerprint"]),None)
            if not candidate or candidate["decision"]!="approved_for_analysis":raise ValueError("device permission revoked")
            address=candidate["address"]
            if not re.fullmatch(r"/dev/tty(?:USB|ACM|S)[0-9]+",address):raise ValueError("invalid serial device")
            physical=Path("/sys/class/tty",Path(address).name,"device")
            if not physical.exists() or str(physical.resolve())!=candidate["evidence"].get("sysfs_path"):
                raise ValueError("device disconnected or mapping changed")
            # Refresh identity before consuming authorization, including USB serial/VID/PID.
            self.scan_serial()
            fresh=next((d for d in self.discoveries() if d["address"]==address),None)
            if not fresh or fresh["fingerprint"]!=action["fingerprint"]:raise ValueError("device identity changed")
            with self._db() as c:
                claimed=c.execute("UPDATE device_actions SET state='executing' WHERE id=? AND state='approved'",(action_id,))
                if not claimed.rowcount:raise ValueError("device action was already claimed for execution")
            try:result=serial_exchange(address,**action["parameters"])
            except Exception as exc:result={"ok":False,"error":str(exc)}
            with self._db() as c:
                c.execute("UPDATE device_actions SET state=?,executed=?,result=? WHERE id=?",("executed" if result.get("ok") else "failed",time.time(),json.dumps(result),action_id))
                return self._action_row(c.execute("SELECT * FROM device_actions WHERE id=?",(action_id,)).fetchone()) or {}
        address=str(action["parameters"].get("address") or "")
        if not re.fullmatch(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}",address):raise ValueError("approved Bluetooth address is invalid")
        with self._db() as c:
            claimed=c.execute("UPDATE device_actions SET state='executing' WHERE id=? AND state='approved'",(action_id,))
            if not claimed.rowcount:raise ValueError("device action was already claimed for execution")
        verb="pair" if action["action"]=="pairing" else "connect"
        exe=self._which("bluetoothctl")
        try:p=subprocess.run([exe,"--timeout","45",verb,address],text=True,capture_output=True,timeout=55,check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:result={"ok":False,"error":type(exc).__name__}
        else:result={"ok":p.returncode==0,"exit_code":p.returncode,"stdout":(p.stdout or "")[-4000:],"stderr":(p.stderr or "")[-2000:]}
        state="executed" if result.get("ok") else "failed";now=time.time()
        with self._db() as c:
            c.execute("UPDATE device_actions SET state=?,executed=?,result=? WHERE id=?",(state,now,json.dumps(result,sort_keys=True),action_id))
            return self._action_row(c.execute("SELECT * FROM device_actions WHERE id=?",(action_id,)).fetchone()) or {}

    def transition(self, device_id: str, new_state: str, *, actor: str, note: str, confirmed: bool) -> dict[str, Any]:
        devices = {str(d.get("id")): d for d in self.inventory()["devices"]}
        if device_id not in devices:
            raise ValueError("device not found")
        if new_state not in STATES:
            raise ValueError("invalid device state")
        old_state = str(devices[device_id].get("state") or "inventory")
        if new_state not in TRANSITIONS.get(old_state, set()):
            raise ValueError(f"transition {old_state} -> {new_state} is not allowed")
        if not confirmed or not actor.strip() or not note.strip():
            raise ValueError("confirmed operator identity and evidence note are required")
        now = time.time()
        with self._db() as c:
            c.execute("INSERT OR REPLACE INTO device_state VALUES(?,?,?,?,?)", (device_id, new_state, actor.strip(), note.strip(), now))
            c.execute("INSERT INTO device_events(device_id,old_state,new_state,actor,note,created) VALUES(?,?,?,?,?,?)", (device_id, old_state, new_state, actor.strip(), note.strip(), now))
        return next(d for d in self.inventory()["devices"] if d["id"] == device_id)

    def discovery_preview(self) -> dict[str, Any]:
        return {
            "mode": "preview_only",
            "mutated": False,
            "steps": [
                {"interface": "usb", "action": "record lsusb and /dev/serial/by-id identifiers", "approval": False},
                {"interface": "bluetooth", "action": "scan advertisements and estimate proximity from RSSI; do not pair", "approval": False},
                {"interface": "2.4ghz", "action": "record FCC/model labels; receive-only research", "approval": False},
                {"interface": "find-hub", "action": "verify ownership and select intended asset before pairing", "approval": True},
            ],
        }
