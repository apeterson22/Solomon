from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

_SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*([^\s,;]+)")
_ZERO_HASH = "0" * 64


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (
                "<redacted>"
                if any(x in k.lower() for x in ("key", "token", "secret", "password", "authorization"))
                else _redact(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return _SECRET.sub(lambda m: f"{m.group(1)}=<redacted>", value)
    return value


class AuditLog:
    """Append-only hash-chained audit log with constant-time steady-state writes.

    The chain head is recovered once when the process starts and cached after each
    successful append.  This avoids rescanning an ever-growing audit file while
    retaining the on-disk record format used by earlier SolomonPrime releases.
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._cached_last_hash = self._load_last_hash()

    @staticmethod
    def _valid_hash(value: Any) -> bool:
        if not isinstance(value, str) or len(value) != 64:
            return False
        try:
            int(value, 16)
        except ValueError:
            return False
        return True

    def _load_last_hash(self) -> str:
        """Return the newest valid stored hash without reading the whole log.

        Reads backwards in bounded blocks and tolerates an empty or partially
        written final record after an unclean shutdown.
        """
        try:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return _ZERO_HASH

            block_size = 8192
            with self.path.open("rb") as f:
                f.seek(0, 2)
                pos = f.tell()
                buf = b""
                while pos > 0:
                    size = min(block_size, pos)
                    pos -= size
                    f.seek(pos)
                    buf = f.read(size) + buf
                    lines = buf.split(b"\n")
                    # Before reaching byte zero, the first fragment may be only
                    # the tail of an earlier line.  All later fragments are complete.
                    candidates = lines if pos == 0 else lines[1:]
                    for raw_line in reversed(candidates):
                        if not raw_line.strip():
                            continue
                        try:
                            record = json.loads(raw_line.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            continue
                        value = record.get("hash")
                        if self._valid_hash(value):
                            return value
            return _ZERO_HASH
        except OSError:
            return _ZERO_HASH

    def _last_hash(self) -> str:
        """Compatibility accessor; O(1) after startup."""
        return self._cached_last_hash

    def emit(
        self,
        event: str,
        *,
        actor: str = "system",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            rec = {
                "ts": time.time(),
                "event": event,
                "actor": actor,
                "data": _redact(data or {}),
                "prev_hash": self._cached_last_hash,
            }
            raw = json.dumps(rec, sort_keys=True, separators=(",", ":")).encode()
            rec["hash"] = hashlib.sha256(raw).hexdigest()
            line = json.dumps(rec, separators=(",", ":")) + "\n"

            # Do not advance the in-memory chain head unless the append succeeds.
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()

            self._cached_last_hash = rec["hash"]
            return rec
