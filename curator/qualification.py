from __future__ import annotations
import json, time
from importlib.resources import files
from pathlib import Path
from . import prompts
from .model import InvalidOutput, ModelError

_TTL_S = 30 * 24 * 3600


def _dig(d, dotted: str):
    for part in dotted.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d


def run_gate(model, cfg: dict, cache_dir: Path | None = None,
             force: bool = False) -> tuple[bool, list[dict]]:
    cache_dir = Path(cache_dir or Path.home() / ".photo-curator")
    cache_file = cache_dir / "qualification.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    hit = cache.get(model.name())
    if hit and not force and time.time() - hit["when"] < _TTL_S:
        return hit["passed"], hit["results"]

    cal = files("curator").joinpath("data/calibration")
    answers = json.loads(cal.joinpath("answers.json").read_text())
    prompt = prompts.render("analyze_photo", cfg)
    schema = prompts.load_schema("analyze")
    results = []
    for item in answers:
        entry = {"file": item["file"], "check": item["check"],
                 "expect": item["expect"], "got": None, "ok": False}
        try:
            out = model.analyze([Path(str(cal.joinpath(item["file"])))], prompt, schema)
            entry["got"] = _dig(out, item["check"])
            entry["ok"] = entry["got"] == item["expect"]
        except (InvalidOutput, ModelError) as exc:
            entry["got"] = f"ERROR: {exc}"
        results.append(entry)
    passed = all(r["got"] is not None and not str(r["got"]).startswith("ERROR")
                 for r in results) and sum(r["ok"] for r in results) >= 9
    cache[model.name()] = {"passed": passed, "when": time.time(), "results": results}
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, indent=2))
    return passed, results
