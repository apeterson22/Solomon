#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import pwd
import grp
import shutil
import subprocess
import sys
import time
import tempfile
from pathlib import Path

ROOT = Path('/apps/solomonprime-jobs').resolve()
ALLOWED = {'python', 'blender', 'openscad'}


def fail(msg: str, code: int = 2):
    print(f'[SOLOMON-JOB][ERROR] {msg}', file=sys.stderr)
    raise SystemExit(code)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tail_text(path: Path, limit: int = 12000) -> str:
    if not path.exists() or path.is_symlink():
        return ''
    with path.open('rb') as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - limit), os.SEEK_SET)
        return handle.read(limit).decode('utf-8', errors='replace')


def workspace_bytes(workspace: Path) -> int:
    total = 0
    for item in workspace.rglob('*'):
        try:
            info = item.lstat()
            if item.is_symlink() or not item.is_file():
                continue
            total += info.st_size
        except OSError:
            continue
    return total


def write_result(workspace: Path, result: dict, group_id: int) -> None:
    # The sandbox has exited. Freeze the parent and atomically replace the entry;
    # never open a job-controlled result.json symlink as root.
    os.chown(workspace, 0, group_id, follow_symlinks=False)
    workspace.chmod(0o750)
    fd, name = tempfile.mkstemp(prefix='.result-', dir=workspace)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.flush(); os.fsync(handle.fileno())
            os.fchown(handle.fileno(), 0, group_id)
            os.fchmod(handle.fileno(), 0o640)
        os.replace(name, workspace / 'result.json')
    finally:
        Path(name).unlink(missing_ok=True)


