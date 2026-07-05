from curator.config import load_config
from curator.db import Store
from curator.inventory import run_stage1
from curator.stage2 import run_stage2
from curator.stage3 import run_stage3
from curator.model import MockModel
from tests.test_qualification import _smart_handler

def _reworded(paths, prompt, schema):
    return {"keep_worthy": "yes", "real_camera_photo": "yes",
            "intentional_shot": "yes", "note": "fine"}

def _router(paths, prompt, schema):
    if "keep_worthy" in str(schema):
        return _reworded(paths, prompt, schema)
    return _smart_handler(paths, prompt, schema)

def _prep(tmp_path, img_factory):
    src = tmp_path / "src"
    img_factory(src / "clean.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:00")
    img_factory(src / "soft.jpg", "scene", seed=2, blur=1.6, exif_dt="2026:05:13 10:00:00")
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    run_stage1(src, store, cfg); run_stage2(src, store, cfg, tmp_path / "work")
    return src, store, cfg

def test_two_pass_only_when_triggered(tmp_path, img_factory):
    src, store, cfg = _prep(tmp_path, img_factory)
    m = MockModel(_router)
    out = run_stage3(src, store, cfg, m)
    assert out["analyzed"] == 2
    assert store.photo("clean.jpg")["stage3"]["pass2"] is None       # no trigger
    assert store.photo("soft.jpg")["stage3"]["pass2"] is not None    # blur-soft trigger
    assert out["second_passes"] == 1

def test_invalid_output_marks_photo(tmp_path, img_factory):
    src, store, cfg = _prep(tmp_path, img_factory)
    def flaky(paths, prompt, schema):
        if paths[0].name.endswith("_soft.jpg") and "keep_worthy" not in str(schema):
            return {"nonsense": True}
        return _router(paths, prompt, schema)
    out = run_stage3(src, store, cfg, MockModel(flaky))
    assert store.photo("soft.jpg")["stage3"]["error"] == "model-output-invalid"
    assert out["invalid"] == 1

def test_resume_skips_done(tmp_path, img_factory):
    src, store, cfg = _prep(tmp_path, img_factory)
    m = MockModel(_router)
    run_stage3(src, store, cfg, m)
    n = len(m.calls)
    run_stage3(src, store, cfg, m)
    assert len(m.calls) == n
