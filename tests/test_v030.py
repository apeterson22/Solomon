from pathlib import Path

from solomonprime.goals import GoalStore
from solomonprime.experiments import ExperimentLedger
from solomonprime.jobs import JobExecutor, JobStore
from solomonprime.registry import NodeRegistry, preferred_from_endpoints


def test_preferred_endpoint_local_first(tmp_path):
    eps=[
        {"endpoint":"http://100.64.1.1:8765","kind":"tailscale","rank":50,"speed_mbps":0},
        {"endpoint":"http://192.0.2.2:8765","kind":"wired","rank":90,"speed_mbps":1000},
        {"endpoint":"http://198.51.100.2:8765","kind":"direct","rank":95,"speed_mbps":1000},
    ]
    assert preferred_from_endpoints(eps)=="http://198.51.100.2:8765"
    r=NodeRegistry(str(tmp_path/'nodes.db'))
    r.upsert({"node_id":"n1","name":"n1","capabilities":[],"network":{"paths":eps}},endpoints=eps)
    assert r.get("n1")["preferred_endpoint"]=="http://198.51.100.2:8765"


def test_goal_engine_and_relationships(tmp_path):
    g=GoalStore(str(tmp_path/'goals.db'))
    a=g.create({"name":"Storage safety","outcome":"Inventory without destructive changes","priority":"high"})
    b=g.create({"name":"Resilience","outcome":"Keep services available"})
    rel=g.relate(a['id'],'supports',b['id'],explanation='safe storage supports resilience')
    assert rel['relation']=='supports'
    assert g.get(a['id'])['relationships'][0]['target_goal']==b['id']
    assert g.update_status(a['id'],'active')['status']=='active'


def test_experiment_ledger(tmp_path):
    e=ExperimentLedger(str(tmp_path/'experiments.db'),str(tmp_path/'artifacts'))
    row=e.create({"title":"Quant benchmark","goal_id":"GOAL-2026-001","hypothesis":"Q4 is faster","metrics":["tokens_per_sec"]})
    assert row['id'].startswith('EXP-')
    assert len(row['manifest_hash'])==64
    e.bind_job(row['id'],job_id='JOB-x',node_id='worker-node')
    updated=e.update_from_job(row['id'],{"status":"completed","started":1,"finished":2,"result":{"metrics":{"tps":12},"artifacts":[]}})
    assert updated['status']=='completed'
    assert updated['metrics']['tps']==12


def test_job_manifest_validation(tmp_path):
    store=JobStore(str(tmp_path/'jobs.db'))
    ex=JobExecutor(store,str(tmp_path/'jobs'),'/bin/false')
    m=ex.validate({"kind":"python","risk":"reversible","source":"print(1)","resources":{"max_runtime_seconds":999999,"max_memory_gb":999}})
    assert m['resources']['max_runtime_seconds']==86400
    assert m['resources']['max_memory_gb']==256.0
    try:
        ex.validate({"kind":"shell","risk":"reversible","source":"id"})
        assert False
    except ValueError:
        pass
    try:
        ex.validate({"kind":"python","risk":"destructive","source":"print(1)"})
        assert False
    except ValueError:
        pass
