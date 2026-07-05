from curator.config import load_config
from curator.db import Store
from curator.stage4 import run_stage4
from curator.model import MockModel

def _keep(store, rel, ts, rubric, bucket="people", phash=None, faces=1):
    store.upsert_photo(rel, kind="photo", status="ok", stage_done=3,
                       ts=ts, ts_source="exif", exif={},
                       stage2={"flags": [], "lap_var_global": 100, "lap_var_center": 100,
                               "phash": phash if phash is not None else
                               abs(hash(rel)) % (2**64),
                               "faces": faces, "work_path": f"tests/na-{rel}"},
                       stage3={"pass1": {
                           "bucket": {"primary": bucket, "confidence": 0.95, "alternates": []},
                           "tags": [], "description": f"photo {rel}",
                           "people": {"count": 1, "eyes_closed": "no",
                                      "expression_quality": "great"},
                           "utility": {"is_screenshot": "no", "is_document": "no",
                                       "is_accidental": "no"},
                           "quality_judgment": {"fatal": "no", "note": ""},
                           "rubric": rubric | {"justifications": {}}},
                           "pass2": None, "prompt_versions": {}})

RUB_HI = {"emotional": 4, "people_engagement": 4, "composition_light": 3,
          "scene_appeal": 3, "novelty": 2}
RUB_LO = {"emotional": 0, "people_engagement": 1, "composition_light": 1,
          "scene_appeal": 1, "novelty": 0}

def _approve_all(paths, prompt, schema):
    return {"flags": []}

def test_top_picks_ranked_and_capped(tmp_path):
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    base = 1778916000.0
    for i in range(30):
        _keep(store, f"hi{i:02d}.jpg", base + i * 7200, RUB_HI)
    for i in range(30):
        _keep(store, f"lo{i:02d}.jpg", base + 500000 + i * 7200, RUB_LO)
    out = run_stage4(tmp_path, store, cfg, MockModel(_approve_all))
    picks = [p["rel_path"] for p in store.photos(verdict="top-pick")]
    assert len(picks) == 20                       # target = max(20, 2% of 60)
    assert all(p.startswith("hi") for p in picks)  # high rubric wins

def test_verification_flag_demotes_and_backfills(tmp_path):
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    base = 1778916000.0
    for i in range(25):
        _keep(store, f"p{i:02d}.jpg", base + i * 7200, RUB_HI)
    def flag_p00(paths, prompt, schema):
        idx = [i for i, p in enumerate(paths) if "p00" in p.name]
        return {"flags": [{"index": idx[0], "reason": "private document visible"}]} \
            if idx else {"flags": []}
    out = run_stage4(tmp_path, store, cfg, MockModel(flag_p00))
    assert store.photo("p00.jpg")["verdict"] == "needs-review"
    assert store.photo("p00.jpg")["verdict_info"]["reason"] == "verification-flagged"
    assert len(store.photos(verdict="top-pick")) == 20 and out["verification_flags"] == 1

def test_events_recorded(tmp_path):
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    base = 1778916000.0
    for i in range(5):
        _keep(store, f"a{i}.jpg", base + i * 60, RUB_HI)
    for i in range(5):
        _keep(store, f"b{i}.jpg", base + 10 * 86400 + i * 60, RUB_LO)
    run_stage4(tmp_path, store, cfg, MockModel(_approve_all))
    assert len(store.events()) == 2
    assert store.photo("a0.jpg")["verdict_info"]["event"] == store.events()[0]["name"]
