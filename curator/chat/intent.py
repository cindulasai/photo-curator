from __future__ import annotations
import json
from .. import prompts
from .deltas import DeltaError, validate_deltas


def parse_intent(model, cfg: dict, text: str, run_state: dict | None = None) -> dict:
    """Free text -> {"deltas": [...], "reply": str}. Deltas are whitelist-
    validated; a model that proposes an out-of-bounds path gets ONE corrective
    retry, then we answer conversationally with no changes (R4: nothing
    unvetted ever reaches the config)."""
    prompt = prompts.render("intent", cfg, USER_TEXT=text,
                            RUN_STATE=json.dumps(run_state or {}, sort_keys=True))
    schema = prompts.load_schema("intent")
    out = model.analyze([], prompt, schema)
    try:
        deltas = validate_deltas(out)
    except DeltaError as exc:
        retry = model.analyze(
            [], prompt + f"\n\nYour previous deltas were rejected ({exc}). "
            "Use only the allowed paths, or return an empty deltas list.", schema)
        try:
            deltas = validate_deltas(retry)
            out = retry
        except DeltaError:
            return {"deltas": [],
                    "reply": "I couldn't turn that into a safe change - "
                             + str(out.get("reply", ""))}
    return {"deltas": deltas, "reply": out["reply"]}
