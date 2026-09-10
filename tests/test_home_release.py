import asyncio
import json
import os
import pty
import threading
import time
from pathlib import Path

import pytest
from solomonprime.approvals import ApprovalStore
from solomonprime.availability import read_availability
from solomonprime.device_lab import analyze_capture, serial_exchange, investigation_plan
from solomonprime.edge_devices import EdgeDeviceRegistry
from solomonprime.jobs import JobExecutor, JobStore
from solomonprime.scheduler import Workload, score_node
from solomonprime.skills import execute_skill


def test_gpu_required_rejects_no_gpu_and_zero_free():
    node={'node_id':'here','trust':'trusted','health':'online','snapshot':{'ram':{'available_gb':8},'gpus':[]}}
    for gpus in ([],[{'vendor':'nvidia','vram_free_mb':0}]):
        node['snapshot']['gpus']=gpus
        assert score_node(node,Workload('gpu',requires_gpu=True),local_node_id='here')[0] < -1e8
    node['snapshot']['gpus']=[{'vendor':'nvidia','vram_free_mb':4096}]
    assert score_node(node,Workload('gpu',requires_gpu=True),local_node_id='here')[0] > 0
    node['snapshot']['availability']={'accepting_jobs':False}
    assert score_node(node,Workload('gpu',requires_gpu=True),local_node_id='here')[1]==['node_unavailable']


def test_availability_expiry_and_corruption_fail_closed(tmp_path):
    path=tmp_path/'gate.json'
    assert read_availability(path)['accepting_jobs']
    for data in ({'mode':'available','expires':time.time()-1}, {'mode':'gaming','expires':time.time()+20}, {'mode':'available','expires':time.time()+10000}):
        path.write_text(json.dumps(data));assert not read_availability(path)['accepting_jobs']
    path.write_text('broken');assert not read_availability(path)['accepting_jobs']
    path.write_text(json.dumps({'mode':'available','expires':time.time()+20}));assert read_availability(path)['accepting_jobs']


def test_job_id_escape_rejected_before_writes(tmp_path):
    executor=JobExecutor(JobStore(str(tmp_path/'jobs.db')),str(tmp_path/'jobs'),'/nonexistent')
    for jid in ('../escape','/tmp/escape','JOB-../../x','JOB-x/y'):
        with pytest.raises(ValueError,match='invalid job id'):
            executor.submit(jid,{'kind':'python','source':'print(1)'},node_id='test')
    assert not list((tmp_path/'jobs').iterdir())


def test_chat_job_requires_exact_single_use_approval(tmp_path):
    approvals=ApprovalStore(str(tmp_path/'approvals.db'));calls=[]
    async def dispatch(payload):calls.append(payload);return {'executed':True}
    kwargs={'approvals':approvals,'edge':None,'dispatch':dispatch}
    result=asyncio.run(execute_skill('solomon_request_job',{'kind':'python','source':'print(3)','purpose':'test'},**kwargs))
    aid=result['approval']['id']
    assert calls==[]
    with pytest.raises(ValueError):asyncio.run(execute_skill('solomon_execute_approved_job',{'approval_id':aid},**kwargs))
    approvals.approve(aid,by='operator')
    assert asyncio.run(execute_skill('solomon_execute_approved_job',{'approval_id':aid},**kwargs))['executed']
    assert calls[0]['allow_network'] is False
    with pytest.raises(ValueError):asyncio.run(execute_skill('solomon_execute_approved_job',{'approval_id':aid},**kwargs))
    assert len(calls)==1


def test_approval_consumption_is_atomic(tmp_path):
    store=ApprovalStore(str(tmp_path/'a.db'));payload={'source':'print(1)'}
    approval=store.request(actor='test',action='skill.job',payload=payload,risk='mutating');store.approve(approval['id'],by='operator')
    assert not store.consume(approval['id'],action='skill.job',payload={'source':'changed'})
    results=[]
    def consume():results.append(store.consume(approval['id'],action='skill.job',payload=payload))
    threads=[threading.Thread(target=consume) for _ in range(8)]
    for thread in threads:thread.start()
    for thread in threads:thread.join()
    assert sum(results)==1


def test_serial_exchange_real_pseudoterminal():
    master,slave=pty.openpty();path=os.ttyname(slave)
    def device():
        request=os.read(master,4)
        if request==b'PING':os.write(master,b'PONG\r\n')
    thread=threading.Thread(target=device,daemon=True);thread.start()
    try:
        result=serial_exchange(path,baud=9600,payload_hex=b'PING'.hex(),duration_seconds=1,max_bytes=6)
        assert result['ok'] and bytes.fromhex(result['response_hex'])==b'PONG\r\n'
        assert result['protocol_validated'] is False
    finally:os.close(master);os.close(slave)
    thread.join(timeout=1)


