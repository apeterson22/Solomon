"""Bounded serial bench adapter. Never probes a port during discovery.

Opening a serial port can toggle control lines on some hardware. Both listening
and transmitting therefore require a device-specific, single-use approval.
"""
from __future__ import annotations
import collections
import hashlib
import math
import os
import select
import stat
import time
from pathlib import Path


def analyze_capture(data: bytes) -> dict:
    counts = collections.Counter(data)
    entropy = -sum((n / len(data)) * math.log2(n / len(data)) for n in counts.values()) if data else 0
    lines = data.decode('ascii', errors='replace').splitlines()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'entropy_bits_per_byte': round(entropy, 3),
            'printable_fraction': round(sum(32 <= b <= 126 or b in (9, 10, 13) for b in data) / max(1, len(data)), 3),
            'possible_nmea': any(line.startswith(('$GP', '$GN')) and '*' in line for line in lines),
            'conclusion': 'Heuristics only; entropy does not establish encryption or protocol identity.'}


def serial_exchange(path: str, *, baud: int, payload_hex: str, duration_seconds: int, max_bytes: int) -> dict:
    import termios
    import tty
    if baud not in (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200):
        raise ValueError('unsupported baud')
    if not 1 <= duration_seconds <= 10 or not 1 <= max_bytes <= 16384:
        raise ValueError('serial capture bounds exceeded')
    payload = bytes.fromhex(payload_hex)
    if len(payload) > 256:
        raise ValueError('serial write exceeds 256 bytes')
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK | os.O_NOFOLLOW)
    previous = None
    data = bytearray()
    sent = 0
    try:
        if not stat.S_ISCHR(os.fstat(fd).st_mode):
            raise ValueError('serial target is not a character device')
        previous = termios.tcgetattr(fd)
        tty.setraw(fd, termios.TCSANOW)
        attrs = termios.tcgetattr(fd)
        attrs[4] = attrs[5] = getattr(termios, 'B' + str(baud))
        attrs[2] |= termios.CLOCAL | termios.CREAD
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline and len(data) < max_bytes:
            readable, writable, _ = select.select([fd], [fd] if sent < len(payload) else [], [], min(.1, max(0, deadline-time.monotonic())))
            if writable:
                try: sent += os.write(fd, payload[sent:])
                except BlockingIOError: pass
            if readable:
                try: chunk = os.read(fd, max_bytes-len(data))
                except BlockingIOError: continue
                if not chunk: break
                data.extend(chunk)
        return {'ok': sent == len(payload), 'bytes_written': sent, 'response_hex': data.hex(),
                'analysis': analyze_capture(bytes(data)), 'protocol_validated': False}
    finally:
        try:
            if previous is not None: termios.tcsetattr(fd, termios.TCSANOW, previous)
        finally: os.close(fd)


def investigation_plan(device: dict) -> dict:
    return {'fingerprint': device['fingerprint'], 'validated_control': False,
            'steps': [
                {'method': 'descriptor_and_driver_mapping', 'mode': 'passive', 'state': 'available'},
                {'method': 'documented_protocol_or_existing_open_driver', 'mode': 'research', 'state': 'requires_device_evidence'},
                {'method': 'bounded_serial_capture_and_exact_byte_exchange', 'mode': 'approved_bench',
                 'state': 'available' if device['transport'] == 'serial' else 'requires_serial_interface'},
                {'method': 'vendor_software_capture_and_replay_analysis', 'mode': 'owned_device_lab', 'state': 'manual_capture_required'},
                {'method': 'official_key_pairing_or_local_vendor_bridge', 'mode': 'authorized_access', 'state': 'device_specific'},
                {'method': 'replacement_firmware_or_external_sensor_actuator', 'mode': 'hardware_alternative', 'state': 'separate_validated_adapter_required'}],
            'constraints': ['No automatic baud sweep or command fuzzing on attached equipment.',
                           'Encrypted captures are not claimed decryptable without authorized keys.',
                           'Firmware replacement requires compatibility evidence, backup/recovery and separate approval.',
                           'Record each experiment, expected response and observed result before promoting control.']}
