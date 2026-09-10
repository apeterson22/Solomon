from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import httpx


def _size_gib(size: int) -> float:
    return round(size / (1024 ** 3), 2)


class LocalModelCatalog:
    """Read-only inventory of models already present on the controller."""

    def __init__(self, active_hint: str, ollama_endpoint: str = ""):
        self.active_hint = Path(active_hint) if active_hint else Path("/var/lib/solomonprime/models/primary.gguf")
        self.ollama_endpoint = (ollama_endpoint or os.getenv("SOLOMON_OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")

    def gguf(self) -> list[dict[str, Any]]:
        root = self.active_hint.parent
        try:
            active = self.active_hint.resolve(strict=True)
        except OSError:
            active = self.active_hint
        rows = []
        try:
            files = sorted(root.rglob("*.gguf"))[:500]
        except OSError:
            files = []
        for path in files:
            try:
                stat = path.stat(); resolved = path.resolve()
            except OSError:
                continue
            rows.append({
                "name": path.name,
                "path": str(path),
                "resolved_path": str(resolved),
                "size_bytes": stat.st_size,
                "size_gib": _size_gib(stat.st_size),
                "active": resolved == active,
                "format": "gguf",
            })
        return rows

    def ollama(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Discover through the daemon API, independent of the caller's CLI/PATH."""
        endpoint=self.ollama_endpoint
        try:
            response=httpx.get(endpoint+"/api/tags",timeout=5)
            response.raise_for_status(); payload=response.json()
        except Exception as exc:
            return [],{"state":"unreachable","endpoint":endpoint,"reason":f"{type(exc).__name__}: {str(exc)[:180]}","how_to_fix":"Start Ollama or configure its reachable daemon URL."}
        rows = []
        for item in payload.get("models") or []:
            name=str(item.get("name") or item.get("model") or "").strip()
            if not name:continue
            cloud=name.endswith(":cloud") or name.endswith("-cloud")
            size=int(item.get("size") or 0)
            rows.append({"name":name,"id":str(item.get("digest") or name),"format":"ollama","active":False,
                         "location":"cloud" if cloud else "local","size_bytes":size,"size_gib":_size_gib(size),
                         "modified_at":item.get("modified_at")})
        local=sum(1 for x in rows if x["location"]=="local");cloud=sum(1 for x in rows if x["location"]=="cloud")
        return rows,{"state":"ready" if rows else "empty","endpoint":endpoint,"models":len(rows),"local":local,"cloud":cloud,
                     "reason":"HTTP inventory succeeded." if rows else "No models are pulled into this Ollama daemon."}

    def inventory(self) -> dict[str, Any]:
        gguf = self.gguf(); ollama, runtime = self.ollama()
        active = next((x for x in gguf if x["active"]), None)
        return {
            "active": active,
            "gguf": gguf,
            "ollama": ollama,
            "ollama_runtime": runtime,
            "counts": {"gguf": len(gguf), "ollama": len(ollama), "total": len(gguf) + len(ollama)},
            "candidates": [
                {"id": "qwen35-27b-q4", "name": "Qwen3.5 27B Q4",
                 "fit": "quality candidate; benchmark against the active model",
                 "source": "unsloth/Qwen3.5-27B-GGUF", "license":"Apache-2.0 family; verify artifact card", "license_gate":"review_required"},
                {"id": "gemma3-12b-q4", "name": "Gemma 3 12B IT QAT Q4_0",
                 "fit": "smaller general assistant candidate",
                 "source": "google/gemma-3-12b-it-qat-q4_0-gguf", "license":"Gemma Terms", "license_gate":"free_use_review_required"},
                {"id": "ministral3-14b-q4", "name": "Ministral 3 14B Instruct Q4_K_M",
                 "fit": "efficient instruction/coding candidate",
                 "source": "mistralai/Ministral-3-14B-Instruct-2512-GGUF", "license":"Apache-2.0 family; verify artifact card", "license_gate":"review_required"},
                {"id": "ollama-gpt-oss-20b", "name": "gpt-oss 20B (Ollama)",
                 "fit": "local reasoning and agentic review candidate; benchmark before promotion",
                 "source": "ollama.com/library/gpt-oss:20b", "license":"Apache-2.0", "license_gate":"allowed"},
                {"id":"ollama-qwen3-14b","name":"Qwen3 14B (Ollama)",
                 "fit":"local general/tool-use candidate; benchmark on both GPUs",
                 "source":"ollama.com/library/qwen3:14b","license":"Apache-2.0", "license_gate":"allowed"},
                {"id":"ollama-gpt-oss-120b-cloud","name":"gpt-oss 120B Cloud (Ollama)",
                 "fit":"complex-task cloud candidate; included/free allowance only",
                 "source":"ollama.com/library/gpt-oss:120b-cloud","license":"Apache-2.0", "license_gate":"allowed","location":"cloud"},
            ],
            "candidate_command": "sudo /apps/solomonprime/app/scripts/model-lab.sh download <candidate-id>",
            "selection_policy": "inventory_only; activation requires operator-controlled service restart",
        }
