#!/usr/bin/env python3
"""Discover local Ollama models and enroll this node's inference capability."""
import json
import os
from pathlib import Path
import urllib.request
import yaml

if os.geteuid()!=0:raise SystemExit('Run with sudo')
p=Path('/etc/solomonprime/config.yaml')
config=yaml.safe_load(p.read_text()) or {}
if config.get('llm_endpoint'):
    raise SystemExit('Existing inference configuration preserved. Use Admin/local configuration to change it.')
with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=5) as response:
    models=json.load(response).get('models',[])
names=[m['name'] for m in models if isinstance(m.get('name'),str) and not m['name'].endswith((':cloud','-cloud'))]
if not names:raise SystemExit('No local Ollama models found. Install an appropriate local model first.')
for i,name in enumerate(names,1):print(f'{i}: {name}')
choice=int(input('Select this worker default model number: '))-1
if not 0<=choice<len(names):raise SystemExit('Invalid selection')
import subprocess
endpoint = subprocess.check_output([str(Path(__file__).with_name('detect-ollama-endpoint.sh'))], text=True).strip()
config.update(llm_endpoint=endpoint.rstrip('/')+'/v1',llm_model_hint=names[choice],ollama_endpoint=endpoint.rstrip('/'))
tmp=p.with_suffix('.tmp');tmp.write_text(yaml.safe_dump(config,sort_keys=False));tmp.chmod(0o640)
meta=p.stat();os.chown(tmp,meta.st_uid,meta.st_gid);os.replace(tmp,p)
print('Node inference configured. Restart solomonprime to publish its capability.')
