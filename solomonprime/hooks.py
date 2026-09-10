from __future__ import annotations

import re
from dataclasses import dataclass

@dataclass
class HookResult:
    allowed: bool
    risk: str
    reason: str

_BLOCK = [
    (re.compile(r"(^|\s)mkfs(\.|\s)", re.I), "filesystem formatting"),
    (re.compile(r"(^|\s)dd\s+.*\bof=/dev/", re.I), "raw block-device write"),
    (re.compile(r"rm\s+-[^\n]*r[^\n]*f[^\n]*\s+/(\s|$)", re.I), "recursive root deletion"),
    (re.compile(r"(^|\s)wipefs\b", re.I), "filesystem signature wipe"),
]
_WARN = [
    (re.compile(r"\b(apt|apt-get|dnf|yum|pacman)\s+(remove|purge|upgrade|dist-upgrade)\b", re.I), "package mutation"),
    (re.compile(r"\bsystemctl\s+(disable|mask|stop|restart)\b", re.I), "service mutation"),
    (re.compile(r"\bufw\s+(enable|disable|reset|delete)\b", re.I), "firewall mutation"),
    (re.compile(r"\b(chmod\s+777|chown\s+-R)\b", re.I), "broad permission mutation"),
]

def classify_command(command: str) -> HookResult:
    for rx, why in _BLOCK:
        if rx.search(command): return HookResult(False, "critical", why)
    for rx, why in _WARN:
        if rx.search(command): return HookResult(False, "mutating", why)
    if re.search(r"(^|\s)(mv|rm|cp|rsync|mount|umount|parted|fdisk)\b", command):
        return HookResult(False, "mutating", "filesystem mutation")
    return HookResult(True, "read_only", "read-only/unclassified safe command")
