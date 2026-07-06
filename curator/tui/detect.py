from __future__ import annotations
import json, os
from dataclasses import dataclass, field
from pathlib import Path
import requests
from ..providers.catalog import ModelEntry, ollama_vision_models
from ..providers.keystore import ENV_MAP


@dataclass
class Detection:
    ollama_up: bool
    local_models: list[ModelEntry]
    env_keys: list[str]
    prior: dict | None


def detect(cfg: dict, home: Path | None = None, timeout: float = 2.0) -> Detection:
    local = ollama_vision_models(cfg["ollama_url"], timeout)
    up = bool(local)
    if not up:
        try:
            requests.get(cfg["ollama_url"].rstrip("/") + "/api/version", timeout=timeout)
            up = True
        except requests.RequestException:
            up = False
    env_keys = [p for p, var in ENV_MAP.items() if os.environ.get(var)]
    home = Path(home) if home else Path.home() / ".photo-curator"
    prior_f = home / "last_run.json"
    prior = json.loads(prior_f.read_text()) if prior_f.exists() else None
    return Detection(up, local, env_keys, prior)
