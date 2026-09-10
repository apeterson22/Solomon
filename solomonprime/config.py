from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    role: str = "node"  # controller | node
    node_name: str = ""
    node_id: str = ""
    bind_host: str = "0.0.0.0"
    port: int = 8765
    state_dir: str = "/var/lib/solomonprime"
    config_dir: str = "/etc/solomonprime"
    cluster_key_file: str = "/etc/solomonprime/cluster.key"
    public_api_key_file: str = "/etc/solomonprime/api.key"
    controller_candidates: list[str] = field(default_factory=list)
    heartbeat_interval: int = 15
    discovery_interval: int = 25
    stale_after: int = 90
    mdns: bool = True
    tailscale_discovery: bool = True
    static_peers: list[str] = field(default_factory=list)
    local_subnets: list[str] = field(default_factory=list)
    llm_endpoint: str = ""
    llm_api_key_file: str = ""
    llm_model_hint: str = ""
    ollama_endpoint: str = "http://127.0.0.1:11434"
    llm_advisor: bool = True
    cloud_routing_enabled: bool = True
    cloud_provider_config: str = "/etc/solomonprime/cloud-providers.yaml"
    cloud_quota_ledger: str = "/var/lib/solomonprime/cloud-quota.db"
    cloud_training_dir: str = "/var/lib/solomonprime/training"
    cloud_complexity_threshold: float = 0.72
    cloud_quota_margin: float = 0.90
    cloud_max_calls_per_request: int = 1
    cloud_capture_training: bool = True
    cloud_sensitive_policy: str = "deny"
    energy_config: str = "/var/lib/solomonprime/energy.yaml"
    energy_ledger: str = "/var/lib/solomonprime/energy.db"
    energy_sample_interval: int = 30
    edge_device_catalog: str = "/var/lib/solomonprime/edge-devices.yaml"
    edge_device_state: str = "/var/lib/solomonprime/edge-devices.db"
    edge_discovery_enabled: bool = True
    edge_usb_scan_interval: int = 5
    edge_bluetooth_scan_interval: int = 60
    edge_bluetooth_scan_seconds: int = 8
    edge_bluetooth_nearby_rssi: int = -70
    rf_monitor_enabled: bool = True
    rf_monitor_interval: int = 300
    rf_receive_window: int = 10
    rf_ledger: str = "/var/lib/solomonprime/rf-observations.db"
    admin_docs_path: str = "/apps/solomonprime/app/config/admin-docs.yaml"
    voice_config: str = "/var/lib/solomonprime/voice.yaml"
    voice_ledger: str = "/var/lib/solomonprime/voice-approvals.db"
    calendar_config: str = "/var/lib/solomonprime/calendars.yaml"
    calendar_ledger: str = "/var/lib/solomonprime/calendars.db"
    self_development_config: str = "/var/lib/solomonprime/self-development.yaml"
    self_development_ledger: str = "/var/lib/solomonprime/self-development.db"
    mobile_access_ledger: str = "/var/lib/solomonprime/mobile-access.db"
    goals_db: str = "/var/lib/solomonprime/goals.db"
    experiments_db: str = "/var/lib/solomonprime/experiment-ledger.db"
    experiment_artifact_dir: str = "/var/lib/solomonprime/experiments"
    jobs_db: str = "/var/lib/solomonprime/jobs.db"
    job_workspace_dir: str = "/apps/solomonprime-jobs"
    # job_runner is retained as the configuration key for compatibility, but
    # points to the unprivileged broker client from v0.3.2 onward.
    job_runner: str = "/usr/local/libexec/solomon-job-broker-client"
    job_broker_socket: str = "/run/solomonprime/job-broker.sock"
    job_default_max_runtime: int = 900
    auto_rebalance: bool = True
    auto_apply_safe_profiles: bool = True
    auto_memory: bool = True
    memory_retrieval_limit: int = 6
    # Legacy memory remains intact; v0.4 adds a separate governed knowledge ledger.
    memory_backend: str = "sqlite_fts5"
    memory_vector_enabled: bool = False
    memory_consolidation_enabled: bool = False
    knowledge_db: str = "/var/lib/solomonprime/knowledge.db"
    knowledge_vector_backend: str = "feature_hash_v1"
    knowledge_hybrid_enabled: bool = True
    improvement_plan_path: str = "/apps/solomonprime/app/docs/SOLOMONPRIME_TED_IMPROVEMENT_PLAN.md"
    obsidian_enabled: bool = False
    obsidian_vault_path: str = "/var/lib/solomonprime/obsidian"
    obsidian_sync_mode: str = "manual"
    workspace_roots: list[str] = field(default_factory=lambda: ["/apps/solomonprime", "/data", "/archive"])
    enabled_agents: list[str] = field(default_factory=lambda: [
        "solomon-core", "storage-steward", "memory-curator", "critic-evaluator",
        "home-ops", "farm-ops", "research-simulation", "infrastructure",
    ])

    @property
    def state_path(self) -> Path:
        p = Path(self.state_dir); p.mkdir(parents=True, exist_ok=True); return p

    @property
    def config_path(self) -> Path:
        return Path(self.config_dir)


