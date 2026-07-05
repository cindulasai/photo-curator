from __future__ import annotations
import json
from pathlib import Path
from . import __version__, prompts
from .config import config_hash
from .db import Store


def write_manifest(store: Store, cfg: dict, out_dir: Path, model_name: str,
                   timings: dict, source_hash: str) -> Path:
    photos = []
    for p in store.photos():
        classical = dict(p["stage2"] or {})
        classical.pop("work_path", None)
        vi = p["verdict_info"] or {}
        photos.append({"rel_path": p["rel_path"], "sha256": p["sha256"],
                       "kind": p["kind"], "status": p["status"],
                       "verdict": p["verdict"], "ts": p["ts"],
                       "ts_source": p["ts_source"],
                       "bucket": vi.get("bucket"), "tags": vi.get("tags", []),
                       "classical": classical, "llm": p["stage3"],
                       "verdict_info": vi})
    doc = {"run": {"skill_version": __version__, "model": model_name,
                   "config_hash": config_hash(cfg), "source_hash": source_hash,
                   "prompt_versions": prompts.versions()},
           "timings": timings,
           "photos": photos,
           "groups": store.groups(),
           "events": store.events()}
    path = Path(out_dir) / "manifest.json"
    path.write_text(json.dumps(doc, indent=1, sort_keys=True))
    return path
