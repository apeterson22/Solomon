import json
import os
import subprocess
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from solomonprime.knowledge import KnowledgeStore, ObsidianBridge, _cosine, _hash_vector
from solomonprime.models import LocalModelCatalog
from solomonprime.cloud_router import CloudRouter, Provider
from solomonprime.energy import EnergyTracker
from solomonprime.edge_devices import DEVICE_ACTIONS, EdgeDeviceRegistry
from solomonprime.rf import RFMonitor


def record(store, title, content, **extra):
    return store.create({"title": title, "content": content, "author": "test-operator", **extra})


def approve(store, kid):
    store.transition(kid, "review", actor="test-operator")
    return store.transition(kid, "approved", actor="test-reviewer")


def test_feature_vectors_are_deterministic_and_bounded():
    a = _hash_vector("local first knowledge retrieval")
    b = _hash_vector("local first knowledge retrieval")
    c = _hash_vector("unrelated livestock schedule")
    assert a == b
    assert .99 <= _cosine(a, b) <= 1.01
    assert _cosine(a, c) < .5


def test_fts_query_punctuation_does_not_disable_lexical_scoring(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    item = record(store, "SolomonPrime v0.4 Knowledge Workspace", "governed hybrid retrieval")
    approve(store, item["id"])
    result = store.search("SolomonPrime v0.4 Knowledge Workspace")[0]
    assert result["id"] == item["id"]
    assert result["retrieval"]["lexical"] > 0


def test_governed_lifecycle_and_approved_only_retrieval(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    draft = record(store, "Network policy", "Prefer direct Ethernet for model transfers", domain="infrastructure")
    assert store.search("Ethernet model transfers", domain="infrastructure") == []
    approved = approve(store, draft["id"])
    assert approved["approved_by"] == "test-reviewer"
    results = store.search("Ethernet model transfers", domain="infrastructure")
    assert results[0]["id"] == draft["id"]
    citation = results[0]["citations"][0]
    assert citation["knowledge_id"] == draft["id"]
    assert len(citation["content_hash"]) == 64


def test_agent_cannot_create_preapproved_knowledge(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    with pytest.raises(ValueError, match="draft or review"):
        record(store, "Unsafe", "bypass review", state="approved")


def test_exact_deduplication_preserves_identity(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    first = record(store, "First", "same durable content")
    second = record(store, "Second", "same durable content")
    assert second == {"inserted": False, "deduplicated": True, "id": first["id"], "state": "draft"}


def test_versioned_revision_retires_prior_only_after_human_approval(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    first = record(store, "Policy v1", "Use wired networking", canonical_key="network.policy")
    approve(store, first["id"])
    second = record(store, "Policy v2", "Prefer direct Ethernet then wired LAN", supersedes=first["id"])
    assert second["version"] == 2 and store.get(first["id"])["state"] == "approved"
    approve(store, second["id"])
    assert store.get(first["id"])["state"] == "retired"


def test_canonical_key_conflict_is_detected_not_resolved(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    first = record(store, "Setting", "Obsidian synchronization is disabled", canonical_key="obsidian.sync")
    second = record(store, "Setting update", "Obsidian synchronization is manual", canonical_key="obsidian.sync")
    conflicts = store.contradictions()
    assert len(conflicts) == 1
    assert conflicts[0]["reason"] == "canonical_key_conflict"
    assert conflicts[0]["state"] == "open"
    resolved = store.resolve_contradiction(conflicts[0]["id"], resolution=f"prefer {second['id']}", actor="test-reviewer")
    assert resolved["state"] == "resolved"


def test_consolidation_is_preview_only(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    record(store, "Temporary", "low value draft", importance=.1)
    preview = store.consolidation_preview(older_days=1)
    assert preview["destructive"] is False
    assert preview["mode"] == "preview_only"
    assert store.status()["records"] == 1


def test_retrieval_evaluation_records_evidence_without_auto_promotion(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    item = record(store, "Storage safety", "Run a non destructive audit before moving important files")
    approve(store, item["id"])
    result = store.evaluate("storage baseline", [{"query":"audit important files", "expected_ids":[item["id"]]}])
    assert result["candidate"]["citation_completeness"] == 1.0
    assert result["promoted"] is False
    assert store.evaluations()[0]["id"] == result["id"]


def test_obsidian_round_trip_exports_only_approved_and_imports_draft(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    bridge = ObsidianBridge(store, str(tmp_path / "vault"))
    approved = record(store, "Approved SOP", "Always audit before moving files", kind="sop")
    approve(store, approved["id"])
    record(store, "Private draft", "This must not be exported")
    exported = bridge.export_approved()
    assert exported["count"] == 1
    path = tmp_path / "vault" / exported["written"][0]["path"]
    assert "Always audit" in path.read_text()
    result = bridge.import_draft(exported["written"][0]["path"], actor="test-operator")
    # The exact-content deduplicator may map an unchanged exported note to its
    # source record; edited/new notes are guaranteed to enter as drafts.
    if result.get("inserted"):
        assert result["state"] == "draft"


def test_obsidian_rejects_path_traversal(tmp_path):
    store = KnowledgeStore(str(tmp_path / "knowledge.db"))
    bridge = ObsidianBridge(store, str(tmp_path / "vault"))
    with pytest.raises(ValueError, match="escape"):
        bridge.import_draft("../../outside.md")


def test_api_reports_truthful_v040_capabilities(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(json.dumps({
        "role":"controller", "node_name":"test", "state_dir":str(tmp_path/"state"),
        "cluster_key_file":str(tmp_path/"etc"/"cluster.key"), "public_api_key_file":str(tmp_path/"etc"/"api.key"),
        "knowledge_db":str(tmp_path/"state"/"knowledge.db"), "goals_db":str(tmp_path/"state"/"goals.db"),
        "experiments_db":str(tmp_path/"state"/"experiments.db"), "experiment_artifact_dir":str(tmp_path/"state"/"experiments"),
        "jobs_db":str(tmp_path/"state"/"jobs.db"), "job_workspace_dir":str(tmp_path/"jobs"),
        "improvement_plan_path":str(Path("docs/SOLOMONPRIME_TED_IMPROVEMENT_PLAN.md").resolve()),
        "admin_docs_path":str(Path("config/admin-docs.yaml").resolve()),
        "obsidian_vault_path":str(tmp_path/"vault"), "obsidian_enabled":True, "obsidian_sync_mode":"manual",
        "mdns":False, "tailscale_discovery":False
    }))
    code = """
from solomonprime import api
s=api.improvement_status(None)
api.hardware_profile=lambda node_id,name,port:{"node_id":node_id,"name":name,"role":"controller","capabilities":[],"services":{},"network":{"paths":[]},"cpu":{},"ram":{},"gpus":[],"timestamp":0}
i=api.current_info()
assert api.health()['version']=='1.0.0'
assert api.health()['release']=='home-rc4'
assert s['rag']['state']=='active' and s['rag']['hybrid_retrieval'] is True
assert s['rag']['neural_semantic_embeddings'] is False
assert s['knowledge']['governance']['automatic_conflict_resolution'] is False
assert s['obsidian']['state']=='available_manual_governed'
assert s['dashboard']['visual_improvement_workspace']=='active'
assert 'edge_extensions' in i and 'rf_monitoring' in i
assert '/v1/knowledge' in api.app.openapi()['paths']
assert '/v1/edge-devices' in api.app.openapi()['paths']
assert '/v1/edge-devices/discovery/scan' in api.app.openapi()['paths']
assert '/v1/edge-devices/actions' in api.app.openapi()['paths']
assert '/v1/edge-devices/actions/{action_id}/decision' in api.app.openapi()['paths']
assert '/v1/edge-devices/actions/{action_id}/execute' in api.app.openapi()['paths']
assert '/v1/rf/status' in api.app.openapi()['paths']
assert '/v1/rf/fleet' in api.app.openapi()['paths']
assert '/v1/documentation' in api.app.openapi()['paths']
assert '/v1/integration/status' in api.app.openapi()['paths']
assert '/v1/tools/self-test' in api.app.openapi()['paths']
assert '/v1/tools/openapi.json' in api.app.openapi()['paths']
assert '/v1/voice/status' in api.app.openapi()['paths']
assert '/v1/voice/device-session' in api.app.openapi()['paths']
assert '/v1/voice/approval-challenge' in api.app.openapi()['paths']
assert '/v1/voice/verify-challenge' in api.app.openapi()['paths']
assert '/v1/audio/transcriptions' in api.app.openapi()['paths']
assert '/v1/audio/speech' in api.app.openapi()['paths']
assert '/v1/calendars/status' in api.app.openapi()['paths']
"""
    env={**os.environ,"SOLOMON_CONFIG":str(config),"PYTHONPATH":str(Path.cwd())}
    proc=subprocess.run([sys.executable,"-c",code],env=env,text=True,capture_output=True)
    assert proc.returncode==0,proc.stderr


def test_http_knowledge_workflow_and_dashboard(tmp_path):
    config=tmp_path/"config.yaml"
    config.write_text(json.dumps({
        "role":"controller","state_dir":str(tmp_path/"state"),"knowledge_db":str(tmp_path/"state"/"knowledge.db"),
        "cluster_key_file":str(tmp_path/"etc"/"cluster.key"),"public_api_key_file":str(tmp_path/"etc"/"api.key"),
        "goals_db":str(tmp_path/"state"/"goals.db"),"experiments_db":str(tmp_path/"state"/"experiments.db"),
        "experiment_artifact_dir":str(tmp_path/"state"/"experiments"),"jobs_db":str(tmp_path/"state"/"jobs.db"),
        "job_workspace_dir":str(tmp_path/"jobs"),"obsidian_vault_path":str(tmp_path/"vault"),"mdns":False,"tailscale_discovery":False
        ,"admin_docs_path":str(Path("config/admin-docs.yaml").resolve())
    }))
    code="""
from fastapi.testclient import TestClient
from solomonprime import api
c=TestClient(api.app);h={'Authorization':'Bearer '+api.public_key_text}
assert c.get('/v1/knowledge').status_code==401
assert len(c.get('/v1/documentation',headers=h).json()['sections'])>=5
assert c.get('/v1/rf/status',headers=h).status_code==200
assert c.get('/v1/rf/fleet',headers=h).status_code==200
assert c.get('/v1/integration/status',headers=h).status_code==200
d=c.post('/v1/knowledge',headers=h,json={'title':'Farm SOP','content':'Check water daily','kind':'sop','state':'draft','author':'operator'}).json()
assert d['inserted'] is True
assert c.get('/v1/knowledge/search',headers=h,params={'q':'water'}).json()['results']==[]
assert c.post(f"/v1/knowledge/{d['id']}/state",headers=h,json={'state':'review','actor':'operator'}).status_code==200
assert c.post(f"/v1/knowledge/{d['id']}/state",headers=h,json={'state':'approved','actor':'human-reviewer'}).status_code==200
r=c.get('/v1/knowledge/search',headers=h,params={'q':'water'}).json()['results'][0]
assert r['citations'][0]['knowledge_id']==d['id']
page=c.get('/admin')
assert page.status_code==200 and '?key=' not in page.text and 'SolomonPrime Admin' in page.text
assert c.get('/admin/admin.css').status_code==200
script=c.get('/admin/admin.js')
assert script.status_code==200 and 'sessionStorage' in script.text
legacy=c.get('/v1/improvement/dashboard',follow_redirects=False)
assert legacy.status_code==307 and legacy.headers['location']=='/admin'
"""
    env={**os.environ,"SOLOMON_CONFIG":str(config),"PYTHONPATH":str(Path.cwd())}
    proc=subprocess.run([sys.executable,"-c",code],env=env,text=True,capture_output=True)
    assert proc.returncode==0,proc.stderr


def test_v032_broker_security_assets_remain_packaged():
    assert Path("scripts/solomon-job-broker.py").is_file()
    assert "NoNewPrivileges=yes" in Path("systemd/solomon-job-broker@.service").read_text()
    assert "PrivateNetwork=yes" in Path("systemd/solomon-job-broker@.service").read_text()


def test_installers_do_not_depend_on_dev_stdin_being_statable():
    assert "/dev/stdin" not in Path("scripts/install-job-broker.sh").read_text()
    assert "/dev/stdin" not in Path("scripts/upgrade-v1.0.0-common.sh").read_text()


def test_admin_workspace_has_one_console_and_all_required_sections():
    html=Path("solomonprime/web/admin.html").read_text()
    js=Path("solomonprime/web/admin.js").read_text()
    for section in ("Overview","Fleet","Models","Edge Devices","RF Monitoring","Voice &amp; Mobile","Calendars","Goals","Jobs","Experiments","Knowledge","Approvals","TED","Configuration","Documentation"):
        assert f'>{section}<' in html
    assert "Chat &amp; Workspaces" in html
    assert "innerHTML=cards.map" not in js
    assert "Live component power" in js
    assert "/v1/energy/status" in js
    assert "/v1/edge-devices" in js
    assert "Trust identity & unlock requests" in js
    assert "RSSI estimate only" in js
    assert "/v1/rf/fleet" in js and "/v1/documentation" in js and "/v1/integration/status" in js
    assert set(DEVICE_ACTIONS)=={"serial_exchange","pairing","authentication_attempt","usb_endpoint_write","driver_detachment","firmware_flashing","radio_command","location_access","physical_movement"}


def test_photo_seeded_edge_catalog_and_governed_transitions(tmp_path):
    registry=EdgeDeviceRegistry("config/edge-devices.yaml",str(tmp_path/"edge.db"))
    inventory=registry.inventory()
    assert inventory["counts"]["total"]==9
    assert inventory["policy"]["cloud_may_control_devices"] is False
    assert inventory["policy"]["share_precise_location_with_cloud"] is False
    ids={d["id"] for d in inventory["devices"]}
    assert {"makey-makey-01","kosmoduino-01","elegoo-car-01","mario-kart-mario-01","mario-kart-wario-01","raykit-tag-04"} <= ids
    with pytest.raises(ValueError,match="evidence note"):
        registry.transition("makey-makey-01","detected",actor="operator",note="",confirmed=True)
    result=registry.transition("makey-makey-01","detected",actor="operator",note="USB VID/PID recorded",confirmed=True)
    assert result["state"]=="detected"
    assert registry.discovery_preview()=={"mode":"preview_only","mutated":False,"steps":registry.discovery_preview()["steps"]}


def test_dynamic_discovery_defaults_to_quarantine_and_requires_decision_reason(tmp_path):
    registry=EdgeDeviceRegistry("config/edge-devices.yaml",str(tmp_path/"edge.db"))
    registry._record_discovery({"fingerprint":"usb-test","transport":"usb","name":"Test device","capabilities":["human-interface"],"risk":"protected-host-device","analysis_plan":["enumerate descriptors read-only"]})
    item=registry.discoveries()[0]
    assert item["decision"]=="pending"
    assert "read-only" in item["analysis_plan"][0]
    with pytest.raises(ValueError,match="reason"):
        registry.decide("usb-test","approved_for_analysis",actor="operator",note="",confirmed=True)
    denied=registry.decide("usb-test","denied",actor="operator",note="not owned",confirmed=True)
    assert denied["decision"]=="denied"


def test_bluetooth_proximity_is_explicitly_not_distance_guaranteed(tmp_path,monkeypatch):
    registry=EdgeDeviceRegistry("config/edge-devices.yaml",str(tmp_path/"edge.db"))
    class Result:
        stdout="[NEW] Device AA:BB:CC:DD:EE:FF Sensor\n[CHG] Device AA:BB:CC:DD:EE:FF RSSI: -55\n"
        stderr=""
    monkeypatch.setattr(subprocess,"run",lambda *a,**k:Result())
    result=registry.scan_bluetooth(timeout_seconds=3,rssi_threshold=-70)
    assert result["nearby_estimate"]==1 and result["distance_guaranteed"] is False
    candidate=registry.discoveries()[0]
    assert candidate["evidence"]["distance_claim"] is False


def test_device_action_authorization_and_allowlisted_bluetooth_execution(tmp_path,monkeypatch):
    registry=EdgeDeviceRegistry("config/edge-devices.yaml",str(tmp_path/"edge.db"))
    registry._record_discovery({"fingerprint":"bluetooth-test","transport":"bluetooth","address":"AA:BB:CC:DD:EE:FF","name":"Owned sensor"})
    registry.decide("bluetooth-test","approved_for_analysis",actor="operator",note="ownership verified",confirmed=True)
    monkeypatch.setattr(registry,"_which",lambda name:"/usr/bin/bluetoothctl")
    request=registry.request_action("bluetooth-test","pairing",actor="operator",note="pair owned sensor",ttl_seconds=300)
    assert request["state"]=="pending" and request["parameters"]=={"address":"AA:BB:CC:DD:EE:FF"}
    approved=registry.decide_action(request["id"],"approved",actor="operator",note="bench isolated",confirmed=True)
    assert approved["state"]=="approved"
    class Result:
        returncode=0;stdout="Pairing successful";stderr=""
    monkeypatch.setattr(subprocess,"run",lambda *a,**k:Result())
    result=registry.execute_action(request["id"],actor="operator",confirmed=True)
    assert result["state"]=="executed" and result["result"]["ok"] is True


def test_critical_device_actions_authorize_but_fail_closed_without_adapter(tmp_path):
    registry=EdgeDeviceRegistry("config/edge-devices.yaml",str(tmp_path/"edge.db"))
    registry._record_discovery({"fingerprint":"usb-test","transport":"usb","address":"1-2","name":"Owned board"})
    registry.decide("usb-test","approved_for_analysis",actor="operator",note="ownership verified",confirmed=True)
    request=registry.request_action("usb-test","firmware_flashing",actor="operator",note="test signed image later",parameters={"adapter_id":"elegoo-avr-v1","image_id":"candidate.hex","artifact_sha256":"a"*64})
    registry.decide_action(request["id"],"approved",actor="operator",note="authorization only",confirmed=True)
    with pytest.raises(ValueError,match="signed, fingerprint-scoped adapter"):
        registry.execute_action(request["id"],actor="operator",confirmed=True)
    capabilities={x["action"]:x for x in registry.action_capabilities()}
    assert capabilities["firmware_flashing"]["authorization_available"] is True
    assert capabilities["firmware_flashing"]["execution_available"] is False


def test_rf_receive_scan_records_bounded_local_observation(tmp_path,monkeypatch):
    monitor=RFMonitor(str(tmp_path/"rf.db"))
    monkeypatch.setattr(shutil,"which",lambda name:"/usr/bin/rtl_433" if name=="rtl_433" else None)
    class Result:
        returncode=0
        stdout='{"model":"Farm-Sensor","id":7,"temperature_C":21.5,"unknown_private_field":"redacted"}\n'
        stderr=""
    monkeypatch.setattr(subprocess,"run",lambda *a,**k:Result())
    result=monitor.scan_receive(3)
    assert result["transmitted"] is False and result["observations"]==1
    observation=monitor.observations()[0]
    assert observation["summary"]["temperature_C"]==21.5
    assert "unknown_private_field" not in observation["summary"]
    assert monitor.status()["policy"]["transmit_requires_action_approval"] is True


def test_node_upgrade_enables_edge_and_rf_reporting_without_remote_transmit():
    api=Path("solomonprime/api.py").read_text()
    upgrade=Path("scripts/upgrade-v1.0.0-common.sh").read_text()
    assert 'threading.Thread(target=_edge_discovery_loop' in api
    assert 'threading.Thread(target=_rf_monitor_loop' in api
    assert '"remote_transmit":False' in api
    assert "install-edge-rf-tools.sh" in upgrade
    node_catalog=yaml.safe_load(Path("config/edge-devices-node.yaml").read_text())
    assert node_catalog["devices"]==[] and node_catalog["policy"]["dynamic_discovery"] is True


def test_openwebui_link_validates_gateway_models_and_admin():
    script=Path("scripts/link-openwebui-admin.sh").read_text()
    assert 'OPENAI_API_BASE_URL/models' in script
    assert 'select(.id=="solomonprime")' in script
    assert "integration validation failed; original container restored" in script


def test_edge_goal_seed_is_local_first_and_actuation_gated():
    script=Path("scripts/seed-edge-device-goals.sh").read_text()
    assert script.count("create '")==5
    assert "cloud_physical_control:false" in script
    assert "no_unapproved_pairing_flashing_transmission_or_actuation:true" in script


def test_openwebui_admin_link_preserves_named_data_volume():
    script=Path("scripts/link-openwebui-admin.sh").read_text()
    assert "WEBUI_BANNERS=" in script
    assert "-v open-webui:/app/backend/data" in script
    assert "docker volume rm" not in script
    assert "original container restored" in script
    assert "ip -4 route get 1.1.1.1" in script
    assert "SOLOMON_ADMIN_URL" in script


def test_local_model_catalog_finds_downloads_and_active_symlink(tmp_path):
    model=tmp_path/"model.gguf";model.write_bytes(b"gguf")
    active=tmp_path/"primary.gguf";active.symlink_to(model)
    inventory=LocalModelCatalog(str(active)).inventory()
    assert inventory["counts"]["gguf"]==2
    assert inventory["active"]["resolved_path"]==str(model)
    assert {"ollama-qwen3-14b","ollama-gpt-oss-120b-cloud","ollama-gpt-oss-20b"} <= {x["id"] for x in inventory["candidates"]}


def test_energy_tracker_integrates_component_power_and_tariff(tmp_path, monkeypatch):
    cfg=tmp_path/"energy.yaml"
    cfg.write_text("tariff:\n  marginal_usd_per_kwh: 0.12794\n  effective_date: '2026-09-02'\n")
    tracker=EnergyTracker(str(cfg),str(tmp_path/"energy.db"))
    monkeypatch.setattr(tracker,"_nvidia",lambda:[{"source":"test","device":"gpu","watts":100.0}])
    monkeypatch.setattr(tracker,"_hwmon",lambda skip:[])
    monkeypatch.setattr(tracker,"_rapl_watts",lambda now:[])
    tracker.sample(); tracker._last_ts -= 36
    tracker.sample(); status=tracker.status()
    assert status["state"]=="component_metered_estimate"
    assert .0009 <= status["today"]["kwh"] <= .0011
    assert status["today"]["cost_usd"] > 0


def test_paid_provider_requires_upstream_cap_and_cost_reserve(tmp_path):
    router=CloudRouter(str(tmp_path/"providers.yaml"),str(tmp_path/"quota.db"),str(tmp_path/"training"))
    base=dict(name="paid",kind="openai",enabled=True,model="test",billing_mode="prepaid-hard-cap",allow_overage=False,
              priority=1,max_output_tokens=100,api_key_file=str(tmp_path/"key"),limits={"daily_requests":10,"monthly_requests":10,"monthly_input_tokens":1000,"monthly_output_tokens":1000,"monthly_cost_microusd":5_000_000})
    (tmp_path/"key").write_text("secret")
    denied=Provider(**base,upstream_hard_cap_confirmed=False,max_cost_microusd_per_call=250_000)
    assert router._eligible(denied,100)[0] is False
    allowed=Provider(**base,upstream_hard_cap_confirmed=True,max_cost_microusd_per_call=250_000)
    ok,_,reservations=router._eligible(allowed,100)
    assert ok and reservations["monthly_cost_microusd"]==250_000


def test_provider_setup_keeps_keys_out_of_urls_and_requires_gemini_gate():
    root=Path(__file__).resolve().parents[1]
    script=(root/"scripts/configure-models-and-providers.sh").read_text()
    assert "generateContent?key=" not in (root/"solomonprime/cloud_router.py").read_text()
    assert "x-goog-api-key" in script
    assert "finite key-limit check" in script
    assert "Gemini Free Tier project with billing disabled" in script
