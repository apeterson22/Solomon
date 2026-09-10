"""Local admission gate for permanent and opportunistic workers."""
import json
import time
from pathlib import Path


def read_availability(path='/etc/solomonprime/availability.json'):
    p=Path(path)
    if not p.exists():return {'accepting_jobs':True,'mode':'permanent'}
    try:
        data=json.loads(p.read_text())
        expires=float(data['expires'])
        allowed=data.get('mode')=='available' and time.time() < expires <= time.time()+120
        return {'accepting_jobs':allowed,'mode':data.get('mode','disabled'),'expires':expires}
    except (ValueError,KeyError,TypeError,OSError):
        return {'accepting_jobs':False,'mode':'invalid_gate'}
