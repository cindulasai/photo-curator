from __future__ import annotations
from pathlib import Path
from . import prompts
from .db import Store
from .metrics import sharpness
from .model import InvalidOutput, ModelError


def _batches(items: list, size: int = 4):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _is_close_call(w: float, r: float, threshold: float = 0.10) -> bool:
    """True if sharpness scores are within *threshold* of each other."""
    if w <= 0:
        return False
    return abs(w - r) / max(w, 0.001) < threshold


def run_tournaments(source: Path, store: Store, cfg: dict, model,
                    budget=None) -> dict:
    summary = {"decided": 0, "review": 0}
    schema = prompts.load_schema("tournament")
    critique_schema = prompts.load_schema("critique")
    photos = {p["rel_path"]: p for p in store.photos()}
    for g in store.groups():
        if g["champion"] or (g["info"] or {}).get("unsure") or (g["info"] or {}).get("error"):
            continue                                        # resume-safe
        ok = [m for m in g["members"] if photos[m]["status"] == "ok"]
        if not ok:
            continue
        if len(ok) == 1:
            store.set_group(g["id"], champion=ok[0],
                            info={"reason": "only survivor", "classical_agree": True})
            summary["decided"] += 1
            continue

        # Close-call critique: if the top-2 candidates are within 10% sharpness,
        # fire one extra LLM round (budget permitting) before the main tournament.
        critique_override: str | None = None
        if len(ok) >= 2 and budget is not None:
            sorted_by_sharp = sorted(
                ok, key=lambda m: sharpness(photos[m]["stage2"]), reverse=True)
            runner_up = sorted_by_sharp[1]
            w_sharp = sharpness(photos[sorted_by_sharp[0]]["stage2"])
            r_sharp = sharpness(photos[runner_up]["stage2"])
            if _is_close_call(w_sharp, r_sharp) and budget.charge():
                imgs = [Path(photos[sorted_by_sharp[0]]["stage2"]["work_path"]),
                        Path(photos[runner_up]["stage2"]["work_path"])]
                crit_prompt = prompts.render("tournament", cfg, COUNT=2, MAXIDX=1)
                try:
                    out = model.analyze(imgs, crit_prompt, critique_schema)
                    idx = int(out.get("winner", 0))
                    critique_override = runner_up if idx == 1 else sorted_by_sharp[0]
                except Exception:
                    pass  # critique failed — proceed with regular tournament

        contenders, reasons, failed = sorted(ok), [], False
        while len(contenders) > 1 and not failed:
            winners = []
            for batch in _batches(contenders):
                if len(batch) == 1:
                    winners.append(batch[0])
                    continue
                imgs = [Path(photos[m]["stage2"]["work_path"]) for m in batch]
                prompt = prompts.render("tournament", cfg,
                                        COUNT=len(batch), MAXIDX=len(batch) - 1)
                try:
                    out = model.analyze(imgs, prompt, schema)
                except (ModelError, InvalidOutput):
                    store.set_group(g["id"], info={"error": "model-output-invalid"})
                    summary["review"] += 1
                    failed = True
                    break
                if out["unsure"] or out["best_index"] >= len(batch):
                    store.set_group(g["id"], info={"unsure": True,
                                                   "reason": out.get("reason", "")})
                    summary["review"] += 1
                    failed = True
                    break
                winners.append(batch[out["best_index"]])
                reasons.append(out["reason"])
            contenders = sorted(winners)
        if failed:
            continue
        champ = contenders[0]
        # If a close-call critique preferred the other photo, honour it.
        if critique_override and critique_override != champ and critique_override in ok:
            champ = critique_override
        best_classical = max(sharpness(photos[m]["stage2"]) for m in ok)
        agree = sharpness(photos[champ]["stage2"]) >= \
            cfg["tournament"]["classical_agree_ratio"] * best_classical
        store.set_group(g["id"], champion=champ,
                        info={"reason": " | ".join(reasons) or "single round",
                              "classical_agree": bool(agree)})
        summary["decided"] += 1
    return summary
