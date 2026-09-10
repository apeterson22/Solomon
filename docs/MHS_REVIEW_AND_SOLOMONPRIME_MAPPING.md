# MHS review and SolomonPrime mapping

Source review date: 2026-09-01

Primary sources:
- Anthropic, "Previewing the Model Hardware Standard" (2026-08-27)
- Model Hardware Standard research preview site
- MarkTechPost summary (2026-08-29)

## What is confirmed

MHS is currently a limited research preview, not yet a generally available open-source specification. Anthropic describes it as a model-agnostic shared specification for agents to discover and operate programmable physical devices. The announcement describes standardized drivers, simple read/write-style primitives, device discovery, device metadata/reference files including safety limits, and access through MCP, CLI, and code APIs.

The most important architectural lesson for SolomonPrime is that physical safety boundaries belong in deterministic device drivers and policy, not only in prompts. Agent reasoning should select high-level actions inside an enforced hardware envelope.

Anthropic also describes a pattern where an agent explores/optimizes a physical process, then packages the learned procedure into deterministic code so the AI does not need to reason at every high-frequency step. This maps directly to SolomonPrime's Goal Engine + Experiment Ledger + Critic + deterministic job artifacts.

The preview reports early integrations with Raspberry Pi products and Hugging Face LeRobot. This is relevant to SolomonPrime's planned Pi edge, camera, sensor, and robotics nodes.

## SolomonPrime adoption policy

Until the public MHS specification is released or research-preview access is granted, SolomonPrime should implement an **MHS-inspired compatibility layer**, not claim official MHS compliance.

Adopt now:
1. Standard device manifest: identity, capabilities, states, procedures, telemetry, safety envelope, approvals, provenance.
2. Minimal primitives: discover, describe, read, write/request-action, execute-procedure, stop/emergency-stop, health.
3. Driver-level hard safety limits that an LLM cannot override.
4. Model-agnostic access adapters: internal API first; MCP adapter when useful; CLI for operators.
5. Simulator/digital-twin mode required before physical actuation for new drivers when practical.
6. Convert validated repetitive agent procedures into inspectable deterministic scripts.
7. Every physical write produces an audit event and is linked to a goal/experiment/job.
8. Capability discovery integrates with SolomonPrime node/hardware discovery but physical devices remain separately trusted identities.

Do not adopt yet:
- Any guessed wire format or schema presented as official MHS.
- Autonomous physical mutation without device-enforced limits and approval policy.
- Direct cloud-model access to physical devices; cloud providers remain advisory teachers unless explicitly approved.

## Side-project tracks

- MHS compatibility shim and device manifest schema.
- Raspberry Pi Camera / sensor edge driver lab.
- Farm device drivers: environmental sensors, pumps/valves, irrigation, gates, feeders, power monitors.
- Home device drivers: cameras, environmental sensors, energy monitoring, non-critical automation.
- Robotics/LeRobot compatibility research.
- Digital twin / simulation harness for validating driver procedures before actuation.
