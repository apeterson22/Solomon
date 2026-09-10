import importlib.util
import subprocess
from pathlib import Path

import yaml

from solomonprime.approvals import ApprovalStore
from solomonprime.selfdev import DevelopmentLab
from solomonprime.mobile import MobileAccess


def load_calendar_script():
    path = Path("scripts/configure-calendars.py")
    spec = importlib.util.spec_from_file_location("configure_calendars", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def make_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "development"], cwd=root, check=True)
    (root / "hello.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "base"], cwd=root, check=True)
    cfg = tmp_path / "dev.yaml"
    cfg.write_text(yaml.safe_dump({"enabled": True, "repositories": [{"id": "test", "path": str(root), "live_runtime": False, "test_commands": ["python3 -c 'print(1)'"]}]}))
    return root, DevelopmentLab(str(cfg), str(tmp_path / "dev.db"))


def test_calendar_prompt_normalizes_authorize_google_and_rejects_unknown():
    module = load_calendar_script()
    assert module.normalize_interactive("Authorize google") == ("connect", "google")
    assert module.normalize_interactive("disconnect m365") == ("disconnect", "m365")
    assert module.normalize_interactive("something else") == ("", "")


def test_development_lab_blocks_escape_and_applies_only_validated_digest(tmp_path):
    root, lab = make_repo(tmp_path)
    assert lab.read("test", "hello.txt")["content"] == "hello\n"
    import pytest
    with pytest.raises(ValueError, match="escapes"):
        lab.read("test", "../outside")
    patch = """diff --git a/hello.txt b/hello.txt
--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hello SolomonPrime
"""
    proposal = lab.propose("test", "Greeting", patch, "solomon-core")
    assert lab.validate(proposal["id"])["state"] == "validated"
    with pytest.raises(ValueError, match="digest"):
        lab.apply(proposal["id"], "wrong")
    assert lab.apply(proposal["id"], proposal["patch_sha256"])["state"] == "applied_to_development"
    assert (root / "hello.txt").read_text() == "hello SolomonPrime\n"


def test_live_runtime_repo_cannot_receive_patch(tmp_path):
    root, _ = make_repo(tmp_path)
    cfg = tmp_path / "live.yaml"
    cfg.write_text(yaml.safe_dump({"enabled": True, "repositories": [{"id": "live", "path": str(root), "live_runtime": True}]}))
    lab = DevelopmentLab(str(cfg), str(tmp_path / "live.db"))
    patch = "diff --git a/hello.txt b/hello.txt\n--- a/hello.txt\n+++ b/hello.txt\n@@ -1 +1 @@\n-hello\n+changed\n"
    p = lab.propose("live", "No live", patch, "solomon")
    lab.validate(p["id"])
    import pytest
    with pytest.raises(ValueError, match="live runtime"):
        lab.apply(p["id"], p["patch_sha256"])


def test_approval_lookup_is_digest_bound(tmp_path):
    store = ApprovalStore(str(tmp_path / "approvals.db"))
    payload = {"proposal_id": "DEV-1", "patch_sha256": "abc"}
    approval = store.request(actor="solomon", action="development.apply", payload=payload, risk="mutating")
    assert store.find_approved(action="development.apply", payload=payload) is None
    assert store.approve(approval["id"], by="operator")
    assert store.find_approved(action="development.apply", payload=payload)["id"] == approval["id"]
    assert store.find_approved(action="development.apply", payload={**payload, "patch_sha256": "def"}) is None


def test_v100_packaging_and_mobile_security_contract():
    assert Path("mobile/tricorder-prime/app/src/main/java/com/solomonprime/tricorder/ui/SolomonPrimeScreen.kt").is_file()
    manifest = Path("mobile/tricorder-prime/app/src/main/AndroidManifest.xml").read_text()
    client = Path("mobile/tricorder-prime/app/src/main/java/com/solomonprime/tricorder/data/SolomonPrimeClient.kt").read_text()
    store = Path("mobile/tricorder-prime/app/src/main/java/com/solomonprime/tricorder/data/SolomonPrimeConfigStore.kt").read_text()
    assert 'android:usesCleartextTraffic="false"' in manifest
    assert 'parsed?.scheme != "https"' in client
    assert "AndroidKeyStore" in store and "AES/GCM/NoPadding" in store
    assert Path("scripts/repair-ollama.sh").is_file()
    assert Path("scripts/bootstrap-development-workspaces.sh").is_file()


def test_mobile_credentials_are_hashed_scoped_and_revocable(tmp_path):
    access = MobileAccess(str(tmp_path / "mobile.db"))
    issued = access.issue("flip5", "Tricorder", ["chat", "voice"])
    assert issued["token"].startswith("spm_")
    assert access.authorize(issued["token"], "chat") is True
    assert access.authorize(issued["token"], "models") is False
    assert issued["token"] not in Path(tmp_path / "mobile.db").read_bytes().decode("latin1")
    assert access.revoke("flip5") is True
    assert access.authorize(issued["token"], "chat") is False
