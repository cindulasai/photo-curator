from pathlib import Path
from curator.config import load_config
from curator.db import Store
from curator.inventory import run_stage1
from curator.output import materialize

def _run(tmp_path, img_factory):
    src = tmp_path / "src"
    img_factory(src / "a.jpg", "scene", exif_dt="2026:05:12 10:00:00", seed=1)
    img_factory(src / "b.jpg", "portrait", exif_dt="2026:05:12 10:01:00", seed=2)
    store = Store(tmp_path / "c.db")
    cfg = load_config(None)
    run_stage1(src, store, cfg)
    # Manually set verdicts so materialize has something to place
    store.update("a.jpg", verdict="keep",
                 verdict_info={"bucket": "people"}, status="ok")
    store.update("b.jpg", verdict="top-pick",
                 verdict_info={"bucket": "people", "event": None}, status="ok")
    out = tmp_path / "out"
    materialize(src, store, cfg, out)
    return out, store

def test_thumbs_generated(tmp_path, img_factory):
    out, store = _run(tmp_path, img_factory)
    thumb_dir = out / "report-assets" / "thumbs"
    thumbs = list(thumb_dir.rglob("*.jpg"))
    assert len(thumbs) == 2

def test_thumb_max_dimension_256(tmp_path, img_factory):
    out, store = _run(tmp_path, img_factory)
    from PIL import Image
    for t in (out / "report-assets" / "thumbs").rglob("*.jpg"):
        with Image.open(t) as img:
            assert max(img.size) <= 256

def test_thumb_path_by_sha256(tmp_path, img_factory):
    out, store = _run(tmp_path, img_factory)
    for p in store.photos():
        if p["sha256"]:
            sha = p["sha256"]
            expected = out / "report-assets" / "thumbs" / sha[:2] / f"{sha}.jpg"
            assert expected.exists(), f"thumb missing for {p['rel_path']}"

def test_materialize_returns_thumbs_dict(tmp_path, img_factory):
    src = tmp_path / "src"
    img_factory(src / "c.jpg", "scene", exif_dt="2026:05:12 10:02:00", seed=3)
    from curator.db import Store
    from curator.config import load_config
    from curator.inventory import run_stage1
    store = Store(tmp_path / "d.db")
    cfg = load_config(None)
    run_stage1(src, store, cfg)
    store.update("c.jpg", verdict="keep", verdict_info={"bucket": "people"}, status="ok")
    out = tmp_path / "out2"
    result = materialize(src, store, cfg, out)
    thumbs = result.get("_thumbs", {})
    assert "c.jpg" in thumbs
    assert thumbs["c.jpg"].startswith("report-assets/thumbs/")
    assert (out / thumbs["c.jpg"]).exists()
