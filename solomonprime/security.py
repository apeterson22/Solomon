from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path


class ReplayGuard:
    def __init__(self, ttl: int = 180):
        self.ttl = ttl
        self._seen: dict[str, float] = {}

    def accept(self, nonce: str, ts: int) -> bool:
        now = int(time.time())
        self._seen = {k: v for k, v in self._seen.items() if now - v < self.ttl}
        if abs(now - ts) > self.ttl or nonce in self._seen:
            return False
        self._seen[nonce] = now
        return True


def ensure_key(path: str, nbytes: int = 32) -> bytes:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists() or not p.read_text().strip():
        p.write_text(secrets.token_hex(nbytes) + "\n", encoding="utf-8")
        p.chmod(0o600)
    return bytes.fromhex(p.read_text().strip())


def sign(key: bytes, method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    nonce = secrets.token_hex(12)
    digest = hashlib.sha256(body).hexdigest()
    msg = "\n".join([method.upper(), path, ts, nonce, digest]).encode()
    sig = hmac.new(key, msg, hashlib.sha256).hexdigest()
    return {"X-Solomon-Timestamp": ts, "X-Solomon-Nonce": nonce, "X-Solomon-Signature": sig}


def verify(key: bytes, method: str, path: str, body: bytes, headers: dict[str, str], replay: ReplayGuard) -> bool:
    try:
        ts = int(headers.get("x-solomon-timestamp", "0"))
        nonce = headers.get("x-solomon-nonce", "")
        sig = headers.get("x-solomon-signature", "")
        if not nonce or not sig or not replay.accept(nonce, ts):
            return False
        digest = hashlib.sha256(body).hexdigest()
        msg = "\n".join([method.upper(), path, str(ts), nonce, digest]).encode()
        expected = hmac.new(key, msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False
