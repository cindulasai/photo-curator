import hashlib, json
from pathlib import Path
from curator.cli import run_pipeline
from curator.model import MockModel
from tests.test_cli import _Args


def _orig(p: Path) -> str:
    """Recover the original filename from a work-copy name '<sha>_<stem>.jpg'."""
    return p.name.split("_", 1)[1] if "_" in p.name else p.name


def _handler(paths, prompt, schema):
    """Scripted 'perfect model': routes by original filename + schema shape."""
    name = _orig(paths[0])
    props = set((schema.get("properties") or {}).keys())
    if "best_index" in props:                        # tournament: prefer 'best' frame
        idx = next((i for i, p in enumerate(paths) if "best" in _orig(p)), 0)
        return {"best_index": idx, "reason": "clearest expressions", "unsure": False}
    if "flags" in props:                             # verification: approve all
        return {"flags": []}
    if "keep_worthy" in props:                       # reworded pass
        bad = name.startswith(("dark", "smear"))
        return {"keep_worthy": "no" if bad else "yes",
                "real_camera_photo": "yes",
                "intentional_shot": "no" if name.startswith("smear") else "yes",
                "note": "n"}
    fatal = "yes" if name.startswith(("dark", "smear")) else "no"
    shot = "yes" if name.startswith("shot") else "no"
    doc = "yes" if name.startswith("receipt") else "no"
    bucket, conf, rubric = "everyday-misc", 0.9, \
        {"emotional": 1, "people_engagement": 0, "composition_light": 1,
         "scene_appeal": 1, "novelty": 0, "justifications": {}}
    if name.startswith("trip"):
        bucket, conf = "travel", 0.93
        rubric = {"emotional": 3, "people_engagement": 1, "composition_light": 3,
                  "scene_appeal": 4, "novelty": 2, "justifications": {}}
    if name.startswith("burst"):
        bucket, conf = "people", 0.9
        rubric = {"emotional": 4, "people_engagement": 4, "composition_light": 3,
                  "scene_appeal": 2, "novelty": 1, "justifications": {}}
    return {"bucket": {"primary": bucket, "confidence": conf, "alternates": []},
            "tags": [], "description": f"synthetic {name}",
            "people": {"count": 0, "eyes_closed": "n/a", "expression_quality": "n/a"},
            "utility": {"is_screenshot": shot, "is_document": doc, "is_accidental": "no"},
            "quality_judgment": {"fatal": fatal, "note": "x"},
            "rubric": rubric}


def _factory(cfg):
    return MockModel(_handler)


def _build_source(tmp_path, img_factory):
    src = tmp_path / "src"
    for i in range(6):
        img_factory(src / f"trip{i}.jpg", "scene", seed=30 + i, gps=(41.89, 12.48),
                    exif_dt=f"2026:05:12 10:0{i}:00")
    img_factory(src / "burst_best.jpg", "scene", seed=50, exif_dt="2026:05:12 11:00:00")
    img_factory(src / "burst_b.jpg", "scene", seed=50, blur=2, exif_dt="2026:05:12 11:00:01")
    img_factory(src / "burst_c.jpg", "scene", seed=50, blur=3, exif_dt="2026:05:12 11:00:02")
    img_factory(src / "dark.jpg", "black", blur=16)                  # auto-reject
    img_factory(src / "smear.jpg", "scene", seed=60, blur=9,
                exif_dt="2026:05:12 12:00:00")                       # LLM+classical reject
    img_factory(src / "shot.png", "screenshot")
    img_factory(src / "receipt.jpg", "white_doc")
    return src


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def test_end_to_end(tmp_path, img_factory):
    src = _build_source(tmp_path, img_factory)
    before = _tree_hash(src)
    out = tmp_path / "curated"
    assert run_pipeline(_Args(src, out), _factory) == 0
    assert _tree_hash(src) == before                                 # R1

    m = json.loads((out / "manifest.json").read_text())
    v = {p["rel_path"]: p["verdict"] for p in m["photos"]}
    assert v["dark.jpg"] == "reject"
    assert v["burst_best.jpg"] in ("keep", "top-pick")
    assert v["burst_b.jpg"] == "duplicate-inferior"
    assert v["smear.jpg"] == "reject"
    assert v["shot.png"] == "keep"
    b = {p["rel_path"]: p.get("bucket") for p in m["photos"]}
    assert b["shot.png"] == "screenshots" and b["receipt.jpg"] == "documents-receipts"
    assert (out / "library").exists() and (out / "REPORT.md").exists()
    chosen = list((out / "duplicates").rglob("CHOSEN.md"))
    assert chosen and "burst_best.jpg" in chosen[0].read_text()


def test_determinism(tmp_path, img_factory):
    src = _build_source(tmp_path, img_factory)
    m = []
    for run in ["r1", "r2"]:
        out = tmp_path / run
        assert run_pipeline(_Args(src, out), _factory) == 0
        d = json.loads((out / "manifest.json").read_text())
        del d["timings"]
        m.append(json.dumps(d, sort_keys=True))
    assert m[0] == m[1]                                              # R4


def test_resume_after_interrupt(tmp_path, img_factory):
    src = _build_source(tmp_path, img_factory)
    out = tmp_path / "curated"
    calls = {"n": 0}
    def dying(paths, prompt, schema):
        calls["n"] += 1
        if calls["n"] == 4:
            from curator.model import ModelError
            raise ModelError("simulated ollama crash")
        return _handler(paths, prompt, schema)
    assert run_pipeline(_Args(src, out), lambda cfg: MockModel(dying)) == 4
    assert run_pipeline(_Args(src, out, resume=True), _factory) == 0  # R3
    assert (out / "REPORT.md").exists()
