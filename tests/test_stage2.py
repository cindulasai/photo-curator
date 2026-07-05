from curator.config import load_config
from curator.db import Store
from curator.inventory import run_stage1
from curator.stage2 import run_stage2

def _run(tmp_path, img_factory, make_photos):
    src = tmp_path / "src"; make_photos(src, img_factory)
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    run_stage1(src, store, cfg)
    summary = run_stage2(src, store, cfg, tmp_path / "work")
    return store, summary

def test_flags_and_autoreject(tmp_path, img_factory):
    def mk(src, f):
        f(src / "sharp.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:00")
        f(src / "soft.jpg", "scene", seed=2, blur=1.6, exif_dt="2026:05:12 11:00:00")
        f(src / "hopeless.jpg", "black", blur=15)          # blur-extreme + exposure-extreme + no faces
        f(src / "shot.png", "screenshot")
        f(src / "doc.jpg", "white_doc")
    store, summary = _run(tmp_path, img_factory, mk)
    assert store.photo("sharp.jpg")["stage2"]["flags"] == []
    assert "blur-soft" in store.photo("soft.jpg")["stage2"]["flags"]
    hopeless = store.photo("hopeless.jpg")
    assert hopeless["verdict"] == "reject" and hopeless["verdict_info"]["reason"] == "unsalvageable"
    assert summary["auto_rejected"] == 1
    assert "screenshot-candidate" in store.photo("shot.png")["stage2"]["flags"]
    assert "document-candidate" in store.photo("doc.jpg")["stage2"]["flags"]

def test_burst_group_created(tmp_path, img_factory):
    def mk(src, f):
        for i in range(3):    # same scene, seconds apart -> burst
            f(src / f"burst_{i}.jpg", "scene", seed=42, blur=i,
              exif_dt=f"2026:05:12 10:00:0{i}")
    store, summary = _run(tmp_path, img_factory, mk)
    gs = store.groups()
    assert len(gs) == 1 and gs[0]["kind"] == "burst" and len(gs[0]["members"]) == 3

def test_stage2_resumes_without_rework(tmp_path, img_factory):
    def mk(src, f):
        f(src / "a.jpg", "scene", seed=1)
    store, _ = _run(tmp_path, img_factory, mk)
    before = store.photo("a.jpg")["stage2"]
    from curator.stage2 import run_stage2 as rs2
    from curator.config import load_config as lc
    rs2(tmp_path / "src", store, lc(None), tmp_path / "work")   # second call: no-op
    assert store.photo("a.jpg")["stage2"] == before