def test_serial_exchange_rejects_non_device_and_overbounds(tmp_path):
    path=tmp_path/'file';path.write_text('untouched')
    with pytest.raises(ValueError):serial_exchange(str(path),baud=9600,payload_hex='',duration_seconds=1,max_bytes=1)
    assert path.read_text()=='untouched'
    with pytest.raises(ValueError):serial_exchange(str(path),baud=9600,payload_hex='00'*257,duration_seconds=1,max_bytes=1)


def test_serial_request_is_approval_only(tmp_path):
    edge=EdgeDeviceRegistry(str(tmp_path/'catalog.yaml'),str(tmp_path/'edge.db'))
    edge._record_discovery({'fingerprint':'serial-test','transport':'serial','address':'/dev/ttyUSB0'})
    with pytest.raises(ValueError,match='approved'):edge.request_action('serial-test','serial_exchange',actor='test',note='test',parameters={})
    edge.decide('serial-test','approved_for_analysis',actor='operator',note='owned bench device',confirmed=True)
    action=edge.request_action('serial-test','serial_exchange',actor='test',note='listen only',parameters={})
    assert action['state']=='pending' and action['parameters']['payload_hex']==''
    with pytest.raises(ValueError,match='not approved'):edge.execute_action(action['id'],actor='test',confirmed=True)
    plan=edge.lab_plan('serial-test');assert not plan['validated_control']


def test_capture_analysis_does_not_infer_decryption():
    assert analyze_capture(b'')['bytes']==0
    assert 'does not establish encryption' in analyze_capture(bytes(range(256)))['conclusion']


def test_upgrade_preflight_cannot_trigger_uninitialized_rollback():
    script=Path('scripts/upgrade-v1.0.0-common.sh').read_text()
    assert script.index('if [[ $CHECKPOINT_READY -ne 1 ]]') < script.index('systemctl stop solomonprime')
    assert 'd != "upgrade-backups"' in script


def test_host_skills_reject_arbitrary_commands():
    from solomonprime.host_skills import inspect_host
    with pytest.raises(ValueError):inspect_host('uname; touch /tmp/bad')
    result=inspect_host('os')
    assert result['state']=='completed' and result['stdout']


def test_api_routes_authentication_and_approved_chat_dispatch(tmp_path,monkeypatch):
    import dataclasses
    import importlib
    import yaml
    from solomonprime.config import Settings
    from fastapi.testclient import TestClient
    cfg=dataclasses.asdict(Settings())
    for key,value in list(cfg.items()):
        if isinstance(value,str) and value.startswith('/'):
            cfg[key]=str(tmp_path/key/Path(value).name)
    cfg.update(role='controller',cloud_routing_enabled=False,mdns=False,edge_discovery_enabled=False,rf_monitor_enabled=False)
    path=tmp_path/'config.yaml';path.write_text(yaml.safe_dump(cfg));monkeypatch.setenv('SOLOMON_CONFIG',str(path))
    api=importlib.import_module('solomonprime.api')
    client=TestClient(api.app)
    assert client.get('/v1/skills').status_code==401
    auth={'Authorization':'Bearer '+api.public_key_text}
    result=client.get('/v1/skills',headers=auth)
    assert result.status_code==200 and any(t['function']['name']=='solomon_request_job' for t in result.json()['tools'])
    assert client.post('/v1/mesh/host/inspect',json={'skill':'os'},headers=auth).status_code==401
    from solomonprime.security import sign
    body=b'{"skill":"os"}';path='/v1/mesh/host/inspect'
    headers=sign(api.cluster_key,'POST',path,body)
    result=client.post(path,content=body,headers=headers)
    assert result.status_code==200 and result.json()['state']=='completed'
    assert client.post(path,content=body,headers=headers).status_code==401
    import httpx
    sent=[]
    class Backend:
        def __init__(self,*a,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def post(self,url,content,headers):
            sent.append(json.loads(content))
            return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]})
    monkeypatch.setattr(api.httpx,'AsyncClient',Backend)
    monkeypatch.setattr(api.settings,'llm_endpoint','http://127.0.0.1:11434/v1')
    monkeypatch.setattr(api.settings,'llm_model_hint','worker-local-model')
    monkeypatch.setattr(api,'read_availability',lambda:{'accepting_jobs':True})
    path='/v1/inference/chat/completions';body=b'{"model":"controller-model","messages":[]}'
    response=client.post(path,content=body,headers=sign(api.cluster_key,'POST',path,body))
    assert response.status_code==200 and sent[0]['model']=='worker-local-model'
    monkeypatch.setattr(api,'read_availability',lambda:{'accepting_jobs':False})
    assert client.post(path,content=body,headers=sign(api.cluster_key,'POST',path,body)).status_code==409
