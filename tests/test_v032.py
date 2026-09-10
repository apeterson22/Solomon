import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from solomonprime.jobs import JobSubmitRequest
from solomonprime.memory import MemoryStore
from solomonprime.scheduler import Workload, score_node


def load_broker():
    path = Path("scripts/solomon-job-broker.py")
    spec = importlib.util.spec_from_file_location("solomon_job_broker", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def load_runner():
    path = Path("scripts/solomon-job-runner.py")
    spec = importlib.util.spec_from_file_location("solomon_job_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def make_job(tmp_path: Path, *, risk: str = "reversible"):
    root = tmp_path / "jobs"
    workspace = root / "JOB-TEST-001"
    workspace.mkdir(parents=True, mode=0o770)
    source = workspace / "main.py"
    source.write_text("print('ok')\n")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = workspace / "manifest.json"
    manifest.write_text(json.dumps({
        "job_id": workspace.name,
        "workspace": str(workspace),
        "kind": "python",
        "risk": risk,
        "source_file": source.name,
        "source_sha256": source_digest,
        "resources": {
            "max_runtime_seconds": 30,
            "max_memory_gb": 1,
            "max_cpu_cores": 1,
            "max_disk_gb": 1,
        },
        "allow_network": False,
    }))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return root, workspace, manifest, source, digest


def test_broker_accepts_owned_bounded_manifest(tmp_path):
    broker = load_broker()
    root, _workspace, manifest, _source, digest = make_job(tmp_path)
    broker.ROOT = root.resolve()
    path, runtime, source = broker.validate_request(
        {"manifest_path": str(manifest), "manifest_sha256": digest}, os.getuid()
    )
    assert path == manifest
    assert runtime == 30
    assert source.name == "main.py"


def test_broker_rejects_hash_mismatch(tmp_path):
    broker = load_broker()
    root, _workspace, manifest, _source, _digest = make_job(tmp_path)
    broker.ROOT = root.resolve()
    with pytest.raises(broker.BrokerReject, match="hash mismatch"):
        broker.validate_request(
            {"manifest_path": str(manifest), "manifest_sha256": "0" * 64}, os.getuid()
        )


def test_broker_rejects_approval_risk(tmp_path):
    broker = load_broker()
    root, _workspace, manifest, _source, digest = make_job(tmp_path, risk="destructive")
    broker.ROOT = root.resolve()
    with pytest.raises(broker.BrokerReject, match="requires approval"):
        broker.validate_request(
            {"manifest_path": str(manifest), "manifest_sha256": digest}, os.getuid()
        )


def test_broker_rejects_symlink_source(tmp_path):
    broker = load_broker()
    root, _workspace, manifest, source, _digest = make_job(tmp_path)
    target = source.with_suffix(".real")
    source.rename(target)
    source.symlink_to(target)
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    broker.ROOT = root.resolve()
    with pytest.raises(broker.BrokerReject, match="non-symlink"):
        broker.validate_request(
            {"manifest_path": str(manifest), "manifest_sha256": digest}, os.getuid()
        )


def test_broker_seals_verified_inodes_against_open_fd_race(tmp_path, monkeypatch):
    broker = load_broker()
    root, workspace, manifest, source, digest = make_job(tmp_path)
    broker.ROOT = root.resolve()
    monkeypatch.setenv("SOLOMON_JOB_GROUP_GID", str(os.getgid()))
    old_descriptor = os.open(source, os.O_WRONLY)
    manifest_path, _runtime, source_path = broker.validate_request(
        {"manifest_path": str(manifest), "manifest_sha256": digest}, os.getuid()
    )
    broker._freeze_workspace(manifest_path, source_path)
    broker._seal_verified_files(manifest_path, source_path, digest)
    os.write(old_descriptor, b"malicious replacement")
    os.close(old_descriptor)
    assert source.read_text() == "print('ok')\n"
    broker._thaw_workspace(workspace, os.getuid())


def test_job_request_is_typed_and_forbids_unknown_fields():
    request = JobSubmitRequest(kind="python", source="print('ok')")
    assert request.resources.max_memory_gb == 4
    with pytest.raises(Exception):
        JobSubmitRequest(kind="python", source="print('ok')", arbitrary_shell="id")


def test_job_request_produces_discoverable_schema():
    schema = JobSubmitRequest.model_json_schema()
    assert schema["properties"]["resources"]["$ref"].endswith("JobResources")
    assert schema["additionalProperties"] is False


def test_legacy_memory_store_remains_truthful_while_v040_knowledge_adds_hybrid(tmp_path):
    store = MemoryStore(str(tmp_path / "memory.db"))
    store.remember("operator standard with provenance", source="operator-plan")
    stats = store.stats()
    assert stats["retrieval"]["lexical"] is True
    assert stats["retrieval"]["vector_embeddings"] is False
    assert stats["retrieval"]["hybrid_reranking"] is False
    assert stats["quality_controls"]["automatic_contradiction_resolution"] is False
    assert stats["quality_controls"]["automatic_knowledge_compilation"] is False


def test_improvement_plan_and_obsidian_readiness_are_packaged():
    plan = Path("docs/SOLOMONPRIME_TED_IMPROVEMENT_PLAN.md")
    readiness = Path("docs/IMPROVEMENT_MEMORY_OBSIDIAN_READINESS.md").read_text()
    seed = Path("scripts/seed-improvement-plan.sh").read_text()
    assert plan.is_file() and plan.stat().st_size > 10000
    assert "Obsidian vault contract" in readiness
    assert "SolomonPrime + TED Continuous Improvement System" in seed


def test_api_exposes_typed_jobs_and_truthful_improvement_status(tmp_path):
    config = tmp_path / "config.yaml"
    plan = Path("docs/SOLOMONPRIME_TED_IMPROVEMENT_PLAN.md").resolve()
    config.write_text(json.dumps({
        "role": "controller",
        "node_name": "test-controller",
        "state_dir": str(tmp_path / "state"),
        "config_dir": str(tmp_path / "config"),
        "cluster_key_file": str(tmp_path / "config" / "cluster.key"),
        "public_api_key_file": str(tmp_path / "config" / "api.key"),
        "goals_db": str(tmp_path / "state" / "goals.db"),
        "experiments_db": str(tmp_path / "state" / "experiments.db"),
        "experiment_artifact_dir": str(tmp_path / "state" / "experiments"),
        "jobs_db": str(tmp_path / "state" / "jobs.db"),
        "job_workspace_dir": str(tmp_path / "jobs"),
        "improvement_plan_path": str(plan),
        "obsidian_vault_path": str(tmp_path / "obsidian"),
        "mdns": False,
        "tailscale_discovery": False,
    }))
    code = """
from solomonprime import api
schema=api.app.openapi()
assert schema['components']['schemas']['JobSubmitRequest']
assert schema['components']['schemas']['JobResources']
status=api.improvement_status(None)
assert status['plan']['present'] is True
assert status['rag']['state']=='active'
assert status['rag']['hybrid_retrieval'] is True
assert status['rag']['neural_semantic_embeddings'] is False
assert status['obsidian']['state']=='implemented_disabled'
assert status['dashboard']['status_api'] is True
class DeniedPath:
    def is_dir(self):
        raise PermissionError(13, 'permission denied')
assert api._safe_is_dir(DeniedPath()) == (False, False)
"""
    env = {**os.environ, "SOLOMON_CONFIG": str(config), "PYTHONPATH": str(Path.cwd())}
    proc = subprocess.run([sys.executable, "-c", code], env=env, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr


def test_scheduler_enforces_locality_and_cpu_saturation():
    node = {
        "node_id": "node-a",
        "trust": "trusted",
        "health": "online",
        "snapshot": {
            "ram": {"available_gb": 8, "total_gb": 16},
            "cpu": {"util_pct": 99},
            "gpus": [],
        },
        "endpoints": [],
    }
    score, reasons, _ = score_node(node, Workload(kind="job", locality_node_id="node-b"))
    assert score < -1e8 and reasons == ["locality_mismatch"]
    score, reasons, _ = score_node(node, Workload(kind="job", locality_node_id="node-a", max_cpu_util_pct=90))
    assert score < -1e8 and reasons == ["cpu_saturated"]


def test_daemon_uses_broker_client_not_sudo():
    source = Path("solomonprime/jobs.py").read_text()
    assert "[\"sudo\",\"-n\"" not in source
    assert "self.launcher" in source
    unit = Path("systemd/solomon-job-broker@.service").read_text()
    assert "PrivateNetwork=yes" in unit
    assert "NoNewPrivileges=yes" in unit
    assert "ReadWritePaths=/apps/solomonprime-jobs" in unit
    assert "root solomonprime" in Path("systemd/solomon-job-broker.tmpfiles").read_text()


def test_workspace_accounting_ignores_symlinks(tmp_path):
    runner = load_runner()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "artifact.bin").write_bytes(b"12345")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x" * 1000)
    (workspace / "escape").symlink_to(outside)
    assert runner.workspace_bytes(workspace) == 5


def test_broker_protocol_invokes_only_validated_runner(tmp_path):
    root, _workspace, manifest, _source, digest = make_job(tmp_path)
    fake_runner = tmp_path / "runner"
    fake_runner.write_text("#!/bin/sh\nprintf 'runner-ok\\n'\n")
    fake_runner.chmod(0o755)
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    env = {
        **os.environ,
            "SOLOMON_JOB_CLIENT_UID": str(os.getuid()),
            "SOLOMON_JOB_GROUP_GID": str(os.getgid()),
        "SOLOMON_JOB_ROOT": str(root),
        "SOLOMON_JOB_RUNNER": str(fake_runner),
    }
    proc = subprocess.Popen(
        [sys.executable, "scripts/solomon-job-broker.py"],
        stdin=child,
        stdout=child,
        stderr=subprocess.PIPE,
        env=env,
        text=False,
    )
    child.close()
    parent.sendall((json.dumps({
        "manifest_path": str(manifest),
        "manifest_sha256": digest,
    }) + "\n").encode())
    parent.shutdown(socket.SHUT_WR)
    response = b""
    while True:
        block = parent.recv(65536)
        if not block:
            break
        response += block
    parent.close()
    assert proc.wait(timeout=5) == 0
    decoded = json.loads(response)
    assert decoded["ok"] is True, (decoded, proc.stderr.read().decode())
    assert decoded["exit_code"] == 0
    assert decoded["stdout"] == "runner-ok\n"
