"""Local, snapshot-bound build orchestration through the existing sandbox broker.

Never runs repository code in the API service process. Packages are built from the
exact source snapshot tested by a separate bounded job, not a mutable live tree.
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import tarfile
import time
import uuid
from pathlib import Path

IGNORED={'.git','.venv','.pytest_cache','__pycache__','node_modules','dist','build','.gradle'}
MAX_TOTAL=32*1024*1024
MAX_ARCHIVE=650*1024


def snapshot_repository(root: Path, sensitive) -> tuple[bytes,list[dict]]:
    files=[];total=0;buffer=io.BytesIO()
    # Include tracked and new nonignored source. No Git hooks or shell execution.
    proc=subprocess.run(['git','-c','core.fsmonitor=false','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root,capture_output=True,check=True,timeout=20)
    names=sorted(set(os.fsdecode(x) for x in proc.stdout.split(b'\0') if x))
    with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
        for name in names:
            rel=Path(name)
            if rel.is_absolute() or '..' in rel.parts:raise ValueError('unsafe source path')
            if any(p in IGNORED or p.endswith('.egg-info') for p in rel.parts):continue
            if sensitive(name) or rel.suffix in {'.db','.sqlite','.log','.apk','.aab'}:raise ValueError('sensitive/generated source must be excluded: '+name)
            path=root/rel
            if not path.exists():continue  # tracked deletion
            if any((root/Path(*rel.parts[:i])).is_symlink() for i in range(1,len(rel.parts)+1)):
                raise ValueError('symlink source is not packageable')
            if not path.is_file():raise ValueError('source is not a regular file')
            data=path.read_bytes();total+=len(data)
            if total>MAX_TOTAL:raise ValueError('source exceeds build size limit')
            if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{24,}|\bgh[pousr]_[A-Za-z0-9]{25,}',data):
                raise ValueError('possible credential in source: '+name)
            info=tarfile.TarInfo('solomonprime/'+name);info.size=len(data);info.mode=0o755 if path.stat().st_mode&0o111 else 0o644
            archive.addfile(info,io.BytesIO(data));files.append({'path':name,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)})
    result=buffer.getvalue()
    if not files or len(result)>MAX_ARCHIVE:raise ValueError('empty or oversized source snapshot')
    return result,files


def build_job_source(archive: bytes, files: list[dict], commands: list[list[str]]) -> str:
    """Generate a fixed harness with source bytes as encoded data, never shell code."""
    payload=base64.b64encode(archive).decode()
    return '''import base64, hashlib, io, json, os, pathlib, subprocess, sys, tarfile
blob=base64.b64decode(PAYLOAD)
assert hashlib.sha256(blob).hexdigest()==DIGEST
root=pathlib.Path('source');root.mkdir()
with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
    for member in archive.getmembers():
        path=pathlib.PurePosixPath(member.name)
        if not member.isfile() or path.is_absolute() or '..' in path.parts:raise RuntimeError('invalid snapshot')
        target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(archive.extractfile(member).read());target.chmod(member.mode & 0o755)
work=root/'solomonprime'
def verify():
    for item in FILES:
        p=work/item['path']
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
            raise RuntimeError('source changed during test: '+item['path'])
verify()
env={'PATH':'/apps/solomonprime-build/.venv/bin:/usr/bin:/bin','HOME':str(pathlib.Path('test-home').resolve()),'CI':'true','PYTHONPATH':str(work.resolve()),'LANG':'C.UTF-8'}
pathlib.Path(env['HOME']).mkdir()
for command in COMMANDS:
    result=subprocess.run(command,cwd=work,env=env,timeout=1500,check=False)
    if result.returncode:raise SystemExit(result.returncode)
verify()
print('SOLOMON_BUILD_TESTS_PASSED '+DIGEST)
'''.replace('PAYLOAD',repr(payload)).replace('DIGEST',repr(hashlib.sha256(archive).hexdigest())).replace('FILES',repr(files)).replace('COMMANDS',repr(commands))


class Maintenance:
    def __init__(self,root,development,executor,jobs,node_id):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.development=development;self.executor=executor;self.jobs=jobs;self.node_id=node_id
        self.db=self.root/'builds.db'
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE IF NOT EXISTS builds(id TEXT PRIMARY KEY, repository TEXT, job_id TEXT, digest TEXT, state TEXT, created REAL)')

    def start(self,repository):
        item,root=self.development._repo(repository)
        if item.get('live_runtime'):raise ValueError('build from a development repository only')
        import shlex
        commands=[shlex.split(str(x)) for x in item.get('test_commands',[])][:5]
        if not commands or any(not x for x in commands):raise ValueError('allowlisted test commands required')
        archive,files=snapshot_repository(root,self.development._sensitive)
        bid='BUILD-'+uuid.uuid4().hex[:16];jid='JOB-'+uuid.uuid4().hex
        directory=self.root/bid;directory.mkdir(mode=0o750)
        (directory/'source.tar.gz').write_bytes(archive)
        digest=hashlib.sha256(archive).hexdigest()
        source=build_job_source(archive,files,commands)
        with sqlite3.connect(self.db) as c:c.execute('INSERT INTO builds VALUES(?,?,?,?,?,?)',(bid,repository,jid,digest,'submitted',time.time()))
        try:
            self.executor.submit(jid,{'kind':'python','risk':'reversible','source':source,'allow_network':False,
                'resources':{'max_runtime_seconds':1800,'max_memory_gb':4,'max_cpu_cores':2,'max_disk_gb':2},
                'metadata':{'build_id':bid,'source_sha256':digest}},node_id=self.node_id)
        except Exception:
            with sqlite3.connect(self.db) as c:c.execute("UPDATE builds SET state='submission_failed' WHERE id=?",(bid,))
            raise
        return self.status(bid)

    def status(self,bid):
        with sqlite3.connect(self.db) as c:
            c.row_factory=sqlite3.Row;row=c.execute('SELECT * FROM builds WHERE id=?',(bid,)).fetchone()
        if not row:raise ValueError('build not found')
        record=dict(row);job=self.jobs.get(record['job_id']) or {}
        state=job.get('status',record['state'])
        directory=self.root/record['id'];archive=directory/'source.tar.gz'
        if state=='completed':
            if hashlib.sha256(archive.read_bytes()).hexdigest()!=record['digest']:raise ValueError('build snapshot changed')
            evidence=job.get('result') or {}
            marker='SOLOMON_BUILD_TESTS_PASSED '+record['digest']
            if marker not in evidence.get('stdout_tail',''):state='evidence_missing'
            else:
                state='package_ready'
                manifest={'build_id':bid,'repository':record['repository'],'job_id':record['job_id'],'archive_sha256':record['digest'],
                    'test_exit_code':job.get('exit_code'),'deployment_approved':False,'requires_operator_promotion':True}
                (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        return {**record,'state':state,'job':{k:job.get(k) for k in ('id','status','exit_code','error','result')},'archive_path':str(archive) if state=='package_ready' else None,
                'automatic_live_install':False}

    def list(self):
        with sqlite3.connect(self.db) as c:
            rows=c.execute('SELECT id FROM builds ORDER BY created DESC LIMIT 30').fetchall()
        return [{k:v for k,v in self.status(row[0]).items() if k!='job'} for row in rows]
