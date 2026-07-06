from __future__ import annotations
from dataclasses import dataclass
import requests


@dataclass
class ModelEntry:
    id: str
    provider: str
    source: str            # "ollama" | "litellm" | "openrouter" | "custom"
    local: bool
    input_cost: float | None = None    # USD per token
    output_cost: float | None = None
    installed: bool = False


def ollama_vision_models(url: str, timeout: float = 2.0) -> list[ModelEntry]:
    base = url.rstrip("/")
    try:
        tags = requests.get(f"{base}/api/tags", timeout=timeout).json().get("models", [])
    except (requests.RequestException, ValueError):
        return []
    out = []
    for m in tags:
        name = m.get("name", "")
        try:
            show = requests.post(f"{base}/api/show", json={"model": name},
                                 timeout=timeout).json()
        except (requests.RequestException, ValueError):
            continue
        caps = set(show.get("capabilities") or [])
        fams = set((show.get("details") or {}).get("families") or [])
        if "vision" in caps or fams & {"clip", "mllama"}:
            out.append(ModelEntry(id=f"ollama/{name}", provider="ollama",
                                  source="ollama", local=True,
                                  input_cost=0.0, output_cost=0.0))
    return sorted(out, key=lambda e: e.id)


def litellm_vision_models() -> list[ModelEntry]:
    try:
        import litellm
        out = []
        for mid, info in litellm.model_cost.items():
            if not info.get("supports_vision"):
                continue
            if info.get("mode") not in (None, "chat"):
                continue
            out.append(ModelEntry(id=mid, provider=info.get("litellm_provider", "unknown"),
                                  source="litellm", local=False,
                                  input_cost=info.get("input_cost_per_token"),
                                  output_cost=info.get("output_cost_per_token")))
        return sorted(out, key=lambda e: e.id)
    except Exception:
        return []


def openrouter_vision_models(timeout: float = 3.0) -> list[ModelEntry]:
    try:
        data = requests.get("https://openrouter.ai/api/v1/models",
                            timeout=timeout).json().get("data", [])
    except (requests.RequestException, ValueError):
        return []
    out = []
    for m in data:
        arch = m.get("architecture") or {}
        mods = arch.get("input_modalities") or str(arch.get("modality", "")).split("+")
        if "image" not in mods:
            continue
        pr = m.get("pricing") or {}
        def _f(x):
            try:
                return float(x) or None
            except (TypeError, ValueError):
                return None
        out.append(ModelEntry(id=f"openrouter/{m['id']}", provider="openrouter",
                              source="openrouter", local=False,
                              input_cost=_f(pr.get("prompt")),
                              output_cost=_f(pr.get("completion"))))
    return sorted(out, key=lambda e: e.id)


def all_vision_models(cfg: dict, include_openrouter: bool = True) -> list[ModelEntry]:
    entries = ollama_vision_models(cfg["ollama_url"]) + litellm_vision_models()
    if include_openrouter:
        entries += openrouter_vision_models()
    seen, out = set(), []
    for e in entries:
        if e.id not in seen:
            seen.add(e.id)
            out.append(e)
    return sorted(out, key=lambda e: e.id)
