from __future__ import annotations
from pathlib import Path
from typing import Callable
from . import prompts
from .db import Store
from .model import InvalidOutput
from .tournament import run_tournaments

_QUALITY_FLAGS = {"blur-soft", "blur-extreme", "exposure-poor", "exposure-extreme"}


def _needs_second_pass(flags: list[str], p1: dict) -> bool:
    if _QUALITY_FLAGS & set(flags):
        return True
    if p1["quality_judgment"]["fatal"] == "yes" or p1["utility"]["is_accidental"] == "yes":
        return True
    if p1["utility"]["is_screenshot"] == "yes" and "screenshot-candidate" not in flags:
        return True
    if p1["utility"]["is_document"] == "yes" and "document-candidate" not in flags:
        return True
    return False


def run_stage3(source: Path, store: Store, cfg: dict, model,
               progress: Callable[[str], None] = lambda s: None,
               steer: Callable[[dict, int], dict | None] | None = None) -> dict:
    run_tournaments(source, store, cfg, model)
    summary = {"analyzed": 0, "second_passes": 0, "invalid": 0}
    skip = set()
    for g in store.groups():
        ok = [m for m in g["members"] if (store.photo(m) or {}).get("status") == "ok"]
        if g["champion"]:
            skip.update(m for m in ok if m != g["champion"])
        else:
            skip.update(ok)                          # unresolved group: verdicts decides
    todo = [p for p in store.photos(status="ok")
            if p["stage_done"] == 2 and p["verdict"] is None
            and p["rel_path"] not in skip]
    total = len(todo)
    a_prompt = prompts.render("analyze_photo", cfg)
    r_prompt = prompts.render("analyze_photo_reworded", cfg)
    a_schema, r_schema = prompts.load_schema("analyze"), prompts.load_schema("reworded")
    for i, photo in enumerate(todo, 1):
        if steer is not None:
            new_cfg = steer(cfg, i - 1)
            if new_cfg is not None:                      # boundary-applied delta (R5)
                cfg = new_cfg
                a_prompt = prompts.render("analyze_photo", cfg)
                r_prompt = prompts.render("analyze_photo_reworded", cfg)
        rel = photo["rel_path"]
        img = [Path(photo["stage2"]["work_path"])]
        try:
            p1 = model.analyze(img, a_prompt, a_schema)
            p2 = None
            if _needs_second_pass(photo["stage2"]["flags"], p1):
                p2 = model.analyze(img, r_prompt, r_schema)
                summary["second_passes"] += 1
            store.update(rel, stage3={"pass1": p1, "pass2": p2,
                                      "prompt_versions": prompts.versions()},
                         stage_done=3)
            summary["analyzed"] += 1
        except InvalidOutput:
            store.update(rel, stage3={"error": "model-output-invalid"}, stage_done=3)
            summary["invalid"] += 1
        progress(f"{i}/{total}")
    return summary
