from __future__ import annotations
import json, re
from collections import Counter
from pathlib import Path
from .. import prompts

_FILENAME_RE = re.compile(
    r"[\w\-()]+\.(?:jpe?g|png|heic|heif|webp|tiff?|bmp|gif)", re.IGNORECASE)


def build_context(store, question: str, limit: int = 8) -> dict:
    names = {m.group(0).lower() for m in _FILENAME_RE.finditer(question)}
    all_photos = store.photos()
    verdicts = Counter(p["verdict"] for p in all_photos if p.get("verdict"))
    matched = []
    for p in all_photos:
        if Path(p["rel_path"]).name.lower() in names:
            matched.append({k: p.get(k) for k in
                            ("rel_path", "verdict", "verdict_info", "stage3", "stage2")
                            if p.get(k) is not None})
    return {"summary": {"total": len(all_photos), "verdicts": dict(verdicts)},
            "photos": matched[:limit]}


def answer(model, store, cfg: dict, question: str) -> str:
    ctx = build_context(store, question)
    prompt = prompts.render("qa", cfg, QUESTION=question,
                            CONTEXT=json.dumps(ctx, default=str, sort_keys=True))
    return model.analyze([], prompt, prompts.load_schema("qa"))["reply"]
