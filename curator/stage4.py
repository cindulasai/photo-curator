from __future__ import annotations
import math
import statistics
from pathlib import Path
from . import prompts
from .db import Store
from .events import cluster_events
from .grouping import hamming
from .model import InvalidOutput, ModelError
from .verdicts import resolve_all

_UTILITY = {"screenshots", "documents-receipts", "whiteboards-notes", "products-shopping"}


def _uniqueness(phash: int, sample: list[int], novelty: int) -> int:
    dists = [hamming(phash, s) for s in sample if s != phash]
    if not dists:
        return novelty
    med = statistics.median(dists)
    scaled = 4 if med >= 28 else 3 if med >= 24 else 2 if med >= 20 else 1 if med >= 16 else 0
    return round((scaled + novelty) / 2)


def _select(cands: list[dict], cfg: dict, target: int, excluded: set) -> list[dict]:
    tp = cfg["top_picks"]
    picked, per_event, per_bucket = [], {}, {}
    bucket_cap = math.ceil(tp["bucket_share_max"] * target)
    for c in sorted(cands, key=lambda c: (-c["composite"], c["rel_path"])):
        if c["rel_path"] in excluded or len(picked) >= target:
            continue
        ev, bk = c["event"], c["bucket"]
        if per_event.get(ev, 0) >= tp["max_per_event"]:
            continue
        near = sum(1 for p in picked if abs(p["ts"] - c["ts"]) <= tp["burst_window_s"])
        if near >= tp["burst_window_max"]:
            continue
        if target >= 8 and per_bucket.get(bk, 0) >= bucket_cap:
            continue
        picked.append(c)
        per_event[ev] = per_event.get(ev, 0) + 1
        per_bucket[bk] = per_bucket.get(bk, 0) + 1
    return picked


def run_stage4(source: Path, store: Store, cfg: dict, model, budget=None) -> dict:
    resolve_all(store, cfg)
    keeps = store.photos(verdict="keep")

    store.clear_events()
    event_of = {}
    evs = cluster_events(keeps, cfg)
    for e in evs:
        store.add_event(e["name"], e["start_ts"], e["end_ts"], e["significance"],
                        e["members"])
        for m in e["members"]:
            event_of[m] = (e["name"], e["significance"])

    all_ok = [p for p in store.photos(status="ok") if p.get("stage2")]
    step = max(1, len(all_ok) // 200)
    sample = [p["stage2"]["phash"] for p in all_ok[::step]]

    w = cfg["rubric"]
    cands = []
    for p in keeps:
        vi = p["verdict_info"]
        if vi["bucket"] in _UTILITY or not vi.get("rubric"):
            continue
        ev_name, ev_sig = event_of.get(p["rel_path"], ("", 0))
        r = vi["rubric"]
        uniq = _uniqueness(p["stage2"]["phash"], sample, r["novelty"])
        comp = (w["emotional"] * r["emotional"] +
                w["people_engagement"] * r["people_engagement"] +
                w["event_significance"] * ev_sig +
                w["composition_light"] * r["composition_light"] +
                w["uniqueness"] * uniq +
                w["scene_appeal"] * r["scene_appeal"])
        vi["scores"] = {"composite": round(comp, 3), "uniqueness": uniq,
                        "event_significance": ev_sig}
        vi["event"] = ev_name
        store.update(p["rel_path"], verdict_info=vi)
        cands.append({"rel_path": p["rel_path"], "composite": comp, "ts": p["ts"],
                      "bucket": vi["bucket"], "event": ev_name,
                      "work_path": p["stage2"]["work_path"], "vi": vi})

    tp = cfg["top_picks"]
    target = (max(20, round(0.02 * len(keeps))) if tp["target"] == "auto"
              else int(tp["target"]))
    target = min(target, tp["cap"], len(cands))

    schema = prompts.load_schema("verification")
    excluded: set[str] = set()
    verified: list[dict] = []
    flags_total = 0
    for _round in range(3):
        picked = _select(cands, cfg, target, excluded | {v["rel_path"] for v in verified})
        new = picked[:max(0, target - len(verified))]
        if not new:
            break
        ok_this_round = []
        for i in range(0, len(new), 4):
            batch = new[i:i + 4]
            prompt = prompts.render("final_verification", cfg,
                                    COUNT=len(batch), MAXIDX=len(batch) - 1)
            try:
                out = model.analyze([Path(b["work_path"]) for b in batch], prompt, schema)
                flagged = {f["index"]: f["reason"] for f in out["flags"]
                           if f["index"] < len(batch)}
            except (ModelError, InvalidOutput):
                for b in batch:                     # never promote unverified
                    excluded.add(b["rel_path"])
                    vi = b["vi"]; vi.setdefault("evidence", []).append(
                        "verification-unavailable")
                    store.update(b["rel_path"], verdict_info=vi)
                continue
            for j, b in enumerate(batch):
                if j in flagged:
                    flags_total += 1
                    excluded.add(b["rel_path"])
                    store.update(b["rel_path"], verdict="needs-review", verdict_info={
                        "reason": "verification-flagged", "tier": "low",
                        "judgments": {"flag_reason": flagged[j]},
                        "bucket": b["bucket"], "event": b["event"]})
                else:
                    ok_this_round.append(b)
        verified.extend(ok_this_round)
        if len(verified) >= target:
            break

    # Confidence-gated highlights critique: one evaluator pass, bottom-decile reconsider
    if budget is not None and verified:
        eval_schema = prompts.load_schema("highlights_eval")
        eval_prompt = prompts.render("highlights_eval", cfg)
        weak_picks = []
        for v in list(verified):
            if not budget.charge():
                break
            try:
                ev = model.analyze([Path(v["work_path"])], eval_prompt, eval_schema)
                if ev.get("verdict") in ("weak", "remove"):
                    weak_picks.append(v)
            except Exception:
                pass
        if weak_picks:
            picked_rels = {v["rel_path"] for v in verified}
            excluded_sorted = sorted(
                [c for c in cands if c["rel_path"] not in picked_rels],
                key=lambda c: (-c["composite"], c["rel_path"]))
            for weak in weak_picks:
                if not excluded_sorted or not budget.charge():
                    break
                challenger = excluded_sorted.pop(0)
                verified = [challenger if v["rel_path"] == weak["rel_path"] else v
                            for v in verified]

    for v in verified:
        vi = v["vi"]
        vi.setdefault("evidence", []).append("survived-final-verification")
        store.update(v["rel_path"], verdict="top-pick", verdict_info=vi)

    return {"top_picks": len(verified), "events": len(evs),
            "verification_flags": flags_total}
