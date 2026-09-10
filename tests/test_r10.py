import json
import subprocess
from pathlib import Path

import yaml

from solomonprime.calendars import CalendarPull
from solomonprime.cloud_router import CloudRouter,Provider
from solomonprime.models import LocalModelCatalog
from solomonprime.voice import VoiceSecurity


def test_ollama_inventory_uses_http_and_classifies_both_cloud_suffixes(tmp_path,monkeypatch):
    class Response:
        def raise_for_status(self):pass
        def json(self):return {"models":[{"name":"qwen3:14b","digest":"a","size":100},{"name":"gpt-oss:120b-cloud","digest":"b","size":0},{"name":"other:cloud","digest":"c","size":0}]}
    monkeypatch.setattr("solomonprime.models.httpx.get",lambda *a,**k:Response())
    catalog=LocalModelCatalog(str(tmp_path/"primary.gguf"),"http://ollama.test:11434")
    inv=catalog.inventory()
    assert inv["ollama_runtime"]=={"state":"ready","endpoint":"http://ollama.test:11434","models":3,"local":1,"cloud":2,"reason":"HTTP inventory succeeded."}
    assert [x["location"] for x in inv["ollama"]]==["local","cloud","cloud"]


def test_ollama_cloud_free_is_eligible_only_with_overage_disabled(tmp_path):
    router=CloudRouter(str(tmp_path/"p.yaml"),str(tmp_path/"q.db"),str(tmp_path/"training"))
    base=dict(name="oc",kind="ollama_cloud",enabled=True,model="gpt-oss:120b-cloud",billing_mode="free",allow_overage=False,priority=1,max_output_tokens=10,limits={"daily_requests":10,"monthly_requests":10,"monthly_input_tokens":1000,"monthly_output_tokens":1000})
    assert router._eligible(Provider(**base,account_overage_disabled=False),10)[0] is False
    assert router._eligible(Provider(**base,account_overage_disabled=True),10)[0] is True


def test_calendar_ledgers_keep_google_and_m365_sources_separate(tmp_path):
    config=tmp_path/"cal.yaml";config.write_text("enabled: false\nproviders: {}\n")
    pull=CalendarPull(str(config),str(tmp_path/"cal.db"))
    pull._write("google",[{"id":"g1","summary":"Home","start":{"dateTime":"2026-09-06T10:00:00Z"},"end":{"dateTime":"2026-09-06T11:00:00Z"}}])
    pull._write("m365",[{"id":"m1","subject":"Work","start":{"dateTime":"2026-09-06T12:00:00Z"},"end":{"dateTime":"2026-09-06T13:00:00Z"}}])
    assert {x["source"] for x in pull.events()}=={"google","m365"}
    assert pull.status()["cloud_advisors_may_receive_events"] is False


def test_voice_challenge_is_action_and_device_bound(tmp_path):
    config=tmp_path/"voice.yaml";config.write_text("approval:\n  challenge_ttl_seconds: 60\n")
    gate=VoiceSecurity(str(config),str(tmp_path/"voice.db"),"test-secret");session=gate.issue_session("operator","flip5")
    result=gate.challenge("ACT-1",session["device_session"])
    assert result["action_id"]=="ACT-1" and len(result["phrase"].split())==4
    assert result["device_id"]=="flip5"
    assert "existing action approval" in result["factors_required"]
    assert gate.status()["enabled"] is False


def test_voice_verification_consumes_bound_challenge_without_granting_authority(tmp_path,monkeypatch):
    enrollment=tmp_path/"speaker.bin";enrollment.write_bytes(b"template")
    config=tmp_path/"voice.yaml";config.write_text(f"speaker_verification: {{command: /bin/echo, enrolled_template: {enrollment}, threshold: 0.82, liveness_required: true}}\n")
    gate=VoiceSecurity(str(config),str(tmp_path/"voice.db"),"test-secret");session=gate.issue_session("operator","flip5")
    challenge=gate.challenge("ACT-2",session["device_session"])
    class Result:returncode=0;stderr="";stdout='{"match":true,"score":0.91,"liveness":true}'
    monkeypatch.setattr("solomonprime.voice.subprocess.run",lambda argv,**kwargs:Result())
    result=gate.verify_challenge(challenge["challenge_id"],"ACT-2",session["device_session"],challenge["phrase"],b"audio")
    assert result["verified"] is True and result["authority_granted"] is False
    import pytest
    with pytest.raises(ValueError,match="used"):
        gate.verify_challenge(challenge["challenge_id"],"ACT-2",session["device_session"],challenge["phrase"],b"audio")


def test_local_voice_adapters_are_bounded_and_shell_free(tmp_path,monkeypatch):
    model=tmp_path/"model.bin";model.write_bytes(b"model")
    cfg=tmp_path/"voice.yaml";cfg.write_text(f"stt: {{command: /bin/echo, model: {model}}}\ntts: {{command: /bin/echo, model: {model}}}\n")
    class Result:returncode=0;stderr="";stdout=""
    def run(argv,**kwargs):
        if "-of" in argv:Path(argv[argv.index("-of")+1]+".txt").write_text("hello")
        if "--output_file" in argv:Path(argv[argv.index("--output_file")+1]).write_bytes(b"RIFF-test")
        assert kwargs.get("shell") is not True
        return Result()
    monkeypatch.setattr("solomonprime.voice.subprocess.run",run)
    gate=VoiceSecurity(str(cfg),str(tmp_path/"voice.db"))
    assert gate.transcribe(b"audio")=="hello"
    assert gate.synthesize("Hello") == b"RIFF-test"


def test_license_gate_and_admin_r10_surface():
    root=Path(__file__).resolve().parents[1]
    ok=subprocess.run(["python3",str(root/"scripts/license-gate.py"),"ollama-gpt-oss-20b"],capture_output=True,text=True)
    denied=subprocess.run(["python3",str(root/"scripts/license-gate.py"),"unknown-model"],capture_output=True,text=True)
    assert ok.returncode==0 and "Apache-2.0" in ok.stdout
    assert denied.returncode==3
    html=(root/"solomonprime/web/admin.html").read_text();js=(root/"solomonprime/web/admin.js").read_text()
    assert "Voice &amp; Mobile" in html and ">Calendars<" in html
    assert "/v1/tools/self-test" in js and "/v1/calendars/sync" in js and "ollama_runtime" in js


def test_package_declares_only_read_calendar_scopes():
    cfg=yaml.safe_load(Path("config/calendars.yaml").read_text())
    assert cfg["providers"]["google"]["scope"].endswith("calendar.readonly")
    assert cfg["providers"]["m365"]["scopes"]==["Calendars.Read"]
    assert cfg["cloud_advisors_may_receive_events"] is False


def test_openwebui_update_keeps_rollback_until_validation():
    configure=Path("scripts/configure-openwebui.sh").read_text()
    link=Path("scripts/link-openwebui-admin.sh").read_text()
    assert "docker rm -f open-webui" not in configure
    assert 'SOLOMON_OPENWEBUI_IMAGE_OVERRIDE="$IMAGE"' in configure
    assert 'docker rename open-webui "$OLD"' in link
    assert 'docker rename "$OLD" open-webui' in link
    assert '-v open-webui:/app/backend/data' in link
    assert 'docker rm "$OLD"' in link


def test_voice_challenge_requires_secure_transport_in_api_source():
    source=Path("solomonprime/api.py").read_text()
    assert "Voice approval challenges require HTTPS" in source
    assert "request.url.scheme==\"https\"" in source
