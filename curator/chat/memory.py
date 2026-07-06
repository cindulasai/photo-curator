from __future__ import annotations
import copy, json
from pathlib import Path
from .. import prompts
from ..review.corrections import append_correction, was_declined

MEMORY_FILE = Path.home() / ".photo-curator" / "memory.md"
_HEADER = "# What I've learned about your taste\n"


def load_memory(path: Path | None = None) -> list[str]:
    p = path or MEMORY_FILE
    if not p.exists():
        return []
    lines = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("- "):
            # Strip internal [key] markers before returning to callers
            entry = line[2:].rsplit("  [", 1)[0].strip()
            if entry:
                lines.append(entry)
    return lines


def propose_memories(corrections: list[dict], model, cfg: dict) -> list[dict]:
    if not corrections:
        return []
    corr_json = json.dumps(corrections, sort_keys=True)
    schema = prompts.load_schema("memory")
    try:
        result = model.analyze([], prompts.render("memory", cfg, CORRECTIONS=corr_json),
                               schema)
        proposals = result.get("proposals", [])
    except Exception:
        return []
    return [p for p in proposals
            if len(p.get("evidence_refs", [])) >= 3 and not was_declined(p["key"])]


def confirm_proposal(proposal: dict, path: Path | None = None) -> None:
    p = path or MEMORY_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    statement = proposal["statement"]
    key = proposal.get("key", "")
    existing = p.read_text() if p.exists() else _HEADER
    lines = existing.splitlines()
    # Remove any existing line with the same key marker
    lines = [l for l in lines if f"[{key}]" not in l]
    entry = f"- {statement}" + (f"  [{key}]" if key else "")
    if not any(l.startswith("# ") for l in lines):
        lines = [_HEADER.strip()] + lines
    lines.append(entry)
    p.write_text("\n".join(lines) + "\n")


def decline_proposal(proposal: dict) -> None:
    append_correction({"kind": "declined", "key": proposal["key"]})


def inject_memory(cfg: dict, path: Path | None = None) -> dict:
    lines = load_memory(path or MEMORY_FILE)
    if not lines:
        return copy.deepcopy(cfg)
    new_cfg = copy.deepcopy(cfg)
    existing = list(new_cfg.get("prompt_suffix") or [])
    for line in lines:
        if line not in existing:
            existing.append(line)
    new_cfg["prompt_suffix"] = existing
    return new_cfg
