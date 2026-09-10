from pathlib import Path
import tempfile

from solomonprime.approvals import ApprovalStore
from solomonprime.hooks import classify_command
from solomonprime.memory import MemoryStore
from solomonprime.storage import StorageIndex
from solomonprime.scheduler import recommended_roles
from solomonprime.agents import AgentCatalog


def test_approval_hash_and_state():
    with tempfile.TemporaryDirectory() as d:
        a=ApprovalStore(f"{d}/a.db");r=a.request(actor="storage-steward",action="move",payload={"a":1},risk="mutating")
        assert r["state"]=="pending" and len(r["plan_hash"])==64
        assert a.approve(r["id"],by="operator")
        assert a.get(r["id"])["state"]=="approved"

def test_hooks_block_disk_damage():
    assert not classify_command("mkfs.ext4 /dev/sda1").allowed
    assert classify_command("lsblk -f").allowed

def test_memory_exact_and_near_dedupe():
    with tempfile.TemporaryDirectory() as d:
        m=MemoryStore(f"{d}/m.db")
        assert m.remember("controller host uses direct Ethernet before Tailscale",domain="infrastructure")["stored"]
        assert m.remember("controller host uses direct Ethernet before Tailscale",domain="infrastructure").get("deduplicated")
        assert m.search("Ethernet Tailscale",domain="infrastructure")

def test_storage_duplicate_hashing():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d);(p/"a.bin").write_bytes(b"x"*200000);(p/"b.bin").write_bytes(b"x"*200000);(p/"c.bin").write_bytes(b"y"*200000)
        s=StorageIndex(f"{d}/s.db");r=s.scan([d]);plan=s.duplicate_plan(r["scan_id"])
        assert len(plan["sets"])==1 and plan["sets"][0]["copies"]==2 and not plan["destructive_actions_available"]

def test_high_memory_roles():
    s={"ram":{"total_gb":256},"cpu":{"physical":24},"gpus":[]}
    roles=recommended_roles(s)
    assert "large-memory" in roles and "memory-store" in roles and "cpu-simulation" in roles

def test_agent_routing():
    root=Path(__file__).parents[1]/"agents";c=AgentCatalog(str(root),[p.name for p in root.iterdir() if p.is_dir()])
    assert c.route("scan the drives for duplicate files") == "storage-steward"
    assert c.route("run a Monte Carlo parameter sweep") == "research-simulation"
    assert c.route("review irrigation and soil records") == "farm-ops"
