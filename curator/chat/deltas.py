from __future__ import annotations
import copy

# Spec §6.1 — ONLY these paths are steerable. llm.*, model, events.* are not.
WHITELIST_PREFIXES = ("triage.", "top_picks.", "rubric.")
WHITELIST_EXACT = {"buckets.disable", "buckets.custom", "prompt_suffix", "skip_globs"}
_LIST_PATHS = {"buckets.disable", "buckets.custom", "prompt_suffix", "skip_globs"}
_OPS = {"set", "append"}


class DeltaError(ValueError):
    pass


def _allowed(path: str) -> bool:
    return path in WHITELIST_EXACT or path.startswith(WHITELIST_PREFIXES)


def validate_deltas(doc: dict) -> list[dict]:
    deltas = doc.get("deltas")
    if not isinstance(deltas, list):
        raise DeltaError("deltas must be a list")
    for d in deltas:
        if not isinstance(d, dict) or "path" not in d or "value" not in d:
            raise DeltaError(f"delta needs path and value: {d!r}")
        if not _allowed(d["path"]):
            raise DeltaError(f"path not steerable: {d['path']}")
        d.setdefault("op", "append" if d["path"] in _LIST_PATHS else "set")
        if d["op"] not in _OPS:
            raise DeltaError(f"unknown op: {d['op']}")
        d.setdefault("why", "")
    return deltas


def apply_deltas(cfg: dict, deltas: list[dict]) -> dict:
    out = copy.deepcopy(cfg)
    for d in validate_deltas({"deltas": deltas}):
        node = out
        parts = d["path"].split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        leaf = parts[-1]
        if d["op"] == "append":
            cur = list(node.get(leaf) or [])
            vals = d["value"] if isinstance(d["value"], list) else [d["value"]]
            node[leaf] = cur + [v for v in vals if v not in cur]
        else:
            node[leaf] = d["value"]
    return out


def describe(deltas: list[dict]) -> list[str]:
    lines = []
    for d in deltas:
        verb = "add" if d.get("op") == "append" else "set"
        line = f"{verb} {d['path']} -> {d['value']}"
        if d.get("why"):
            line += f"  ({d['why']})"
        lines.append(line)
    return lines
