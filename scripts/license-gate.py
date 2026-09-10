#!/usr/bin/env python3
import sys
from pathlib import Path
import yaml

policy=Path(__file__).resolve().parents[1]/"config/license-policy.yaml"
data=yaml.safe_load(policy.read_text()) or {}
name=sys.argv[1] if len(sys.argv)>1 else ""
aliases={"ollama-gpt-oss-20b":"gpt-oss:20b","ollama-qwen3-14b":"qwen3:14b","ollama-gpt-oss-120b-cloud":"gpt-oss:120b-cloud"}
record=(data.get("models") or {}).get(aliases.get(name,name))
if not record or record.get("allowed") is not True:
    print(f"DENY: {name} has no approved free-use license record",file=sys.stderr);raise SystemExit(3)
print(f"ALLOW: {name} ({record.get('license')})")