def load_settings(path: str | None = None) -> Settings:
    path = path or os.getenv("SOLOMON_CONFIG", "/etc/solomonprime/config.yaml")
    raw: dict[str, Any] = {}
    p = Path(path)
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    s = Settings()
    for k, v in raw.items():
        if hasattr(s, k):
            setattr(s, k, v)
    # All default state paths follow an explicitly configured state root. This
    # also allows isolated test/build instances without touching live databases.
    if "state_dir" in raw:
        for name, value in vars(s).items():
            if name not in raw and isinstance(value,str) and value.startswith("/var/lib/solomonprime/"):
                setattr(s,name,str(Path(s.state_dir)/value.removeprefix("/var/lib/solomonprime/")))
    if "energy_ledger" not in raw:
        s.energy_ledger = str(Path(s.state_dir) / "energy.db")
    s.role = os.getenv("SOLOMON_ROLE", s.role)
    s.node_name = os.getenv("SOLOMON_NODE_NAME", s.node_name)
    s.node_id = os.getenv("SOLOMON_NODE_ID", s.node_id)
    if os.getenv("SOLOMON_CONTROLLER_URLS"):
        s.controller_candidates = [x.strip() for x in os.getenv("SOLOMON_CONTROLLER_URLS", "").split(";") if x.strip()]
    s.llm_endpoint = os.getenv("SOLOMON_LLM_ENDPOINT", s.llm_endpoint)
    s.llm_api_key_file = os.getenv("SOLOMON_LLM_API_KEY_FILE", s.llm_api_key_file)
    s.ollama_endpoint = os.getenv("SOLOMON_OLLAMA_URL", s.ollama_endpoint)
    s.cloud_routing_enabled = _bool_env("SOLOMON_CLOUD_ROUTING", s.cloud_routing_enabled)
    s.cloud_capture_training = _bool_env("SOLOMON_CLOUD_CAPTURE_TRAINING", s.cloud_capture_training)
    s.edge_discovery_enabled = _bool_env("SOLOMON_EDGE_DISCOVERY", s.edge_discovery_enabled)
    s.rf_monitor_enabled = _bool_env("SOLOMON_RF_MONITOR", s.rf_monitor_enabled)
    s.auto_rebalance = _bool_env("SOLOMON_AUTO_REBALANCE", s.auto_rebalance)
    s.auto_apply_safe_profiles = _bool_env("SOLOMON_AUTO_APPLY_SAFE", s.auto_apply_safe_profiles)
    s.auto_memory = _bool_env("SOLOMON_AUTO_MEMORY", s.auto_memory)
    s.state_path
    return s