def main() -> int:
    if os.geteuid() != 0:
        fail('runner must execute as root through the SolomonPrime job broker')
    if len(sys.argv) != 2:
        fail('usage: solomon-job-runner.py /apps/solomonprime-jobs/JOB-.../manifest.json')
    manifest_path = Path(sys.argv[1]).resolve()
    try:
        manifest_path.relative_to(ROOT)
    except ValueError:
        fail('manifest path is outside the SolomonPrime job root')
    if manifest_path.name != 'manifest.json' or not manifest_path.is_file():
        fail('invalid manifest path')
    workspace = manifest_path.parent.resolve()
    try:
        m = json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as e:
        fail(f'invalid manifest: {e}')
    if Path(str(m.get('workspace') or '')).resolve() != workspace:
        fail('workspace mismatch')
    kind = str(m.get('kind') or '').lower()
    if kind not in ALLOWED:
        fail(f'unsupported kind: {kind}')
    if str(m.get('risk') or 'reversible') not in {'read_only', 'reversible'}:
        fail('only read_only/reversible jobs are executable')

    resources = dict(m.get('resources') or {})
    runtime = min(max(int(resources.get('max_runtime_seconds') or 900), 1), 86400)
    memory_gb = min(max(float(resources.get('max_memory_gb') or 4), .25), 256)
    cpu_cores = min(max(float(resources.get('max_cpu_cores') or 2), .1), 64)
    disk_gb = min(max(float(resources.get('max_disk_gb') or 4), .1), 512)
    allow_network = bool(m.get('allow_network', False))

    src = workspace / str(m.get('source_file') or '')
    if not src.is_file() or src.parent != workspace:
        fail('source file missing or invalid')

    binaries = {
        'python': ['/usr/bin/python3', src.name],
        'blender': ['/usr/bin/blender', '-b', '--python', src.name],
        'openscad': ['/usr/bin/openscad', '-o', 'output.stl', src.name],
    }
    exe = Path(binaries[kind][0])
    if not exe.exists():
        fail(f'executor is not installed: {exe}')

    job_user = pwd.getpwnam('solomonjob')
    job_group = grp.getgrgid(job_user.pw_gid).gr_name
    for p in workspace.iterdir():
        try:
            os.chown(p, job_user.pw_uid, job_user.pw_gid)
        except Exception:
            pass
    os.chown(workspace, job_user.pw_uid, job_user.pw_gid)
    # Keep the submitting API user read-only while the executable is being
    # opened and run. The broker restores group write access after completion.
    workspace.chmod(0o750)

    unit = 'solomon-job-' + ''.join(c if c.isalnum() else '-' for c in str(m.get('job_id') or workspace.name))[:50]
    stdout_path = workspace / 'job.stdout.log'
    stderr_path = workspace / 'job.stderr.log'
    props = [
        f'WorkingDirectory={workspace}',
        'NoNewPrivileges=yes',
        'ProtectSystem=strict',
        'ProtectHome=yes',
        'PrivateTmp=yes',
        'PrivateMounts=yes',
        'ProtectKernelTunables=yes',
        'ProtectKernelModules=yes',
        'ProtectKernelLogs=yes',
        'ProtectControlGroups=yes',
        'RestrictSUIDSGID=yes',
        'LockPersonality=yes',
        'SystemCallArchitectures=native',
        'UMask=0027',
        'TasksMax=256',
        f'MemoryMax={int(memory_gb * 1024**3)}',
        f'CPUQuota={max(1, int(cpu_cores * 100))}%',
        f'RuntimeMaxSec={runtime}',
        f'LimitFSIZE={int(disk_gb * 1024**3)}',
        f'ReadWritePaths={workspace}',
        f'StandardOutput=append:{stdout_path}',
        f'StandardError=append:{stderr_path}',
        'InaccessiblePaths=/etc/solomonprime /var/lib/solomonprime /var/log/solomonprime /root -/mnt -/media',
    ]
    if not allow_network:
        props.append('PrivateNetwork=yes')
    else:
        props.append('RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6')

    cmd = ['systemd-run', '--wait', '--collect', '--quiet', f'--unit={unit}', '--uid=solomonjob', f'--gid={job_group}']
    for p in props:
        cmd += ['--property', p]
    cmd += binaries[kind]

    started = time.time()
    proc = subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    disk_limit_bytes = int(disk_gb * 1024**3)
    disk_limit_exceeded = False
    interrupted = False
    while proc.poll() is None:
        gate=Path('/etc/solomonprime/availability.json')
        if gate.exists():
            try:
                availability=json.loads(gate.read_text())
                available=availability.get('mode')=='available' and time.time()<float(availability['expires'])<=time.time()+120
            except Exception: available=False
            if not available:
                interrupted = True
                subprocess.run(['systemctl','stop',f'{unit}.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                print('[SOLOMON-JOB] interrupted: worker unavailable',file=sys.stderr)
                break
        if workspace_bytes(workspace) > disk_limit_bytes:
            disk_limit_exceeded = True
            subprocess.run(
                ['systemctl', 'kill', '--kill-whom=all', f'{unit}.service'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            break
        time.sleep(.2)
    try:
        stdout, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill(); stdout, stderr = proc.communicate()
    return_code = 125 if interrupted else 122 if disk_limit_exceeded else proc.returncode
    finished = time.time()
    print(stdout, end='')
    if stderr:
        print(stderr, end='', file=sys.stderr)
    if disk_limit_exceeded:
        print('[SOLOMON-JOB][ERROR] total workspace disk limit exceeded', file=sys.stderr)

    artifacts = []
    total = 0
    excluded = {'manifest.json', src.name, 'result.json', 'runner.stdout.log', 'runner.stderr.log'}
    for p in sorted(workspace.rglob('*')):
        if p.is_symlink() or not p.is_file() or p.name in excluded:
            continue
        try:
            rel = str(p.relative_to(workspace)); size = p.stat().st_size; total += size
            artifacts.append({'path': rel, 'size': size, 'sha256': sha256(p)})
            if len(artifacts) >= 100:
                break
        except Exception:
            continue

    result = {
        'job_id': str(m.get('job_id') or workspace.name),
        'kind': kind,
        'exit_code': return_code,
        'started': started,
        'finished': finished,
        'metrics': {
            'runtime_seconds': round(finished - started, 3),
            'artifact_bytes': total,
            'artifact_count': len(artifacts),
            'max_runtime_seconds': runtime,
            'max_memory_gb': memory_gb,
            'max_cpu_cores': cpu_cores,
            'max_disk_gb': disk_gb,
            'network_enabled': allow_network,
        },
        'artifacts': artifacts,
        'stdout_tail': tail_text(stdout_path),
        'stderr_tail': tail_text(stderr_path),
        'disk_limit_exceeded': disk_limit_exceeded,
    }
    write_result(workspace, result, job_user.pw_gid)
    workspace.chmod(0o770)
    return return_code


if __name__ == '__main__':
    raise SystemExit(main())
