# SolomonPrime Spatial / God's Eye View Integration Plan

Status: **post-v1 capability track; reference integration, not a hard dependency**.

The external `bilawalsidhu/gods-eye-view` project is MIT licensed and provides a
browser-based 3D globe with modular public-data layers (aircraft, ships,
satellites, earthquakes, cameras, traffic, launches), scene/entity context,
tracking/camera verbs, annotations, sensor-style rendering, and voice-agent
control. SolomonPrime should reuse or adapt useful open-source patterns while
keeping its own local-first orchestration, governance, memory, and approval
boundaries.

## Target architecture

```text
Open WebUI / SolomonPrime Admin / Spatial UI
                 |
          SolomonPrime API
                 |
      Spatial Capability Broker
       /         |          \
Public feeds   Farm/home    Fleet/node telemetry
(ADSB/AIS/etc) sensors      + cameras/devices
       \         |          /
        Normalized Geo Events
                 |
       local cache + provenance
                 |
  map/3D client + agent tools
```

## First capability slice

- Add `/v1/spatial/context`, `/v1/spatial/entities`, and `/v1/spatial/layers`.
- Normalize geospatial entities into a shared envelope with source, timestamp,
  confidence, position/altitude, velocity/heading, tags, and provenance.
- Expose read-only agent tools first: `spatial_search`, `spatial_nearby`,
  `spatial_track`, `spatial_scene_context`, `spatial_measure`, and
  `spatial_annotate`.
- Bridge the current SolomonPrime fleet, edge-device inventory, RF observations,
  farm sensors, and approved cameras into the same spatial model.
- Keep external public-data feeds independently toggleable and cache-aware.
- Do not expose private home/farm coordinates to external providers by default.
- Preserve provenance for every external/public observation and annotation.

## UI direction

The SolomonPrime Admin workspace should grow a **Spatial** panel with:
- 2D fallback + Cesium-capable 3D globe;
- selectable public and private/local layers;
- fleet/node status overlay;
- farm/home sensors and device health;
- cameras with explicit privacy/authorization state;
- RF observations and nearby-device candidates;
- tracked target card with live telemetry and provenance;
- timeline/replay mode backed by local storage;
- voice/chat action handoff through SolomonPrime rather than a cloud-only agent.

Open WebUI remains the conversational front door; the spatial panel is a
specialized visualization surface that can be opened from a chat/tool result.

## Local AI integration

Replace the external project's OpenAI-only voice requirement with a provider
adapter that targets SolomonPrime's OpenAI-compatible `/v1` endpoint. This lets
local llama.cpp/Ollama models perform scene questions and tool planning, with
cloud providers optional and policy-gated. Visual grounding should use local
vision models when available and fall back explicitly rather than hallucinating.

## Safety / privacy boundaries

- Read-only public situational awareness is the default.
- Local cameras/devices require SolomonPrime trust and permissions.
- Physical-device actions continue through deterministic approval/interlock
  layers; spatial visualization never bypasses the device broker.
- Sensitive local coordinates are redacted from cloud prompts unless approved.
- No face recognition or person-identification capability is required for this
  integration.

## Implementation phases

1. **Adapter spike:** run the upstream UI locally in an isolated development
   workspace and route its agent endpoint to a SolomonPrime compatibility shim.
2. **Spatial API:** implement normalized entity/layer/context contracts and tests.
3. **Local layers:** fleet, edge devices, RF, farm/home sensors, approved cameras.
4. **Public layers:** aircraft, ships, satellites, earthquakes, weather/public
   cameras with explicit provider provenance and rate limits.
5. **UI merge:** add Spatial workspace/navigation to SolomonPrime Admin and
   deep-links from Open WebUI.
6. **Agent tools:** scene Q&A, tracking, measurement, annotations, routes, and
   timeline queries using local models first.
7. **Validation:** offline/degraded mode, privacy tests, replay/provenance tests,
   performance budgets, and permission-bound device/camera tests.

No upstream God's Eye View source is vendored into RC4. This document begins the
post-v1 integration track without adding a new runtime dependency to the stable
release candidate.
