from __future__ import annotations
import json,sqlite3,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any
import httpx,yaml

class CalendarPull:
    """Two isolated, read-only calendar pulls with one normalized local ledger."""
    def __init__(self,config_path:str,db_path:str):
        self.config_path=Path(config_path);self.db_path=Path(db_path);self.db_path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.db_path) as c:c.execute("CREATE TABLE IF NOT EXISTS events(source TEXT,event_id TEXT,start TEXT,end TEXT,subject TEXT,location TEXT,organizer TEXT,online_url TEXT,updated REAL,PRIMARY KEY(source,event_id))")
    def config(self):
        try:return yaml.safe_load(self.config_path.read_text()) or {}
        except OSError:return {}
    def status(self):
        cfg=self.config();providers={}
        for name,p in (cfg.get("providers") or {}).items():
            token=Path(str(p.get("token_file") or p.get("token_cache_file") or ""))
            providers[name]={"enabled":bool(p.get("enabled")),"authorized":token.is_file(),"scope":p.get("scope") or p.get("scopes"),"token_store":str(token),"read_only":True}
        return {"enabled":bool(cfg.get("enabled")),"providers":providers,"cloud_advisors_may_receive_events":False,"separate_token_stores":True,"events":len(self.events(1000))}
    @staticmethod
    def _iso(value:Any)->str:
        if isinstance(value,dict):return str(value.get("dateTime") or value.get("date") or "")
        return str(value or "")
    def _write(self,source:str,items:list[dict[str,Any]]):
        now=time.time()
        with sqlite3.connect(self.db_path) as c:
            for x in items:
                if source=="google":
                    row=(source,str(x.get("id")),self._iso(x.get("start")),self._iso(x.get("end")),str(x.get("summary") or "(busy)"),str(x.get("location") or ""),str((x.get("organizer") or {}).get("email") or ""),str(x.get("hangoutLink") or ""),now)
                else:
                    row=(source,str(x.get("id")),self._iso(x.get("start")),self._iso(x.get("end")),str(x.get("subject") or "(busy)"),str((x.get("location") or {}).get("displayName") or ""),str(((x.get("organizer") or {}).get("emailAddress") or {}).get("address") or ""),str(x.get("onlineMeetingUrl") or ""),now)
                c.execute("INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?,?,?,?)",row)
        return len(items)
    def sync_google(self,p:dict[str,Any],start:str,end:str)->int:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GoogleRequest
        token=Path(p["token_file"]);creds=Credentials.from_authorized_user_file(str(token),[p["scope"]])
        if creds.expired and creds.refresh_token:creds.refresh(GoogleRequest());token.write_text(creds.to_json());token.chmod(0o600)
        headers={"Authorization":f"Bearer {creds.token}"};params={"timeMin":start,"timeMax":end,"singleEvents":"true","orderBy":"startTime","maxResults":2500}
        with httpx.Client(timeout=30) as c:r=c.get("https://www.googleapis.com/calendar/v3/calendars/primary/events",headers=headers,params=params)
        r.raise_for_status();return self._write("google",r.json().get("items") or [])
    def sync_m365(self,p:dict[str,Any],start:str,end:str)->int:
        import msal
        cache=msal.SerializableTokenCache();path=Path(p["token_cache_file"]);cache.deserialize(path.read_text())
        app=msal.PublicClientApplication(p["client_id"],authority=f"https://login.microsoftonline.com/{p.get('tenant','organizations')}",token_cache=cache)
        accounts=app.get_accounts();result=app.acquire_token_silent(p["scopes"],account=accounts[0] if accounts else None)
        if not result or "access_token" not in result:raise RuntimeError("M365 token unavailable; re-run calendar authorization")
        if cache.has_state_changed:path.write_text(cache.serialize());path.chmod(0o600)
        headers={"Authorization":f"Bearer {result['access_token']}","Prefer":'outlook.timezone="UTC"'};params={"startDateTime":start,"endDateTime":end,"$top":1000,"$select":"id,subject,start,end,location,organizer,onlineMeetingUrl"}
        with httpx.Client(timeout=30) as c:r=c.get("https://graph.microsoft.com/v1.0/me/calendarView",headers=headers,params=params)
        r.raise_for_status();return self._write("m365",r.json().get("value") or [])
    def sync(self):
        cfg=self.config();now=datetime.now(timezone.utc);start=(now-timedelta(hours=int(cfg.get("lookback_hours",12)))).isoformat();end=(now+timedelta(days=int(cfg.get("lookahead_days",14)))).isoformat();result={}
        for name,p in (cfg.get("providers") or {}).items():
            if not p.get("enabled"):result[name]={"state":"disabled"};continue
            try:n=self.sync_google(p,start,end) if name=="google" else self.sync_m365(p,start,end);result[name]={"state":"ok","events":n}
            except Exception as exc:result[name]={"state":"failed","error":f"{type(exc).__name__}: {str(exc)[:240]}"}
        return {"sources":result,"read_only":True}
    def events(self,limit:int=200):
        with sqlite3.connect(self.db_path) as c:c.row_factory=sqlite3.Row;rows=c.execute("SELECT * FROM events ORDER BY start LIMIT ?",(min(max(limit,1),1000),)).fetchall()
        return [dict(x) for x in rows]
