import json
from pathlib import Path
from curator.config import load_config, config_hash
from curator.db import Store
from curator.manifest import write_manifest
from curator.report import write_report

def _store(tmp_path, img_factory):
    store = Store(tmp_path / "c.db")
    src = tmp_path / "src"
    img_factory(src / "pick.jpg", "scene", seed=1)
    work = tmp_path / "work"; work.mkdir()
    import shutil; shutil.copy(src / "pick.jpg", work / "w.jpg")
    store.upsert_photo("pick.jpg", kind="photo", status="ok", sha256="aa" * 32,
                       size=5, ts=1778916000.0, ts_source="exif",
                       stage2={"flags": [], "phash": 3, "work_path": str(work / "w.jpg"),
                               "lap_var_global": 90, "lap_var_center": 90},
                       verdict="top-pick",
                       verdict_info={"bucket": "people", "event": "2026-05-16 people",
                                     "description": "a joyful moment", "tier": "medium",
                                     "scores": {"composite": 3.1}, "evidence": ["x"]})
    store.upsert_photo("rev.jpg", kind="photo", status="ok", sha256="bb" * 32, size=5,
                       verdict="needs-review",
                       verdict_info={"reason": "passes-disagree", "judgments": {}})
    store.upsert_photo("skip.mp4", kind="video", status="skipped", size=5)
    return store, src

def test_manifest_structure_and_determinism(tmp_path, img_factory):
    store, src = _store(tmp_path, img_factory)
    cfg = load_config(None)
    out = tmp_path / "curated"; out.mkdir()
    p1 = write_manifest(store, cfg, out, "mock", {"stage1_s": 1.0}, "srchash")
    m1 = json.loads(Path(p1).read_text())
    assert m1["run"]["config_hash"] == config_hash(cfg)
    assert m1["photos"][0]["rel_path"] == "pick.jpg"
    assert "work_path" not in m1["photos"][0]["classical"]
    m2 = json.loads(write_manifest(store, cfg, out, "mock",
                                   {"stage1_s": 9.9}, "srchash").read_text())
    del m1["timings"]; del m2["timings"]
    assert m1 == m2

def test_report_sections_in_order(tmp_path, img_factory):
    store, src = _store(tmp_path, img_factory)
    out = tmp_path / "curated"; out.mkdir()
    p = write_report(store, load_config(None), out, src, "mock", {"stage1_s": 1.0})
    text = Path(p).read_text()
    order = [text.index(h) for h in
             ["# Curation Report", "## Top picks", "## Needs your eyes",
              "## Double-check these", "## Events", "## Statistics", "## Skipped files"]]
    assert order == sorted(order)
    assert "a joyful moment" in text and "passes-disagree" in text
    assert (out / "report-assets").exists()
