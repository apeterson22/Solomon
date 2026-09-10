from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import time
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml


_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:password|passwd|secret|api[_ -]?key|token)\s*[:=]\s*\S+", re.I),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
]

_COMPLEX_HINTS = {
    "analyze": .08, "analysis": .08, "architecture": .10, "design": .08,
    "research": .10, "compare": .07, "evaluate": .07, "optimize": .08,
    "simulation": .10, "mathemat": .10, "debug": .07, "diagnose": .07,
    "strategy": .07, "tradeoff": .08, "trade-off": .08, "multi-step": .08,
    "comprehensive": .08, "in depth": .08, "reasoning": .06, "plan": .05,
    "code": .05, "script": .05, "security": .08, "legal": .10,
}


def estimate_tokens(text: str) -> int:
    # Deliberately conservative for quota reservation across mixed tokenizers.
    return max(1, int(len(text) / 3.2) + 8)


def complexity_score(text: str) -> float:
    t = (text or "").strip().lower()
    score = .18
    n = len(t)
    if n > 250: score += .08
    if n > 700: score += .10
    if n > 1600: score += .12
    if "```" in t: score += .08
    score += min(.18, t.count("?") * .025)
    for k, w in _COMPLEX_HINTS.items():
        if k in t: score += w
    return round(min(1.0, score), 4)


def contains_sensitive(text: str) -> bool:
    return any(p.search(text or "") for p in _SECRET_PATTERNS)


@dataclass
class Provider:
    name: str
    kind: str
    enabled: bool
    model: str
    billing_mode: str
    allow_overage: bool
    priority: int
    max_output_tokens: int
    api_key_file: str = ""
    endpoint: str = ""
    max_ai_credits_per_call: int = 0
    account_overage_disabled: bool = False
    upstream_hard_cap_confirmed: bool = False
    max_cost_microusd_per_call: int = 0
    limits: dict[str, int] | None = None
    configured_reason: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Provider":
        return cls(
            name=str(d.get("name") or "provider"),
            kind=str(d.get("kind") or "openai_compatible"),
            enabled=bool(d.get("enabled", False)),
            model=str(d.get("model") or ""),
            billing_mode=str(d.get("billing_mode") or "unknown"),
            allow_overage=bool(d.get("allow_overage", False)),
            priority=int(d.get("priority", 100)),
            max_output_tokens=int(d.get("max_output_tokens", 2048)),
            api_key_file=str(d.get("api_key_file") or ""),
            endpoint=str(d.get("endpoint") or ""),
            max_ai_credits_per_call=int(d.get("max_ai_credits_per_call", 0)),
            account_overage_disabled=bool(d.get("account_overage_disabled", False)),
            upstream_hard_cap_confirmed=bool(d.get("upstream_hard_cap_confirmed", False)),
            max_cost_microusd_per_call=max(0, int(d.get("max_cost_microusd_per_call", 0))),
            limits={str(k): int(v) for k, v in (d.get("limits") or {}).items() if int(v) >= 0},
            configured_reason=str(d.get("configured_reason") or ""),
        )


