from curator.config import load_config
from curator.db import Store
from curator.inventory import run_stage1
from curator.stage2 import run_stage2
from curator.tournament import run_tournaments
from curator.model import MockModel

def _pipeline(tmp_path, img_factory, n=3, sharp_idx=0):
    src = tmp_path / "src"
    for i in range(n):   # burst: same seed, i-th sharp, others slightly blurred
        img_factory(src / f"b{i}.jpg", "scene", seed=7, blur=0 if i == sharp_idx else 2,
                    exif_dt=f"2026:05:12 10:00:0{i}")
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    run_stage1(src, store, cfg); run_stage2(src, store, cfg, tmp_path / "work")
    assert len(store.groups()) == 1
    return src, store, cfg

def test_champion_with_classical_agreement(tmp_path, img_factory):
    src, store, cfg = _pipeline(tmp_path, img_factory, sharp_idx=1)
    picks = MockModel(lambda paths, p, s: {"best_index": [i for i, pp in enumerate(paths)
                                           if pp.name.endswith("_b1.jpg")][0],
                                           "reason": "eyes open", "unsure": False})
    out = run_tournaments(src, store, cfg, picks)
    g = store.groups()[0]
    assert g["champion"] == "b1.jpg" and g["info"]["classical_agree"] is True
    assert out["decided"] == 1

def test_unsure_leaves_group_unresolved(tmp_path, img_factory):
    src, store, cfg = _pipeline(tmp_path, img_factory)
    unsure = MockModel(lambda *a: {"best_index": 0, "reason": "too close", "unsure": True})
    out = run_tournaments(src, store, cfg, unsure)
    g = store.groups()[0]
    assert g["champion"] is None and g["info"]["unsure"] is True and out["review"] == 1

def test_classical_disagreement_recorded(tmp_path, img_factory):
    src = tmp_path / "src"
    img_factory(src / "sharp.jpg", "scene", seed=7, exif_dt="2026:05:12 10:00:00")
    img_factory(src / "blurry.jpg", "scene", seed=7, blur=2, exif_dt="2026:05:12 10:00:01")
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    run_stage1(src, store, cfg); run_stage2(src, store, cfg, tmp_path / "work")
    lover_of_blur = MockModel(lambda paths, p, s: {"best_index": [i for i, pp in
                              enumerate(paths) if pp.name.endswith("_blurry.jpg")][0],
                              "reason": "prefers it", "unsure": False})
    run_tournaments(src, store, cfg, lover_of_blur)
    g = store.groups()[0]
    assert g["champion"] == "blurry.jpg" and g["info"]["classical_agree"] is False
