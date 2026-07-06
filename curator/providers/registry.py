from __future__ import annotations
import dataclasses
from importlib.resources import files
from pathlib import Path
import yaml
from .catalog import ModelEntry

AVG_TOKENS_PER_PHOTO = (900, 350)   # measured input/output average per analyze call


def load_registry(user_path: Path | None = None) -> list[dict]:
    shipped = yaml.safe_load(
        files("curator").joinpath("providers/registry.yaml").read_text())["recommended"]
    if user_path is None:
        user_path = Path.home() / ".photo-curator" / "registry.yaml"
    if Path(user_path).exists():
        user = (yaml.safe_load(Path(user_path).read_text()) or {}).get("recommended", [])
        user_ids = {e["id"] for e in user}
        return user + [e for e in shipped if e["id"] not in user_ids]
    return shipped


def est_cost_per_1000(entry: ModelEntry) -> float | None:
    if entry.input_cost is None or entry.output_cost is None:
        return None
    i, o = AVG_TOKENS_PER_PHOTO
    return round((entry.input_cost * i + entry.output_cost * o) * 1000, 2)


def tiered(catalog: list[ModelEntry], registry: list[dict]
           ) -> tuple[list[ModelEntry], list[ModelEntry]]:
    by_id = {e.id: e for e in catalog}
    rec: list[ModelEntry] = []
    for r in registry:
        if r["id"] in by_id:
            entry = by_id[r["id"]]
            # Models present in the catalog are available/installed
            if not entry.installed:
                entry = dataclasses.replace(entry, installed=True)
            rec.append(entry)
        elif r["id"].startswith("ollama/"):   # pullable but not installed
            rec.append(ModelEntry(id=r["id"], provider="ollama", source="ollama",
                                  local=True, input_cost=0.0, output_cost=0.0,
                                  installed=False))
        # cloud registry entries missing from the catalog are dropped (stale id)
    rec_ids = {e.id for e in rec}
    rest = [e for e in catalog if e.id not in rec_ids]
    return rec, rest
