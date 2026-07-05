from __future__ import annotations
from .config import active_buckets
from .db import Store

_QUALITY_FLAGS = {"blur-extreme", "blur-soft", "exposure-extreme", "exposure-poor"}


def confidence_tier(two_pass_agree, classical: str, self_conf) -> str:
    if two_pass_agree is None:
        return "medium" if (self_conf or 0) >= 0.8 else "low"
    if not two_pass_agree:
        return "low"
    return "medium" if classical == "conflict" else "high"


def _review(store, rel, reason, judgments):
    store.update(rel, verdict="needs-review",
                 verdict_info={"reason": reason, "tier": "low", "judgments": judgments})


def _keep(store, rel, bucket, tier, evidence, p1):
    store.update(rel, verdict="keep", verdict_info={
        "bucket": bucket, "tier": tier, "evidence": evidence,
        "tags": p1.get("tags", []) if p1 else [],
        "description": p1.get("description", "") if p1 else "",
        "rubric": p1.get("rubric") if p1 else None,
        "people": p1.get("people") if p1 else None})


def resolve_all(store: Store, cfg: dict) -> dict:
    keys = {b["key"] for b in active_buckets(cfg)}
    summary = {"keep": 0, "reject": 0, "dupe": 0, "review": 0}
    group_of = {}
    for g in store.groups():
        for m in g["members"]:
            group_of[m] = g

    for photo in store.photos(status="ok"):
        if photo["verdict"] is not None:
            continue
        rel, s2, s3 = photo["rel_path"], photo["stage2"] or {}, photo["stage3"] or {}
        flags = set(s2.get("flags", []))
        g = group_of.get(rel)

        if s3.get("error"):
            _review(store, rel, "model-output-invalid", {}); summary["review"] += 1; continue

        if g is not None:
            info = g["info"] or {}
            if not g["champion"]:
                _review(store, rel, "tournament-unsure" if info.get("unsure")
                        else "model-output-invalid", info)
                summary["review"] += 1; continue
            if not info.get("classical_agree", False):
                _review(store, rel, "tournament-conflict", info)
                summary["review"] += 1; continue
            if rel != g["champion"]:
                store.update(rel, verdict="duplicate-inferior", verdict_info={
                    "reason": "tournament", "kept": g["champion"],
                    "evidence": ["tournament-choice", "classical-agree"],
                    "tier": "high"})
                summary["dupe"] += 1; continue
            # champion falls through to its own analysis

        if s3.get("fast_skipped"):
            _keep(store, rel, "everyday-misc", "low", ["fast-mode-unclassified"], None)
            summary["keep"] += 1; continue

        p1, p2 = s3.get("pass1"), s3.get("pass2")
        if not p1:
            _review(store, rel, "pipeline-error", {"note": "no analysis present"})
            summary["review"] += 1; continue

        if p1["quality_judgment"]["fatal"] == "yes":
            agree = bool(p2) and p2.get("keep_worthy") == "no"
            classical = "concur" if flags & _QUALITY_FLAGS else "conflict"
            if confidence_tier(agree if p2 else False, classical, None) == "high":
                store.update(rel, verdict="reject", verdict_info={
                    "reason": "quality", "tier": "high",
                    "evidence": sorted(flags & _QUALITY_FLAGS) +
                                ["llm-fatal-pass1", "llm-fatal-pass2"]})
                summary["reject"] += 1
            else:
                _review(store, rel, "passes-disagree", {"pass1": p1, "pass2": p2})
                summary["review"] += 1
            continue

        if p1["utility"]["is_accidental"] == "yes":
            agree = bool(p2) and p2.get("intentional_shot") == "no"
            classical = "concur" if flags else "conflict"
            if confidence_tier(agree if p2 else False, classical, None) == "high":
                store.update(rel, verdict="reject", verdict_info={
                    "reason": "accidental", "tier": "high",
                    "evidence": sorted(flags) + ["llm-accidental-pass1",
                                                 "llm-accidental-pass2"]})
                summary["reject"] += 1
            else:
                _review(store, rel, "passes-disagree", {"pass1": p1, "pass2": p2})
                summary["review"] += 1
            continue

        if "screenshot-candidate" in flags and p1["utility"]["is_screenshot"] == "yes":
            _keep(store, rel, "screenshots", "medium",
                  ["screenshot-candidate", "llm-confirmed"], p1)
            summary["keep"] += 1; continue
        if "document-candidate" in flags and p1["utility"]["is_document"] == "yes":
            _keep(store, rel, "documents-receipts", "medium",
                  ["document-candidate", "llm-confirmed"], p1)
            summary["keep"] += 1; continue

        primary, conf = p1["bucket"]["primary"], p1["bucket"]["confidence"]
        if primary not in keys:
            _review(store, rel, "invalid-bucket-key", {"pass1": p1})
            summary["review"] += 1
        elif conf >= 0.8:
            _keep(store, rel, primary, "medium", [f"bucket-confidence-{conf:.2f}"], p1)
            summary["keep"] += 1
        elif conf >= 0.3:
            _keep(store, rel, "everyday-misc", "low",
                  [f"low-confidence-guess: {primary} @ {conf:.2f}"], p1)
            summary["keep"] += 1
        else:
            _review(store, rel, "model-unsure", {"pass1": p1})
            summary["review"] += 1
    return summary
