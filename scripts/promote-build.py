#!/usr/bin/env python3
"""Operator-only promotion of an exact approved local build; never called by chat.

The existing release upgrader owns migration, checkpoint and rollback. This
entrypoint authenticates the approval and freezes bytes before executing it.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path


def unpack(blob: bytes, destination: Path):
    total=0;seen=set()
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
        for item in archive.getmembers():
            path=Path(item.name)
            if not item.isfile() or path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='solomonprime':
                raise ValueError('unsafe build archive')
            if item.name in seen:raise ValueError('duplicate archive path')
            seen.add(item.name);total+=item.size
            if total>32*1024*1024:raise ValueError('archive exceeds size limit')
            target=destination/path;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as handle:handle.write(archive.extractfile(item).read())
            target.chmod(0o755 if item.mode&0o111 else 0o644)


def main():
    if os.geteuid()!=0:raise SystemExit('Run with sudo from an operator shell')
    if len(sys.argv)!=3 or not re.fullmatch(r'BUILD-[a-f0-9]{16}',sys.argv[1]):raise SystemExit('Usage: promote-build.py BUILD-ID APPROVAL-ID')
    bid,aid=sys.argv[1:];root=Path('/var/lib/solomonprime/builds')
    archive=root/bid/'source.tar.gz'
    fd=os.open(archive,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as handle:blob=handle.read(1024*1024+1)
    if len(blob)>1024*1024:raise SystemExit('archive too large')
    digest=hashlib.sha256(blob).hexdigest()
    payload={'build_id':bid,'archive_sha256':digest,'role':'controller'}
    plan=hashlib.sha256(json.dumps({'action':'maintenance.promote','payload':payload},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    stage=Path(tempfile.mkdtemp(prefix='solomon-promote-',dir='/var/tmp'));stage.chmod(0o700)
    unpack(blob,stage)
    deploy=stage/'solomonprime/deploy.sh'
    if not deploy.is_file():raise SystemExit('snapshot has no deploy.sh; not an installable runtime package')
    with sqlite3.connect('/var/lib/solomonprime/approvals.db') as con:
        changed=con.execute("UPDATE approvals SET state='consumed' WHERE id=? AND action='maintenance.promote' AND plan_hash=? AND state='approved' AND approved>=?",(aid,plan,time.time()-3600))
        if changed.rowcount!=1:raise SystemExit('matching unused, unexpired Admin promotion approval required')
    print('Promoting approved snapshot '+digest+'; staging retained at '+str(stage))
    result=subprocess.run(['bash',str(deploy),'controller','upgrade'],cwd=deploy.parent,check=False)
    print('Upgrade exit code:',result.returncode)
    return result.returncode

if __name__=='__main__':raise SystemExit(main())
