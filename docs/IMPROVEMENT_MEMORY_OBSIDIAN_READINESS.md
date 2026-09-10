# Improvement, RAG, Memory, Obsidian, and Dashboard Readiness

Date: 2026-09-02  
Release: SolomonPrime v0.3.2

This document is deliberately conservative. A feature is marked active only
when the shipped runtime implements it and the upgrade verifies it.

## Current state

| Area | v0.3.2 state | Evidence in the runtime |
|---|---|---|
| Tiered persistent memory | Active baseline | SQLite records use working, episodic, semantic, domain, and archive tiers. |
| Lexical RAG | Active | SQLite FTS5 search with a LIKE fallback; retrieved context is injected into agent prompts. |
| Retrieval quality scoring | Active baseline | FTS relevance, importance, confidence, recency, reuse, agent, and domain scores. |
| Deduplication | Active baseline | Exact normalized hashes and recent same-scope Jaccard near-deduplication. |
| Provenance | Partial | Each record has a source string, agent, domain, confidence, timestamps, and tags; there is no normalized citation/evidence table yet. |
| Long-term curation | Partial | Low-value archival and a Memory Curator role exist; consolidation/promotion is not automated. |
| Vector embeddings | Not implemented | No embedding model or vector index is installed or called. |
| Hybrid RAG and reranking | Not implemented | There is no vector/lexical fusion or cross-encoder/LLM reranker. |
| Contradiction/staleness handling | Not implemented | Supersession exists in the schema, but no automatic contradiction graph or stale-evidence workflow operates it. |
| Knowledge compiler | Not implemented | Conversations are captured as episodes; they are not automatically compiled into facts, SOPs, rules, or skills. |
| Obsidian integration | Not implemented | No vault, watcher, synchronizer, conflict policy, or dashboard panel ships in v0.3.2. |
| Improvement dashboard | Backend seed only | `/v1/improvement/status` exposes truthful status. A visual workspace is a later gated phase. |

The full operator-supplied plan is preserved as
`docs/SOLOMONPRIME_TED_IMPROVEMENT_PLAN.md` and is seeded into the Goal Engine
and semantic memory by the controller upgrade.

## Target knowledge architecture

The canonical record remains SolomonPrime's versioned knowledge store. An
Obsidian vault is a human-readable working projection, not an uncontrolled
second source of truth.

1. Ingestion records source, owner, timestamps, content hash, classification,
   and consent/approval state.
2. Lexical and local-vector indexes retrieve candidates independently.
3. A bounded hybrid ranker combines relevance, importance, confidence,
   recency, reuse, agent/domain scope, and provenance quality.
4. Answers retain memory IDs and source references so retrieval can be audited.
5. The Memory Curator proposes consolidation, contradiction, supersession, and
   archival changes; protected knowledge requires review.
6. Only evaluated, approved knowledge becomes a standard, rule, SOP, workflow,
   agent skill, or training candidate.

## Obsidian vault contract

Proposed controller path:

`/apps/solomonprime-data/knowledge/obsidian`

Proposed top-level folders:

- `00-Inbox` — user capture; agents may tag but not rewrite originals.
- `10-Notes` — user and shared notes.
- `20-Research` — sourced research and experiment observations.
- `30-Goals` — goal/project/task views generated from the Goal Engine.
- `40-Standards` — approved standards and specifications.
- `50-SOPs` — approved operating processes.
- `60-Rules` — approved rulesets and policy explanations.
- `70-Agent-Proposals` — agent-drafted notes awaiting human/critic review.
- `80-Agent-Knowledge` — promoted agent-readable knowledge.
- `90-Archive` — retained superseded versions.

Required frontmatter for synchronized notes:

```yaml
solomon_id: KNOW-...
type: note | research | standard | sop | rule | proposal
owner: operator | agent-name
source: ...
confidence: 0.0
status: draft | proposed | approved | superseded | archived
version: 1
content_hash: sha256:...
created: ...
updated: ...
tags: []
```

Safety rules:

- Agents never silently overwrite user-authored text.
- Agent changes to standards, SOPs, and rules are proposals until approved.
- Conflicting edits create a conflict record and preserve both versions.
- Deletion is archival by default; protected records require approval.
- The synchronizer operates without SolomonPrime secrets and has a scoped root.
- Every promotion, supersession, archive, and sync conflict is audited.

## Dashboard build order

The current dashboard should add panels in this order:

1. Improvement Plan phase/gate status from `/v1/improvement/status`.
2. RAG health: lexical/vector availability, retrieval latency, hit rate,
   citation coverage, stale results, and benchmark regressions.
3. Memory quality: tier counts, proposed promotions, duplicates,
   contradictions, stale knowledge, and archival queue.
4. Obsidian sync: last scan, pending imports/exports, conflicts, approvals, and
   vault backup state.
5. Experiment and promotion board: baseline, candidate, evidence, risk,
   approval, rollback, and release state.
6. Resource/cost/energy panel using TED telemetry.

## Promotion gates

Vector or Obsidian features must not be enabled merely because configuration
keys exist. Promotion requires:

- repeatable retrieval benchmarks against the FTS5 baseline;
- source/citation preservation tests;
- contradiction and stale-memory tests;
- vault round-trip and conflict tests;
- backup/restore and rollback tests;
- permission and secret-exposure tests;
- measured CPU, RAM, disk, and latency impact;
- human approval for the first production activation.

This keeps the Improvement Plan's governing rule intact: proposed optimization
is not production improvement until it is measured, reviewed, and reversible.
