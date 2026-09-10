from pathlib import Path
import yaml

from solomonprime.cloud_router import CloudRouter, complexity_score, contains_sensitive


def mk(tmp_path, provider):
    cfg=tmp_path/'cloud.yaml'
    cfg.write_text(yaml.safe_dump({'providers':[provider]}))
    return CloudRouter(str(cfg),str(tmp_path/'quota.db'),str(tmp_path/'training'),complexity_threshold=.5,quota_margin=.9)


def test_complexity_and_sensitive():
    assert complexity_score('hi') < complexity_score('Design a comprehensive multi-step simulation architecture and optimize it')
    assert contains_sensitive('api_key=ABCDEF1234567890')


def test_unknown_quota_denied(tmp_path):
    p={'name':'x','kind':'openai_compatible','enabled':True,'billing_mode':'free','allow_overage':False,
       'endpoint':'https://example.invalid/v1','model':'m','api_key_file':str(tmp_path/'key'),'limits':{}}
    (tmp_path/'key').write_text('x')
    r=mk(tmp_path,p)
    prov=r.providers()[0]
    ok,why,res=r._eligible(prov,100)
    assert not ok and 'quota' in why


def test_hard_quota_reservation(tmp_path):
    p={'name':'x','kind':'openai_compatible','enabled':True,'billing_mode':'free','allow_overage':False,
       'endpoint':'https://example.invalid/v1','model':'m','api_key_file':str(tmp_path/'key'),'max_output_tokens':100,
       'limits':{'daily_requests':2,'monthly_requests':2,'monthly_input_tokens':1000,'monthly_output_tokens':300}}
    (tmp_path/'key').write_text('x')
    r=mk(tmp_path,p);prov=r.providers()[0]
    ok,why,res=r._eligible(prov,100);assert ok
    r.ledger.reserve(prov,res)
    ok,why,res=r._eligible(prov,100);assert not ok  # 90% margin makes 2nd request exceed 1.8 hard-stop


def test_overage_never_eligible(tmp_path):
    p={'name':'x','kind':'openai_compatible','enabled':True,'billing_mode':'free','allow_overage':True,
       'endpoint':'https://example.invalid/v1','model':'m','api_key_file':str(tmp_path/'key'),
       'limits':{'daily_requests':100,'monthly_requests':100,'monthly_input_tokens':100000,'monthly_output_tokens':100000}}
    (tmp_path/'key').write_text('x')
    r=mk(tmp_path,p);ok,why,_=r._eligible(r.providers()[0],100)
    assert not ok and 'allow_overage' in why


def test_copilot_requires_account_overage_disabled(tmp_path):
    p={'name':'cop','kind':'copilot_cli','enabled':True,'billing_mode':'subscription-included','allow_overage':False,
       'account_overage_disabled':False,'max_ai_credits_per_call':30,
       'limits':{'daily_requests':10,'monthly_requests':100,'monthly_ai_credits':1000}}
    r=mk(tmp_path,p);ok,why,_=r._eligible(r.providers()[0],100)
    assert not ok and 'additional usage' in why.lower()


def test_openai_cannot_be_mislabeled_free(tmp_path):
    p={'name':'openai','kind':'openai','enabled':True,'billing_mode':'free','allow_overage':False,
       'endpoint':'https://api.openai.com/v1','model':'x','api_key_file':str(tmp_path/'key'),
       'limits':{'daily_requests':10,'monthly_requests':10,'monthly_input_tokens':1000,'monthly_output_tokens':1000}}
    (tmp_path/'key').write_text('x')
    r=mk(tmp_path,p);ok,why,_=r._eligible(r.providers()[0],100)
    assert not ok and 'metered' in why


def test_ollama_local_needs_no_api_key(tmp_path):
    p={'name':'ollama','kind':'ollama_local','enabled':True,'billing_mode':'free','allow_overage':False,'max_output_tokens':100,
       'endpoint':'http://127.0.0.1:11434/v1','model':'qwen','limits':{
       'daily_requests':10,'monthly_requests':10,'monthly_input_tokens':1000,'monthly_output_tokens':1000}}
    r=mk(tmp_path,p);assert r._eligible(r.providers()[0],100)[0]
