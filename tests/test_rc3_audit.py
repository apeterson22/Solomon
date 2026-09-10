from __future__ import annotations

import hashlib
import json
import threading
import time

from solomonprime.audit import AuditLog


def _expected_hash(record: dict) -> str:
    base = {k: v for k, v in record.items() if k != "hash"}
    raw = json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def test_audit_chain_cache_and_restart_recovery(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(str(path))
    records = [log.emit("rc3.test", actor="pytest", data={"i": i}) for i in range(1000)]
    assert records[0]["prev_hash"] == "0" * 64
    for previous, current in zip(records, records[1:]):
        assert current["prev_hash"] == previous["hash"]
        assert previous["hash"] == _expected_hash(previous)
    assert records[-1]["hash"] == _expected_hash(records[-1])

    recovered = AuditLog(str(path))
    assert recovered._last_hash() == records[-1]["hash"]
    nxt = recovered.emit("rc3.after-restart")
    assert nxt["prev_hash"] == records[-1]["hash"]


def test_audit_recovery_skips_partial_final_line(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(str(path))
    good = log.emit("good")
    with path.open("ab") as f:
        f.write(b'{"ts":123,"event":"partial"')
    recovered = AuditLog(str(path))
    assert recovered._last_hash() == good["hash"]


def test_audit_emit_does_not_rescan_history(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(str(path))
    for i in range(5000):
        log.emit("seed", data={"i": i})

    # Steady-state emit must use the cached chain head.  If it calls the
    # startup recovery path again this test fails immediately.
    monkeypatch.setattr(log, "_load_last_hash", lambda: (_ for _ in ()).throw(AssertionError("rescan")))
    before = path.stat().st_size
    rec = log.emit("constant-time")
    assert path.stat().st_size > before
    assert rec["prev_hash"] != "0" * 64


def test_audit_threaded_chain_is_serialized(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(str(path))
    threads=[]
    def worker(offset):
        for i in range(200):
            log.emit("threaded", actor=str(offset), data={"i": i})
    for n in range(4):
        t=threading.Thread(target=worker,args=(n,));t.start();threads.append(t)
    for t in threads:t.join(timeout=10)
    assert all(not t.is_alive() for t in threads)
    lines=[json.loads(x) for x in path.read_text().splitlines()]
    assert len(lines)==800
    prev="0"*64
    for rec in lines:
        assert rec["prev_hash"]==prev
        assert rec["hash"]==_expected_hash(rec)
        prev=rec["hash"]
