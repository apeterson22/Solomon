from __future__ import annotations

import secrets
import base64
import hashlib
import hmac
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
import yaml

WORDS=("amber","cedar","delta","field","harbor","lantern","maple","orbit","river","solar","timber","violet")

class VoiceSecurity:
    """Voice readiness and fresh challenge ledger. Voice never grants authority alone."""
    def __init__(self,config_path:str,db_path:str,session_secret:str=""):
        self.config_path=Path(config_path);self.db_path=Path(db_path);self.db_path.parent.mkdir(parents=True,exist_ok=True)
        self.session_secret=(session_secret or secrets.token_hex(32)).encode()
        with sqlite3.connect(self.db_path) as c:c.execute("CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY, action_id TEXT, device_session TEXT, phrase TEXT, created REAL, expires REAL, used INTEGER DEFAULT 0)")

    def config(self)->dict[str,Any]:
        try:return yaml.safe_load(self.config_path.read_text()) or {}
        except OSError:return {}

    def status(self)->dict[str,Any]:
        c=self.config();stt=c.get("stt") or {};tts=c.get("tts") or {};sv=c.get("speaker_verification") or {}
        def ready(command:str)->bool:return bool(command and (Path(command).is_file() or shutil.which(command)))
        checks={"stt":ready(str(stt.get("command") or "")) and Path(str(stt.get("model") or "")).is_file(),
                "tts":ready(str(tts.get("command") or "")) and Path(str(tts.get("model") or "")).is_file(),
                "speaker_verifier":ready(str(sv.get("command") or "")),"speaker_enrolled":bool(sv.get("enrolled_template"))}
        enabled=bool(c.get("enabled")) and all(checks.values())
        return {"state":"ready" if enabled else "configuration_required","enabled":enabled,"checks":checks,
                "voice_name":c.get("voice_name","SolomonPrime"),"approval_policy":c.get("approval") or {},
                "privacy":c.get("privacy") or {},"browser_requirement":"HTTPS is required for dependable microphone access",
                "mobile":{"gateway_state":"https_setup_available","tricorder_app_state":"source_integrated_android_sdk_required","source_path":"/apps/solomonprime/app/mobile/tricorder-prime","production_signing":"operator_local_required"},
                "truth_note":"Speaker identity is an additional factor, never the sole authorization factor."}

    def issue_session(self,actor:str,device_id:str,ttl_seconds:int=900)->dict[str,Any]:
        if not actor.strip() or not device_id.strip():raise ValueError("actor and device_id are required")
        now=int(time.time());ttl=max(60,min(3600,int(ttl_seconds)))
        payload={"actor":actor.strip(),"device_id":device_id.strip(),"issued":now,"expires":now+ttl,"nonce":secrets.token_hex(12)}
        raw=json.dumps(payload,separators=(",",":"),sort_keys=True).encode()
        encoded=base64.urlsafe_b64encode(raw).rstrip(b"=")
        mac=hmac.new(self.session_secret,encoded,hashlib.sha256).hexdigest().encode()
        return {"device_session":(encoded+b"."+mac).decode(),"expires":payload["expires"],"device_id":payload["device_id"]}

    def _session(self,token:str)->dict[str,Any]:
        try:
            encoded,provided=token.encode().rsplit(b".",1)
            expected=hmac.new(self.session_secret,encoded,hashlib.sha256).hexdigest().encode()
            if not hmac.compare_digest(provided,expected):raise ValueError
            raw=base64.urlsafe_b64decode(encoded+b"="*((4-len(encoded)%4)%4));payload=json.loads(raw)
            if int(payload.get("expires") or 0)<int(time.time()):raise ValueError
            return payload
        except Exception as exc:raise ValueError("invalid or expired signed device_session") from exc

    def challenge(self,action_id:str,device_session:str)->dict[str,Any]:
        if not action_id or not device_session:raise ValueError("action_id and signed device_session are required")
        session=self._session(device_session)
        phrase=" ".join(secrets.choice(WORDS) for _ in range(4));now=time.time();ttl=int((self.config().get("approval") or {}).get("challenge_ttl_seconds",90));cid=secrets.token_hex(16)
        session_hash=hashlib.sha256(device_session.encode()).hexdigest()
        with sqlite3.connect(self.db_path) as c:c.execute("INSERT INTO challenges VALUES(?,?,?,?,?,?,0)",(cid,action_id,session_hash,phrase,now,now+ttl))
        return {"challenge_id":cid,"action_id":action_id,"device_id":session["device_id"],"phrase":phrase,"expires":now+ttl,"factors_required":["signed device session","fresh spoken challenge","server-side speaker match","existing action approval"]}

    def verify_challenge(self,challenge_id:str,action_id:str,device_session:str,transcript:str,audio:bytes,suffix:str=".wav")->dict[str,Any]:
        self._session(device_session)
        if len(audio)>10*1024*1024:raise ValueError("verification audio exceeds 10 MiB")
        session_hash=hashlib.sha256(device_session.encode()).hexdigest();now=time.time()
        with sqlite3.connect(self.db_path) as c:
            row=c.execute("SELECT phrase,expires,used FROM challenges WHERE id=? AND action_id=? AND device_session=?",(challenge_id,action_id,session_hash)).fetchone()
        if not row or row[2] or float(row[1])<now:raise ValueError("challenge is missing, expired, used, or not bound to this action/session")
        clean=lambda s:" ".join(re.sub(r"[^a-z0-9 ]"," ",(s or "").lower()).split())
        if not hmac.compare_digest(clean(transcript),clean(str(row[0]))):raise ValueError("spoken challenge phrase did not match")
        cfg=self.config();sv=cfg.get("speaker_verification") or {};command=str(sv.get("command") or "");enrollment=str(sv.get("enrolled_template") or "")
        if not command or not enrollment or not Path(enrollment).is_file():raise RuntimeError("local speaker verifier and enrollment are not configured")
        suffix=suffix if suffix in {".wav",".mp3",".m4a",".ogg",".webm"} else ".wav"
        with tempfile.TemporaryDirectory(prefix="solomon-speaker-") as d:
            sample=Path(d)/("sample"+suffix);sample.write_bytes(audio)
            p=subprocess.run([command,"--enrollment",enrollment,"--audio",str(sample)],capture_output=True,text=True,timeout=90,check=False)
        if p.returncode:raise RuntimeError((p.stderr or "speaker verification failed")[-500:])
        try:result=json.loads(p.stdout)
        except Exception as exc:raise RuntimeError("speaker verifier did not return JSON") from exc
        score=float(result.get("score") or 0);threshold=float(sv.get("threshold") or .82);liveness=bool(result.get("liveness"))
        if result.get("match") is not True or score<threshold or (sv.get("liveness_required",True) and not liveness):
            raise ValueError("speaker match or liveness threshold failed")
        with sqlite3.connect(self.db_path) as c:
            changed=c.execute("UPDATE challenges SET used=1 WHERE id=? AND used=0 AND expires>=?",(challenge_id,time.time())).rowcount
        if changed!=1:raise ValueError("challenge was already consumed")
        return {"verified":True,"challenge_id":challenge_id,"action_id":action_id,"speaker_score":round(score,4),"liveness":liveness,"authority_granted":False,"next_step":"complete the existing action-specific Admin approval"}

    def transcribe(self,audio:bytes,suffix:str=".wav")->str:
        if len(audio)>25*1024*1024:raise ValueError("audio exceeds 25 MiB")
        cfg=self.config().get("stt") or {};command=str(cfg.get("command") or "");model=str(cfg.get("model") or "")
        if not command or not model or not Path(model).is_file():raise RuntimeError("local STT command/model is not configured")
        suffix=suffix if suffix in {".wav",".mp3",".m4a",".ogg",".webm"} else ".wav"
        with tempfile.TemporaryDirectory(prefix="solomon-voice-") as d:
            inp=Path(d)/("input"+suffix);out=Path(d)/"transcript";inp.write_bytes(audio)
            p=subprocess.run([command,"-m",model,"-f",str(inp),"-otxt","-of",str(out)],capture_output=True,text=True,timeout=180,check=False)
            if p.returncode or not out.with_suffix(".txt").is_file():raise RuntimeError((p.stderr or "STT failed")[-500:])
            return out.with_suffix(".txt").read_text(errors="replace").strip()

    def synthesize(self,text:str)->bytes:
        text=(text or "").strip()
        if not text or len(text)>4000:raise ValueError("text must contain 1-4000 characters")
        cfg=self.config().get("tts") or {};command=str(cfg.get("command") or "");model=str(cfg.get("model") or "")
        if not command or not model or not Path(model).is_file():raise RuntimeError("local TTS command/model is not configured")
        with tempfile.TemporaryDirectory(prefix="solomon-voice-") as d:
            out=Path(d)/"speech.wav";p=subprocess.run([command,"--model",model,"--output_file",str(out)],input=text,capture_output=True,text=True,timeout=180,check=False)
            if p.returncode or not out.is_file():raise RuntimeError((p.stderr or "TTS failed")[-500:])
            return out.read_bytes()
