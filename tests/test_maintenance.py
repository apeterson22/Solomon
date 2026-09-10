import asyncio
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from solomonprime.selfdev import DevelopmentLab
from solomonprime.maintenance import snapshot_repository,build_job_source
from solomonprime.approvals import ApprovalStore
from solomonprime.skills import execute_skill


def repo(tmp):
    root=tmp/'repo';root.mkdir()
    subprocess.run(['git','init','-q',str(root)],check=True)
    (root/'calc.py').write_text('def add(a,b):\n    return a-b\n')
    (root/'check.py').write_text('from calc import add\nassert add(2,3)==5\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    cfg=tmp/'dev.yaml';cfg.write_text(yaml.safe_dump({'enabled':True,'repositories':[{'id':'code','path':str(root),'test_commands':[sys.executable+' check.py']}]}))
    return root,DevelopmentLab(str(cfg),str(tmp/'dev.db'))


def run_harness(root,tmp):
    archive,files=snapshot_repository(root,DevelopmentLab._sensitive)
    code=build_job_source(archive,files,[[sys.executable,'check.py']])
    tmp.mkdir();script=tmp/'harness.py';script.write_text(code)
    # This test runs only the fixed two-line fixture, not arbitrary repository code.
    return subprocess.run([sys.executable,str(script)],cwd=tmp,capture_output=True,text=True,timeout=10)


def test_bug_fix_chat_proposal_to_tested_snapshot(tmp_path):
    root,lab=repo(tmp_path)
    assert run_harness(root,tmp_path/'before').returncode!=0
    patch='diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a,b):\n-    return a-b\n+    return a+b\n'
    approvals=ApprovalStore(str(tmp_path/'approvals.db'))
    args={'approvals':approvals,'edge':None,'dispatch':None,'development':lab}
    proposal=asyncio.run(execute_skill('solomon_development_propose',{'repository':'code','title':'Fix addition','patch':patch},**args))
    asyncio.run(execute_skill('solomon_development_validate',{'proposal_id':proposal['id']},**args))
    approval=asyncio.run(execute_skill('solomon_development_request_apply',{'proposal_id':proposal['id']},**args))
    with pytest.raises(ValueError):asyncio.run(execute_skill('solomon_development_apply',{'proposal_id':proposal['id'],'approval_id':approval['id']},**args))
    approvals.approve(approval['id'],by='operator')
    applied=asyncio.run(execute_skill('solomon_development_apply',{'proposal_id':proposal['id'],'approval_id':approval['id']},**args))
    assert applied['state']=='applied_to_development'
    result=run_harness(root,tmp_path/'after')
    assert result.returncode==0 and 'SOLOMON_BUILD_TESTS_PASSED' in result.stdout


def test_same_git_status_changed_bytes_invalidates_proposal(tmp_path):
    root,lab=repo(tmp_path)
    (root/'calc.py').write_text('def add(a,b):\n    return a-b\n# initial\n')
    patch='diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,3 +1,3 @@\n def add(a,b):\n-    return a-b\n+    return a+b\n # initial\n'
    p=lab.propose('code','fix',patch,'test');lab.validate(p['id'])
    (root/'check.py').write_text('raise RuntimeError("changed")\n')
    with pytest.raises(ValueError,match='changed'):lab.apply(p['id'],p['patch_sha256'])


def test_snapshot_blocks_symlink_and_secret(tmp_path):
    root,lab=repo(tmp_path)
    (root/'.env.local').write_text('private')
    with pytest.raises(ValueError,match='sensitive'):snapshot_repository(root,lab._sensitive)
    (root/'.env.local').unlink();(root/'link').symlink_to(root/'calc.py')
    with pytest.raises(ValueError,match='symlink'):snapshot_repository(root,lab._sensitive)


def test_test_runner_fails_closed_without_sandbox(tmp_path):
    _,lab=repo(tmp_path)
    with pytest.raises(ValueError,match='isolated'):lab.test('code')


def test_root_result_write_does_not_follow_symlink(tmp_path):
    script=Path('scripts/solomon-job-runner.py')
    spec=importlib.util.spec_from_file_location('root_runner',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    work=tmp_path/'job';work.mkdir();victim=tmp_path/'victim';victim.write_text('preserve')
    (work/'result.json').symlink_to(victim)
    if os.geteuid()!=0:pytest.skip('root-owned output test requires root')
    module.write_result(work,{'exit_code':0},os.getgid())
    assert victim.read_text()=='preserve' and not (work/'result.json').is_symlink()


def test_promote_archive_rejects_escape_and_symlinks(tmp_path):
    import io,tarfile
    spec=importlib.util.spec_from_file_location('promote',Path('scripts/promote-build.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for name,kind in [('../escape',tarfile.REGTYPE),('solomonprime/link',tarfile.SYMTYPE)]:
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w:gz') as archive:
            item=tarfile.TarInfo(name);item.type=kind;item.linkname='/etc/passwd';archive.addfile(item)
        with pytest.raises(ValueError):module.unpack(data.getvalue(),tmp_path)
    assert not (tmp_path.parent/'escape').exists()


def test_build_status_requires_pass_evidence_and_matching_snapshot(tmp_path):
    from solomonprime.maintenance import Maintenance
    from solomonprime.jobs import JobStore
    root,lab=repo(tmp_path);jobs=JobStore(str(tmp_path/'jobs.db'))
    class RecordingExecutor:
        def submit(self,jid,manifest,**kw):return jobs.create(jid,manifest,node_id='test')
    service=Maintenance(tmp_path/'builds',lab,RecordingExecutor(),jobs,'test')
    started=service.start('code');jid=started['job_id']
    assert started['state']=='queued'
    jobs.update(jid,status='completed',exit_code=0,result={})
    assert service.status(started['id'])['state']=='evidence_missing'
    jobs.update(jid,status='completed',exit_code=0,result={'stdout_tail':'SOLOMON_BUILD_TESTS_PASSED '+started['digest']})
    assert service.status(started['id'])['state']=='package_ready'
    (tmp_path/'builds'/started['id']/'source.tar.gz').write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):service.status(started['id'])