class QuotaLedger:
    """Local hard-stop accounting.

    Reservations are intentionally conservative: reserved amounts are not refunded.
    This can under-use a subscription quota, but it prevents SolomonPrime from
    knowingly crossing its own configured ceiling.
    """

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS usage(
                provider TEXT NOT NULL,
                period TEXT NOT NULL,
                metric TEXT NOT NULL,
                value INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(provider, period, metric)
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS events(
                ts REAL, provider TEXT, event TEXT, data TEXT
            )""")

    @staticmethod
    def _period(metric: str) -> str:
        now = time.gmtime()
        if metric.startswith("daily_"):
            return time.strftime("%Y-%m-%d", now)
        return time.strftime("%Y-%m", now)

    def used(self, provider: str, metric: str) -> int:
        period = self._period(metric)
        with sqlite3.connect(self.path) as c:
            row = c.execute("SELECT value FROM usage WHERE provider=? AND period=? AND metric=?", (provider, period, metric)).fetchone()
        return int(row[0]) if row else 0

    def can_reserve(self, provider: Provider, reservations: dict[str, int], margin: float) -> tuple[bool, str]:
        limits = provider.limits or {}
        required = ("daily_requests", "monthly_requests", "monthly_ai_credits") if provider.kind == "copilot_cli" else ("daily_requests", "monthly_requests", "monthly_input_tokens", "monthly_output_tokens")
        if any(int(limits.get(k, 0)) <= 0 for k in required):
            return False, "quota limits are incomplete; unknown quota policy is deny"
        for metric, amount in reservations.items():
            cap = int(limits.get(metric, 0) * margin)
            if cap <= 0:
                return False, f"no hard cap configured for {metric}"
            if self.used(provider.name, metric) + int(amount) > cap:
                return False, f"configured {metric} budget exhausted"
        return True, "ok"

    def reserve(self, provider: Provider, reservations: dict[str, int], data: dict[str, Any] | None = None):
        with sqlite3.connect(self.path) as c:
            for metric, amount in reservations.items():
                period = self._period(metric)
                c.execute("""INSERT INTO usage(provider,period,metric,value) VALUES(?,?,?,?)
                    ON CONFLICT(provider,period,metric) DO UPDATE SET value=value+excluded.value""",
                    (provider.name, period, metric, int(amount)))
            c.execute("INSERT INTO events VALUES(?,?,?,?)", (time.time(), provider.name, "reserve", json.dumps(data or {})))

    def status(self, providers: list[Provider], margin: float) -> dict[str, Any]:
        out = []
        for p in providers:
            limits = p.limits or {}
            metrics = {}
            for m, raw_cap in limits.items():
                if m not in {"daily_requests","monthly_requests","monthly_input_tokens","monthly_output_tokens","monthly_ai_credits","monthly_cost_microusd"}:
                    continue
                cap = int(raw_cap * margin)
                used = self.used(p.name, m)
                metrics[m] = {"used": used, "hard_stop": cap, "remaining": max(0, cap-used), "configured_limit": raw_cap}
            monitoring = "live pre-call finite key-limit check" if p.kind == "openrouter" else "provider dashboard plus conservative local ledger"
            out.append({"name": p.name, "kind": p.kind, "enabled": p.enabled, "billing_mode": p.billing_mode,
                        "allow_overage": p.allow_overage, "model": p.model, "quota": metrics,
                        "upstream_hard_cap_confirmed":p.upstream_hard_cap_confirmed,
                        "configured_reason":p.configured_reason or ("enabled" if p.enabled else "disabled by configuration"),
                        "upstream_monitoring": monitoring})
        return {"providers": out, "policy": "hard-local-ledger-no-overage", "margin": margin}


class CloudRouter:
    def __init__(self, config_file: str, ledger_file: str, training_dir: str,
                 complexity_threshold: float = .72, quota_margin: float = .90,
                 max_calls_per_request: int = 1, capture_training: bool = True,
                 sensitive_policy: str = "deny"):
        self.config_file = config_file
        self.ledger = QuotaLedger(ledger_file)
        self.training_dir = Path(training_dir)
        self.training_dir.mkdir(parents=True, exist_ok=True)
        self.complexity_threshold = float(complexity_threshold)
        self.quota_margin = max(.5, min(.99, float(quota_margin)))
        self.max_calls_per_request = max(0, min(3, int(max_calls_per_request)))
        self.capture_training = bool(capture_training)
        self.sensitive_policy = sensitive_policy
        self.runtime_policy_file = Path(ledger_file).with_name("orchestration-policy.yaml")
        self.consensus_threshold = .90

    def _apply_runtime_policy(self) -> dict[str, Any]:
        try: raw=yaml.safe_load(self.runtime_policy_file.read_text()) or {}
        except Exception: raw={}
        if raw:
            self.complexity_threshold=max(.5,min(1.0,float(raw.get("complexity_threshold",self.complexity_threshold))))
            self.max_calls_per_request=max(1,min(2,int(raw.get("max_calls_per_request",self.max_calls_per_request))))
            self.consensus_threshold=max(self.complexity_threshold,min(1.0,float(raw.get("consensus_threshold",self.consensus_threshold))))
        return raw

    def configure_runtime(self, payload: dict[str, Any]) -> dict[str, Any]:
        threshold=float(payload.get("complexity_threshold",self.complexity_threshold))
        calls=int(payload.get("max_calls_per_request",self.max_calls_per_request))
        consensus=float(payload.get("consensus_threshold",self.consensus_threshold))
        if not .5 <= threshold <= 1.0:raise ValueError("complexity threshold must be between 0.50 and 1.00")
        if calls not in {1,2}:raise ValueError("maximum advisors must be 1 or 2")
        if not threshold <= consensus <= 1.0:raise ValueError("consensus threshold must be between complexity threshold and 1.00")
        data={"mode":"free_only","complexity_threshold":threshold,"max_calls_per_request":calls,
              "consensus_threshold":consensus,"updated_at":time.time()}
        self.runtime_policy_file.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix="orchestration-",suffix=".yaml",dir=self.runtime_policy_file.parent)
        try:
            with os.fdopen(fd,"w") as stream:yaml.safe_dump(data,stream,sort_keys=False);stream.flush();os.fsync(stream.fileno())
            os.chmod(name,0o640);os.replace(name,self.runtime_policy_file)
        finally:
            try:os.unlink(name)
            except FileNotFoundError:pass
        self._apply_runtime_policy();return self.status()

    def _raw(self) -> dict[str, Any]:
        p = Path(self.config_file)
        if not p.exists(): return {}
        try: return yaml.safe_load(p.read_text()) or {}
        except Exception: return {}

    def providers(self) -> list[Provider]:
        raw = self._raw()
        ps = [Provider.from_dict(x) for x in (raw.get("providers") or [])]
        return sorted(ps, key=lambda x: x.priority)

    def status(self) -> dict[str, Any]:
        runtime=self._apply_runtime_policy()
        s = self.ledger.status(self.providers(), self.quota_margin)
        raw_policy = self._raw().get("policy") or {}
        s.update({"complexity_threshold": self.complexity_threshold,
                  "max_calls_per_request": self.max_calls_per_request,
                  "sensitive_policy": self.sensitive_policy,
                  "routing": {**raw_policy,**runtime,"mode":"free_only"},
                  "consensus_threshold":self.consensus_threshold})
        return s

    def should_escalate(self, text: str, force: bool = False) -> tuple[bool, float, str]:
        self._apply_runtime_policy()
        score = complexity_score(text)
        if self.max_calls_per_request < 1: return False, score, "cloud calls disabled"
        if contains_sensitive(text) and self.sensitive_policy == "deny":
            return False, score, "sensitive-content policy denied cloud routing"
        if force: return True, score, "operator forced bounded cloud advisory"
        if score < self.complexity_threshold: return False, score, "local model sufficient by complexity policy"
        return True, score, "complexity threshold reached"

    @staticmethod
    def _key(p: Provider) -> str:
        f = Path(p.api_key_file) if p.api_key_file else None
        return f.read_text().strip() if f and f.exists() else ""

    def _eligible(self, p: Provider, input_tokens: int) -> tuple[bool, str, dict[str,int]]:
        if not p.enabled: return False, "disabled", {}
        if p.allow_overage: return False, "allow_overage must remain false", {}
        if p.billing_mode not in {"free", "subscription-included", "prepaid-hard-cap"}:
            return False, f"billing_mode={p.billing_mode} is not allowed in zero-overage mode", {}
        if p.billing_mode == "prepaid-hard-cap" and (not p.upstream_hard_cap_confirmed or p.max_cost_microusd_per_call <= 0):
            return False, "paid provider requires confirmed upstream hard cap and per-call reserve", {}
        if p.kind == "openai" and p.billing_mode == "free":
            return False, "OpenAI API is metered and cannot be enabled by the free-only policy", {}
        if p.kind == "ollama_cloud" and (p.billing_mode not in {"free","subscription-included"} or not p.account_overage_disabled):
            return False, "Ollama cloud requires confirmed free/included quota with additional charges disabled", {}
        if p.kind == "copilot_cli" and not p.account_overage_disabled:
            return False, "Copilot account-level additional usage must be disabled", {}
        if p.kind not in {"copilot_cli", "ollama_local", "ollama_cloud"} and not self._key(p):
            return False, "credential missing", {}
        if p.kind == "copilot_cli":
            reservations = {
                "daily_requests": 1,
                "monthly_requests": 1,
                "monthly_ai_credits": max(1, p.max_ai_credits_per_call),
            }
        else:
            reservations = {
                "daily_requests": 1,
                "monthly_requests": 1,
                "monthly_input_tokens": input_tokens,
                "monthly_output_tokens": p.max_output_tokens,
            }
            if p.billing_mode == "prepaid-hard-cap":
                reservations["monthly_cost_microusd"] = p.max_cost_microusd_per_call
        ok, why = self.ledger.can_reserve(p, reservations, self.quota_margin)
        return ok, why, reservations

    async def _call_openai_compatible(self, p: Provider, prompt: str, system: str) -> tuple[str, dict[str,Any]]:
        headers = {"Content-Type":"application/json"}
        if self._key(p): headers["Authorization"] = f"Bearer {self._key(p)}"
        payload = {"model":p.model, "messages":[{"role":"system","content":system},{"role":"user","content":prompt}],
                   "temperature":.2, "max_tokens":p.max_output_tokens, "stream":False}
        async with httpx.AsyncClient(timeout=httpx.Timeout(180,read=None)) as c:
            r = await c.post(p.endpoint.rstrip("/")+"/chat/completions", headers=headers, json=payload)
        r.raise_for_status(); obj=r.json()
        text=str((((obj.get("choices") or [{}])[0].get("message") or {}).get("content")) or "")
        return text, obj.get("usage") or {}

    async def _call_gemini(self, p: Provider, prompt: str, system: str) -> tuple[str, dict[str,Any]]:
        key=self._key(p)
        endpoint=(p.endpoint or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        url=f"{endpoint}/models/{p.model}:generateContent"
        payload={"systemInstruction":{"parts":[{"text":system}]},
                 "contents":[{"role":"user","parts":[{"text":prompt}]}],
                 "generationConfig":{"maxOutputTokens":p.max_output_tokens,"temperature":.2}}
        async with httpx.AsyncClient(timeout=httpx.Timeout(180,read=None)) as c:r=await c.post(url,headers={"x-goog-api-key":key},json=payload)
        r.raise_for_status();obj=r.json();parts=((((obj.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or [])
        text="".join(str(x.get("text") or "") for x in parts if isinstance(x,dict))
        return text,obj.get("usageMetadata") or {}

    async def _call_copilot_cli(self, p: Provider, prompt: str, system: str) -> tuple[str, dict[str,Any]]:
        exe=shutil.which("copilot")
        if not exe: raise RuntimeError("copilot CLI not installed")
        combined=f"{system}\n\nUSER REQUEST:\n{prompt}"
        cmd=[exe,"-p",combined]
        if p.model:cmd += ["--model",p.model]
        if p.max_ai_credits_per_call > 0:cmd += ["--max-ai-credits",str(p.max_ai_credits_per_call)]
        proc=await __import__("asyncio").create_subprocess_exec(*cmd,stdout=__import__("asyncio").subprocess.PIPE,stderr=__import__("asyncio").subprocess.PIPE)
        out,err=await proc.communicate()
        if proc.returncode!=0:raise RuntimeError((err or out).decode(errors="replace")[-2000:])
        return out.decode(errors="replace"),{"ai_credits_reserved":p.max_ai_credits_per_call}

    def _capture(self, prompt: str, provider: Provider, response: str, score: float, reason: str):
        if not self.capture_training:return
        rec={"ts":time.time(),"prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),"prompt":prompt,
             "provider":provider.name,"model":provider.model,"teacher_response":response,"complexity":score,
             "route_reason":reason,"status":"candidate","production_promoted":False}
        f=self.training_dir/"cloud-teacher-candidates.jsonl"
        with f.open("a",encoding="utf-8") as h:h.write(json.dumps(rec,ensure_ascii=False)+"\n")

    async def _upstream_gate(self,p:Provider)->tuple[bool,str,dict[str,Any]]:
        if p.kind != "openrouter":return True,"not-required",{}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r=await c.get("https://openrouter.ai/api/v1/key",headers={"Authorization":f"Bearer {self._key(p)}"})
            r.raise_for_status();data=(r.json().get("data") or {})
            remaining=data.get("limit_remaining");limit=data.get("limit")
            if limit is None or remaining is None:return False,"OpenRouter key has no finite credit limit",data
            reserve=p.max_cost_microusd_per_call/1_000_000
            if float(remaining)<reserve:return False,"OpenRouter remaining key credit is below per-call reserve",data
            return True,"ok",{"limit":limit,"limit_remaining":remaining,"usage_monthly":data.get("usage_monthly")}
        except Exception as e:return False,f"OpenRouter key-limit check failed: {type(e).__name__}",{}

    async def advise(self, prompt: str, force: bool = False, preferred_provider: str = "") -> dict[str,Any]:
        should,score,reason=self.should_escalate(prompt,force=force)
        if not should:return {"used":False,"complexity":score,"reason":reason}
        input_tokens=estimate_tokens(prompt)+220
        denied=[]
        system=("You are a bounded cloud expert advising a local-first AI system. Return concise, high-value analysis. "
                "Do not claim access to the local machine, its private memory, or current hardware unless explicitly provided. "
                "Identify uncertainty. Your answer is advisory; the local model verifies and synthesizes the final response.")
        providers=[p for p in self.providers() if not preferred_provider or p.kind==preferred_provider or p.name==preferred_provider]
        # Ordinary complex requests use one advisor. Very-high-complexity requests
        # use two independent zero-cost advisors before the local orchestrator
        # synthesizes the final answer. Explicit provider selection remains one call.
        target_calls=1 if preferred_provider else min(self.max_calls_per_request,2 if score>=self.consensus_threshold else 1)
        answers=[]
        for p in providers:
            ok,why,reservations=self._eligible(p,input_tokens)
            if not ok:
                denied.append({"provider":p.name,"reason":why});continue
            upstream_ok,upstream_why,upstream=await self._upstream_gate(p)
            if not upstream_ok:
                denied.append({"provider":p.name,"reason":upstream_why});continue
            # Reserve before the network call. Conservative no-refund accounting is intentional.
            self.ledger.reserve(p,reservations,{"complexity":score,"model":p.model})
            try:
                if p.kind=="gemini": text,usage=await self._call_gemini(p,prompt,system)
                elif p.kind=="copilot_cli": text,usage=await self._call_copilot_cli(p,prompt,system)
                else: text,usage=await self._call_openai_compatible(p,prompt,system)
                self._capture(prompt,p,text,score,reason)
                answers.append({"provider":p.name,"model":p.model,"content":text,"upstream":upstream,"usage":usage})
                if len(answers)>=target_calls:break
            except Exception as e:
                denied.append({"provider":p.name,"reason":f"call failed: {type(e).__name__}: {str(e)[:500]}"})
                continue
        if answers:
            combined="\n\n".join(f"ADVISOR {i+1} ({a['provider']} / {a['model']}):\n{a['content']}" for i,a in enumerate(answers))
            return {"used":True,"provider":answers[0]["provider"],"model":answers[0]["model"],"content":combined,
                    "advisors":[{k:v for k,v in a.items() if k!='content'} for a in answers],"complexity":score,
                    "reason":reason,"denied":denied,"quota_policy":"reserved-before-call; free/included quota only"}
        return {"used":False,"complexity":score,"reason":"no eligible zero-overage cloud provider","denied":denied}
