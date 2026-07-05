import shutil
from pathlib import Path
from curator.config import load_config
from curator.db import Store
from curator.inventory import run_stage1, source_tree_hash

def _setup(tmp_path, img_factory):
    src = tmp_path / "src"
    img_factory(src / "a.jpg", "scene", exif_dt="2026:05:12 10:00:00", seed=1)
    img_factory(src / "sub" / "b.jpg", "portrait", exif_dt="2026:05:12 10:00:05", seed=2)
    shutil.copy(src / "a.jpg", src / "a_copy.jpg")          # exact dupe
    (src / "bad.jpg").write_bytes(b"not an image")          # corrupt
    (src / "clip.mp4").write_bytes(b"\x00" * 100)           # video -> skipped
    return src

def test_inventory_classifies(tmp_path, img_factory):
    src = _setup(tmp_path, img_factory)
    store = Store(tmp_path / "c.db")
    summary = run_stage1(src, store, load_config(None))
    assert summary["corrupt"] == 1 and summary["exact_dupes"] == 1
    a = store.photo("a.jpg")
    assert a["status"] == "ok" and a["ts_source"] == "exif" and a["stage_done"] == 1
    assert a["width"] == 1600 and a["exif"]["make"] == "TestCam"
    dupe = store.photo("a_copy.jpg")
    assert dupe["verdict"] == "duplicate-inferior" and dupe["status"] == "excluded"
    assert dupe["verdict_info"]["kept"] == "a.jpg"
    assert store.photo("clip.mp4")["status"] == "skipped"
    assert store.photo("bad.jpg")["status"] == "corrupt"

def test_mtime_fallback(tmp_path, img_factory):
    src = tmp_path / "src"
    img_factory(src / "noexif.jpg", "scene", exif_dt=None, exif_make=None)
    store = Store(tmp_path / "c.db")
    run_stage1(src, store, load_config(None))
    assert store.photo("noexif.jpg")["ts_source"] == "mtime"

def test_source_tree_hash_changes(tmp_path, img_factory):
    src = _setup(tmp_path, img_factory)
    h1 = source_tree_hash(src)
    img_factory(src / "new.jpg", "scene", seed=9)
    assert source_tree_hash(src) != h1
