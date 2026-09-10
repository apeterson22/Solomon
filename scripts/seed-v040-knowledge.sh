#!/usr/bin/env bash
set -Eeuo pipefail
KEY="$(cat /etc/solomonprime/api.key)"
curl -fsS -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  --data-binary @- http://127.0.0.1:8765/v1/knowledge <<'JSON'
{
  "title":"SolomonPrime v0.4 Knowledge Workspace",
  "content":"v0.4 introduces approved-only hybrid retrieval, structured provenance, human-resolved contradiction candidates, preview-only consolidation, and governed manual Obsidian exchange. Automatic bidirectional sync, neural embedding promotion, and destructive consolidation remain approval-gated.",
  "kind":"standard",
  "state":"review",
  "domain":"solomonprime",
  "canonical_key":"solomonprime.release.knowledge-workspace",
  "source_type":"release_manifest",
  "source_uri":"docs/V0.4_KNOWLEDGE_WORKSPACE.md",
  "author":"solomon-v0.4-installer",
  "confidence":1.0,
  "importance":0.95,
  "tags":["v0.4","knowledge","rag","governance"]
}
JSON
