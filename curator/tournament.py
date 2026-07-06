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

        # Close-call critique: if budget available and top-2 are close, one extra round
        if budget is not None and len(ok) >= 2:
            runner_up = max(
                (m for m in ok if m != champ),
                key=lambda m: sharpness(photos[m]["stage2"]),
                default=None,
            )
            if runner_up and _is_close_call(
                sharpness(photos[champ]["stage2"]),
                sharpness(photos[runner_up]["stage2"]),
            ) and budget.charge():
                c_imgs = [Path(photos[champ]["stage2"]["work_path"]),
                          Path(photos[runner_up]["stage2"]["work_path"])]
                c_prompt = prompts.render("tournament", cfg, COUNT=2, MAXIDX=1)
                try:
                    c_out = model.analyze(c_imgs, c_prompt, critique_schema)
                    if int(c_out.get("winner", 0)) == 1:
                        champ = runner_up
                        reasons.append("critique: preferred runner-up")
                except Exception:
                    pass

        best_classical = max(sharpness(photos[m]["stage2"]) for m in ok)
        agree = sharpness(photos[champ]["stage2"]) >= \
            cfg["tournament"]["classical_agree_ratio"] * best_classical
        store.set_group(g["id"], champion=champ,
                        info={"reason": " | ".join(reasons) or "single round",
                              "classical_agree": bool(agree)})
        summary["decided"] += 1
    return summary
