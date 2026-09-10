"""Executable chat skills. Approval decisions never belong to the model."""
from __future__ import annotations
from typing import Any


def tool(name, description, properties, required=()):
    return {'type':'function','function':{'name':name,'description':description,'parameters':{
        'type':'object','properties':properties,'required':list(required),'additionalProperties':False}}}

TEXT={'type':'string'}
EXECUTION_TOOLS = [
    tool('solomon_development_request_promotion','Request Admin approval for a tested build digest; returns the separate operator deployment command, never installs itself.',{'build_id':TEXT},('build_id',)),
    tool('solomon_development_propose','Create a unified-diff proposal against an allowlisted development repository.',{'repository':TEXT,'title':TEXT,'patch':TEXT},('repository','title','patch')),
    tool('solomon_development_validate','Check a proposed patch and bind it to current source contents.',{'proposal_id':TEXT},('proposal_id',)),
    tool('solomon_development_request_apply','Request Admin approval for the exact validated development patch.',{'proposal_id':TEXT},('proposal_id',)),
    tool('solomon_development_apply','Apply an exact Admin-approved patch to development only, consuming the approval once.',{'proposal_id':TEXT,'approval_id':TEXT},('proposal_id','approval_id')),
    tool('solomon_development_build','Run allowlisted tests in a bounded sandbox and prepare a package of the exact tested source.',{'repository':TEXT},('repository',)),
    tool('solomon_development_build_status','Read build job evidence and package availability.',{'build_id':TEXT},('build_id',)),
    tool("solomon_host_inspect","Run a fixed read-only inspection on an enrolled trusted node; omit node_id for this host.", {"node_id":TEXT,"skill":{"type":"string","enum":["os","uptime","disk_space","usb","processes","services"]}}, ("skill",)),
    tool('solomon_request_job', 'Propose a sandboxed distributed Python, Blender or OpenSCAD job for Admin approval. Returns an approval ID; does not execute.',
         {'kind':{'type':'string','enum':['python','blender','openscad']}, 'source':TEXT,'node_id':TEXT,
          'requires_gpu':{'type':'boolean'},'min_gpu_vram_gb':{'type':'number','minimum':0},'purpose':TEXT}, ('kind','source','purpose')),
    tool('solomon_execute_approved_job','Execute a previously Admin-approved exact job once. No approval authority is available to chat.',{'approval_id':TEXT},('approval_id',)),
    tool('solomon_devices','Read discovered USB/serial/Bluetooth devices and validation evidence.',{}),
    tool('solomon_device_lab_plan','Get device-specific investigation methods and limits.',{'fingerprint':TEXT},('fingerprint',)),
    tool('solomon_request_serial_exchange','Request approval for one bounded serial bench session. Empty payload only listens, but opening a port may reset equipment.',
         {'fingerprint':TEXT,'baud':{'type':'integer'},'payload_hex':TEXT,'duration_seconds':{'type':'integer','minimum':1,'maximum':10},'purpose':TEXT},('fingerprint','baud','purpose')),
    tool('solomon_execute_device_action','Execute an existing approved device action once. Cannot approve or broaden parameters.',{'action_id':TEXT},('action_id',)),
]

async def execute_skill(name: str, args: dict[str,Any], *, approvals, edge, dispatch, refresh_job=None, development=None, maintenance=None):
    if name == 'solomon_development_request_promotion':
        result=maintenance.status(str(args['build_id']))
        if result['state']!='package_ready':raise ValueError('tested package required')
        payload={'build_id':result['id'],'archive_sha256':result['digest'],'role':'controller'}
        approval=approvals.request(actor='chat-skill',action='maintenance.promote',payload=payload,risk='critical')
        return {'approval':approval,'operator_command':'sudo /apps/solomonprime/.venv/bin/python /apps/solomonprime/app/scripts/promote-build.py '+result['id']+' '+approval['id'],'installed':False}
    if name == 'solomon_development_propose':return development.propose(str(args['repository']),str(args['title']),str(args['patch']),'chat-skill')
    if name == 'solomon_development_validate':return development.validate(str(args['proposal_id']))
    if name in {'solomon_development_request_apply','solomon_development_apply'}:
        proposal=development.get(str(args['proposal_id']))
        if not proposal or proposal['state']!='validated':raise ValueError('validated proposal required')
        payload={'proposal_id':proposal['id'],'repository':proposal['repository'],'patch_sha256':proposal['patch_sha256']}
        if name=='solomon_development_request_apply':return approvals.request(actor='chat-skill',action='development.apply',payload=payload,risk='mutating')
        if not approvals.consume(str(args['approval_id']),action='development.apply',payload=payload):raise ValueError('matching unused approval required')
        return development.apply(proposal['id'],proposal['patch_sha256'])
    if name == 'solomon_development_build':
        import asyncio
        return await asyncio.to_thread(maintenance.start,str(args['repository']))
    if name == 'solomon_development_build_status':return maintenance.status(str(args['build_id']))
    if name == 'solomon_request_job':
        from .jobs import JobSubmitRequest
        payload = JobSubmitRequest(kind=args['kind'],source=args['source'],actor='chat-skill',risk='reversible',allow_network=False,
            resources={'locality_node_id':args.get('node_id',''),'requires_gpu':args.get('requires_gpu',False),
                       'min_gpu_vram_gb':args.get('min_gpu_vram_gb',0)}).model_dump()
        payload['metadata']={'purpose':str(args.get('purpose',''))[:1000]}
        approval=approvals.request(actor='chat-skill',action='skill.job',payload=payload,risk='mutating')
        return {'state':'approval_required','approval':approval,'executed':False}
    if name == 'solomon_execute_approved_job':
        row=approvals.get(str(args['approval_id']))
        if not row or row['action']!='skill.job':raise ValueError('job approval not found')
        if not approvals.consume(row['id'],action='skill.job',payload=row['payload']):raise ValueError('approval missing, expired or already consumed')
        return await dispatch(row['payload'])
    if name == 'solomon_devices':return edge.inventory()
    if name == 'solomon_device_lab_plan':return edge.lab_plan(str(args['fingerprint']))
    if name == 'solomon_request_serial_exchange':
        return edge.request_action(str(args['fingerprint']),'serial_exchange',actor='chat-skill',note=str(args['purpose']),
            parameters={k:args[k] for k in ('baud','payload_hex','duration_seconds') if k in args})
    if name == 'solomon_execute_device_action':
        import asyncio
        return await asyncio.to_thread(edge.execute_action,str(args['action_id']),actor='chat-skill',confirmed=True)
    raise ValueError('unknown executable skill')
