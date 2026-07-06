from curator.config import load_config
from curator.db import Store
from curator.inventory import run_stage1
from curator.prompts import render


def test_prompt_suffix_injected():
    cfg = load_config(None)
    cfg["prompt_suffix"] = ["Weight photos of children highly."]
    for name in ["analyze_photo", "analyze_photo_reworded"]:
        assert "Weight photos of children highly." in render(name, cfg)
    assert "children" in render("tournament", cfg, COUNT=2, MAXIDX=1)
    base = load_config(None)
    assert "children" not in render("analyze_photo", base)


def test_skip_globs_in_stage1(tmp_path, img_factory):
    src = tmp_path / "src"
    img_factory(src / "keep.jpg", "scene", seed=1)
    img_factory(src / "WhatsApp" / "wa1.jpg", "scene", seed=2)
    cfg = load_config(None)
    cfg["skip_globs"] = ["WhatsApp/*"]
    store = Store(tmp_path / "c.db")
    s = run_stage1(src, store, cfg)
    assert s["photos"] == 1 and s["skipped"] == 1
    assert store.photo("WhatsApp/wa1.jpg")["status"] == "skipped"


def test_stage3_steer_swaps_cfg(tmp_path, img_factory):
    from curator.model import MockModel
    from curator.stage2 import run_stage2
    from curator.stage3 import run_stage3
    src = tmp_path / "src"
    for i in range(3):
        img_factory(src / f"p{i}.jpg", "scene", seed=10 + i,
                    exif_dt=f"2026:05:12 10:0{i}:00")
    cfg = load_config(None)
    store = Store(tmp_path / "c.db")
    run_stage1(src, store, cfg)
    run_stage2(src, store, cfg, tmp_path / "work")
    prompts_seen = []
    def handler(paths, prompt, schema):
        prompts_seen.append(prompt)
        return {"bucket": {"primary": "everyday-misc", "confidence": 0.9, "alternates": []},
                "tags": [], "description": "x",
                "people": {"count": 0, "eyes_closed": "n/a", "expression_quality": "n/a"},
                "utility": {"is_screenshot": "no", "is_document": "no", "is_accidental": "no"},
                "quality_judgment": {"fatal": "no", "note": "x"},
                "rubric": {"emotional": 1, "people_engagement": 0, "composition_light": 1,
                           "scene_appeal": 1, "novelty": 0, "justifications": {}}}
    def steer(cfg_in, idx):
        if idx == 1:                       # apply before the 2nd photo
            out = dict(cfg_in)
            out["prompt_suffix"] = ["STEERED"]
            return out
        return None
    run_stage3(src, store, cfg, MockModel(handler), steer=steer)
    assert "STEERED" not in prompts_seen[0]
    assert all("STEERED" in p for p in prompts_seen[1:])
