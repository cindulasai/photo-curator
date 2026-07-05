from __future__ import annotations
import copy, hashlib, json
from pathlib import Path
import yaml

# Spec §7.1 — descriptions are used VERBATIM in LLM prompts.
DEFAULT_BUCKETS = [
    {"key": "people", "description": "Portraits, group shots, candids where people are the subject", "utility": False},
    {"key": "celebrations", "description": "Birthdays, weddings, holidays, parties, ceremonies", "utility": False},
    {"key": "kids-family", "description": "Children and family life moments", "utility": False},
    {"key": "travel", "description": "Trips and vacations - landmarks, hotels, journeys", "utility": False},
    {"key": "nature-outdoors", "description": "Landscapes, hikes, beaches, gardens, sky", "utility": False},
    {"key": "urban-architecture", "description": "Cities, buildings, streets, interiors as subject", "utility": False},
    {"key": "events-performances", "description": "Concerts, sports, shows, public events", "utility": False},
    {"key": "food-drink", "description": "Meals, dishes, drinks, restaurants, cooking", "utility": False},
    {"key": "pets-animals", "description": "Pets and animals as the subject", "utility": False},
    {"key": "hobbies-activities", "description": "Sports, crafts, games, projects being done", "utility": False},
    {"key": "vehicles", "description": "Cars, bikes, boats, planes as the subject", "utility": False},
    {"key": "screenshots", "description": "Device screenshots (utility)", "utility": True},
    {"key": "documents-receipts", "description": "Documents, receipts, IDs, forms, labels (utility)", "utility": True},
    {"key": "whiteboards-notes", "description": "Whiteboards, handwritten notes, slides (utility)", "utility": True},
    {"key": "products-shopping", "description": "Products photographed for reference or shopping (utility)", "utility": True},
    {"key": "everyday-misc", "description": "Genuinely uncategorizable everyday shots - the honest fallback", "utility": False},
]

# Spec §4.2, §5.4, §7.2 — normative defaults.
DEFAULTS = {
    "model": "qwen2.5vl:7b",
    "ollama_url": "http://localhost:11434",
    "buckets": {"disable": [], "custom": []},
    "triage": {
        "blur_sharp_min": 60.0,       # sharp if max(global,center) >= this
        "blur_extreme_max": 25.0,     # blur-extreme if both below this
        "black_extreme": 85.0,        # % pixels luma<8
        "white_extreme": 85.0,        # % pixels luma>247
        "exposure_poor": 40.0,
        "doc_white_min": 0.55, "doc_edge_min": 0.02,
        "burst_gap_s": 3.0, "burst_hamming_max": 10, "neardupe_hamming_max": 6,
        "working_edge_px": 1536, "min_megapixels": 0.1,
    },
    "llm": {"analyze_edge_px": 1024, "timeout_s": 120, "seed": 42},
    "top_picks": {"target": "auto", "cap": 300, "max_per_event": 15,
                  "burst_window_s": 60, "burst_window_max": 3, "bucket_share_max": 0.5},
    "rubric": {"emotional": 0.30, "people_engagement": 0.20, "event_significance": 0.15,
               "composition_light": 0.15, "uniqueness": 0.10, "scene_appeal": 0.10},
    "tournament": {"classical_agree_ratio": 0.7},
    "events": {"gap_hours": 6.0, "gps_jump_km": 50.0},
    "fast": {"enabled": False},
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: Path | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if path is not None:
        user = yaml.safe_load(Path(path).read_text()) or {}
        cfg = _deep_merge(cfg, user)
    for c in cfg["buckets"]["custom"]:
        if "key" not in c or "description" not in c:
            raise ValueError(f"custom bucket needs key+description: {c}")
        c.setdefault("utility", False)
    return cfg


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def active_buckets(cfg: dict) -> list[dict]:
    disabled = set(cfg["buckets"]["disable"])
    out = [b for b in DEFAULT_BUCKETS if b["key"] not in disabled]
    out += [dict(c) for c in cfg["buckets"]["custom"]]
    return out
