from __future__ import annotations

import sqlite3
import subprocess
import threading
import time
import hashlib
import html
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import yaml


class EnergyTracker:
    """Integrate readable component power sensors into a conservative kWh ledger.

    This deliberately does not call component readings "wall power". Motherboard,
    storage, fans, PSU loss, and devices without readable sensors are not included.
    """

    def __init__(self, config_file: str, ledger_file: str):
        self.config_file = Path(config_file)
        self.ledger_file = Path(ledger_file)
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        self._last_ts: float | None = None
        self._last_watts: float | None = None
        self._rapl: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()
        self._last_refresh_check = 0.0
        with sqlite3.connect(self.ledger_file) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS samples(
                ts REAL NOT NULL, watts REAL NOT NULL, kwh_delta REAL NOT NULL,
                cost_usd_delta REAL NOT NULL, coverage TEXT NOT NULL, sources TEXT NOT NULL
            )""")

    def _config(self) -> dict[str, Any]:
        try:
            return yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def _write_config(self, config: dict[str, Any]) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="energy-", suffix=".yaml", dir=self.config_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                yaml.safe_dump(config, stream, sort_keys=False)
                stream.flush(); os.fsync(stream.fileno())
            os.chmod(name, 0o640); os.replace(name, self.config_file)
        finally:
            try: os.unlink(name)
            except FileNotFoundError: pass

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        utility = str(payload.get("utility") or "").strip()
        provider_id = re.sub(r"[^a-z0-9-]", "-", str(payload.get("provider_id") or utility).lower()).strip("-")
        schedule = str(payload.get("schedule") or "RS").strip()
        source = str(payload.get("source_current") or "").strip()
        rate = float(payload.get("marginal_usd_per_kwh"))
        fixed = float(payload.get("fixed_service_charge_usd_per_month") or 0)
        effective = str(payload.get("effective_date") or "").strip()
        updater_type = str(payload.get("updater_type") or "manual")
        if not utility or not provider_id or not schedule: raise ValueError("utility, provider_id, and schedule are required")
        if not (.01 <= rate <= 1.0): raise ValueError("marginal rate must be between $0.01 and $1.00/kWh")
        if not (0 <= fixed <= 500): raise ValueError("fixed monthly charge must be between $0 and $500")
        try: datetime.strptime(effective, "%Y-%m-%d")
        except ValueError as exc: raise ValueError("effective_date must be YYYY-MM-DD") from exc
        if source and urlparse(source).scheme not in {"http", "https"}: raise ValueError("source_current must be HTTP(S)")
        if updater_type not in {"manual", "chickasaw_monthly_pdf"}: raise ValueError("unsupported updater type")
        if updater_type == "chickasaw_monthly_pdf" and provider_id != "chickasaw-electric":
            raise ValueError("Chickasaw updater can only be used with chickasaw-electric")
        old = self._config(); history = list(old.get("rate_history") or [])[-23:]
        prior = old.get("tariff") or {}
        if prior.get("effective_date") and prior.get("marginal_usd_per_kwh"):
            history.append({"effective_date":prior.get("effective_date"),"marginal_usd_per_kwh":prior.get("marginal_usd_per_kwh"),"source":prior.get("source_current"),"replaced_at":time.time()})
        config={
            "utility":utility,"service_area":str(payload.get("service_area") or ""),"provider_id":provider_id,
            "updater":{"type":updater_type,"rate_page":str(payload.get("rate_page") or ""),
                       "auto_update":bool(payload.get("auto_update",False)),"check_interval_hours":int(payload.get("check_interval_hours") or 24)},
            "tariff":{"schedule":schedule,"usage_tier":str(payload.get("usage_tier") or "all_kwh"),
                      "marginal_usd_per_kwh":rate,"fixed_service_charge_usd_per_month":fixed,
                      "effective_date":effective,"source_current":source,"refresh_required":"monthly"},
            "accounting":old.get("accounting") or {"include_fixed_charge_in_task_cost":False,"measurement_scope":"readable_component_sensors","whole_system_meter_present":False},
            "rate_history":history,
        }
        self._write_config(config); return self.status()

    def refresh_rate(self, force: bool = False) -> dict[str, Any]:
        config=self._config(); updater=config.get("updater") or {}
        if updater.get("type") != "chickasaw_monthly_pdf":
            return {"updated":False,"reason":"active provider uses manual updates"}
        page=str(updater.get("rate_page") or "https://billing.cecpowerup.com/onlineportal/Rates")
        parsed=urlparse(page)
        if parsed.hostname != "billing.cecpowerup.com": raise ValueError("untrusted Chickasaw rate source host")
        with httpx.Client(timeout=30,follow_redirects=True) as client:
            response=client.get(page);response.raise_for_status()
            if urlparse(str(response.url)).hostname != "billing.cecpowerup.com":
                raise ValueError("rate page redirected outside trusted host")
            links=[]
            for href in re.findall(r'href=["\']([^"\']*rates_(\d{6})\.pdf[^"\']*)',response.text,re.I):
                links.append((href[1],urljoin(page,html.unescape(href[0]))))
            if not links: raise RuntimeError("no monthly Chickasaw rate PDF links found")
            current=datetime.now(timezone.utc).strftime("%Y%m")
            eligible=[x for x in links if x[0] <= current]
            period,url=max(eligible or links,key=lambda x:x[0])
            if urlparse(url).hostname != "billing.cecpowerup.com": raise ValueError("rate PDF redirected outside trusted host")
            pdf=client.get(url);pdf.raise_for_status()
            if urlparse(str(pdf.url)).hostname != "billing.cecpowerup.com":
                raise ValueError("rate PDF redirected outside trusted host")
        proc=subprocess.run(["pdftotext","-layout","-","-"],input=pdf.content,capture_output=True,timeout=20,check=False)
        if proc.returncode != 0: raise RuntimeError("pdftotext is required for automatic Chickasaw updates")
        text=proc.stdout.decode(errors="replace")
        match=re.search(r"(?m)^\s*RS\s+\$([0-9.]+)\s+\$([0-9.]+)\s*$",text)
        if not match: raise RuntimeError("Chickasaw residential rate row could not be verified")
        fixed,rate=map(float,match.groups())
        tariff=config.get("tariff") or {}; old_period=str(tariff.get("effective_date") or "")[:7].replace("-","")
        same_values=(abs(float(tariff.get("marginal_usd_per_kwh") or 0)-rate)<0.000001 and
                     abs(float(tariff.get("fixed_service_charge_usd_per_month") or 0)-fixed)<0.001)
        if not force and period < old_period:
            return {"updated":False,"reason":"published rate is older than configured rate","period":period}
        if not force and period == old_period and same_values:
            return {"updated":False,"reason":"rate is current","period":period}
        history=list(config.get("rate_history") or [])[-23:]
        if tariff: history.append({**tariff,"replaced_at":time.time()})
        tariff.update({"schedule":"RS","usage_tier":"all_kwh","marginal_usd_per_kwh":rate,
                       "fixed_service_charge_usd_per_month":fixed,"effective_date":f"{period[:4]}-{period[4:]}-01",
                       "source_current":url,"source_sha256":hashlib.sha256(pdf.content).hexdigest(),"retrieved_at":time.time(),"refresh_required":"monthly"})
        config["tariff"]=tariff;config["rate_history"]=history;self._write_config(config)
        return {"updated":True,"period":period,"marginal_usd_per_kwh":rate,"fixed_service_charge_usd_per_month":fixed,"source_sha256":tariff["source_sha256"]}

    def maybe_refresh(self) -> None:
        now=time.time();config=self._config();updater=config.get("updater") or {}
        interval=max(1,int(updater.get("check_interval_hours") or 24))*3600
        if not updater.get("auto_update") or now-self._last_refresh_check < interval:return
        self._last_refresh_check=now
        self.refresh_rate(force=False)

    @staticmethod
    def _nvidia() -> list[dict[str, Any]]:
        try:
            proc = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,power.draw", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=8, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        rows = []
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                try:
                    name, raw = line.rsplit(",", 1)
                    rows.append({"source": "nvidia-smi", "device": name.strip(), "watts": round(float(raw), 3)})
                except (ValueError, TypeError):
                    continue
        return rows

    @staticmethod
    def _hwmon(skip_nvidia: bool) -> list[dict[str, Any]]:
        rows = []
        for root in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            try:
                name = (root / "name").read_text().strip()
            except OSError:
                name = root.name
            if skip_nvidia and "nvidia" in name.lower():
                continue
            candidates = sorted(root.glob("power*_average")) or sorted(root.glob("power*_input"))
            if not candidates:
                continue
            # One aggregate sensor per hwmon device avoids summing duplicate rails.
            path = candidates[0]
            try:
                watts = float(path.read_text().strip()) / 1_000_000
            except (OSError, ValueError):
                continue
            if 0 <= watts <= 5000:
                rows.append({"source": "hwmon", "device": name, "sensor": path.name, "watts": round(watts, 3)})
        return rows

    def _rapl_watts(self, now: float) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(Path("/sys/class/powercap").glob("intel-rapl*/energy_uj")):
            try:
                energy = int(path.read_text().strip())
                name_path = path.parent / "name"
                name = name_path.read_text().strip() if name_path.exists() else path.parent.name
            except (OSError, ValueError):
                continue
            prior = self._rapl.get(str(path)); self._rapl[str(path)] = (now, energy)
            if not prior or now <= prior[0] or energy < prior[1]:
                continue
            watts = ((energy - prior[1]) / 1_000_000) / (now - prior[0])
            if 0 <= watts <= 2000:
                rows.append({"source": "intel-rapl", "device": name, "watts": round(watts, 3)})
        return rows

    def sample(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            nvidia = self._nvidia()
            sources = nvidia + self._hwmon(bool(nvidia)) + self._rapl_watts(now)
            watts = round(sum(float(x["watts"]) for x in sources), 3)
            config = self._config(); rate = float((config.get("tariff") or {}).get("marginal_usd_per_kwh") or 0)
            delta = 0.0
            if sources and self._last_ts is not None and self._last_watts is not None:
                elapsed = min(max(0.0, now - self._last_ts), 300.0)
                delta = ((self._last_watts + watts) / 2.0) * elapsed / 3_600_000.0
            coverage = "component_metered_estimate" if sources else "unmetered"
            with sqlite3.connect(self.ledger_file) as db:
                db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?)", (now, watts, delta, delta * rate, coverage, json.dumps(sources)))
                db.execute("DELETE FROM samples WHERE ts < ?", (now - 90 * 86400,))
            self._last_ts, self._last_watts = now, watts
            return {"ts": now, "watts": watts, "sources": sources, "coverage": coverage}

    def status(self) -> dict[str, Any]:
        now = time.time(); config = self._config(); tariff = config.get("tariff") or {}
        day = now - 86400; month = now - 31 * 86400
        with sqlite3.connect(self.ledger_file) as db:
            latest = db.execute("SELECT ts,watts,coverage,sources FROM samples ORDER BY ts DESC LIMIT 1").fetchone()
            daily = db.execute("SELECT COALESCE(SUM(kwh_delta),0),COALESCE(SUM(cost_usd_delta),0) FROM samples WHERE ts>=?", (day,)).fetchone()
            monthly = db.execute("SELECT COALESCE(SUM(kwh_delta),0),COALESCE(SUM(cost_usd_delta),0) FROM samples WHERE ts>=?", (month,)).fetchone()
        live = {"ts": latest[0], "watts": latest[1], "coverage": latest[2], "sources": json.loads(latest[3])} if latest else {"coverage": "unmetered", "sources": []}
        rate = float(tariff.get("marginal_usd_per_kwh") or 0)
        if live.get("sources"):
            state = "component_metered_estimate" if rate > 0 else "component_metered_tariff_unconfigured"
        else:
            state = "tariff_configured_usage_unmetered" if rate > 0 else "tariff_unconfigured_usage_unmetered"
        return {
            "state": state,
            "utility": config.get("utility"), "service_area": config.get("service_area"), "provider_id": config.get("provider_id"),
            "updater": {**(config.get("updater") or {}),
                        "dependency_ready": bool(shutil.which("pdftotext")),
                        "dependency": "pdftotext"},
            "tariff": tariff, "rate_history": config.get("rate_history") or [],
            "live": live,
            "today": {"kwh": round(float(daily[0]), 6), "cost_usd": round(float(daily[1]), 6)},
            "rolling_31_days": {"kwh": round(float(monthly[0]), 6), "cost_usd": round(float(monthly[1]), 6)},
            "truth_note": "Component sensors exclude unmetered host loads and PSU losses; connect a wall meter for whole-system energy.",
        }
