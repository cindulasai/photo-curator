from curator.config import load_config
from curator.db import Store
from curator.verdicts import confidence_tier, resolve_all

def test_tier_matrix():
    assert confidence_tier(True, "concur", None) == "high"
    assert confidence_tier(True, "na", None) == "high"
    assert confidence_tier(True, "conflict", None) == "medium"
    assert confidence_tier(False, "concur", None) == "low"
    assert confidence_tier(None, "na", 0.9) == "medium"
    assert confidence_tier(None, "na", 0.7) == "low"

def _photo(store, rel, flags=(), p1=None, p2=None, error=None, verdict=None):
    s3 = {"error": error} if error else \
         {"pass1": p1, "pass2": p2, "prompt_versions": {}} if p1 else None
    store.upsert_photo(rel, kind="photo", status="ok", stage_done=3, verdict=verdict,
                       stage2={"flags": list(flags), "lap_var_global": 100,
                               "lap_var_center": 100, "phash": 1, "faces": 0,
                               "work_path": "x"},
                       stage3=s3)

def _p1(bucket="people", conf=0.9, fatal="no", accidental="no",
        screenshot="no", document="no"):
    return {"bucket": {"primary": bucket, "confidence": conf, "alternates": []},
            "tags": [], "description": "d",
            "people": {"count": 1, "eyes_closed": "no", "expression_quality": "ok"},
            "utility": {"is_screenshot": screenshot, "is_document": document,
                        "is_accidental": accidental},
            "quality_judgment": {"fatal": fatal, "note": ""},
            "rubric": {"emotional": 2, "people_engagement": 2, "composition_light": 2,
                       "scene_appeal": 2, "novelty": 1, "justifications": {}}}

def test_reject_requires_full_agreement(tmp_path):
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    p2_no = {"keep_worthy": "no", "real_camera_photo": "yes", "intentional_shot": "yes"}
    p2_yes = {"keep_worthy": "yes", "real_camera_photo": "yes", "intentional_shot": "yes"}
    _photo(store, "dead.jpg", ["blur-extreme"], _p1(fatal="yes"), p2_no)
    _photo(store, "saved.jpg", ["blur-soft"], _p1(fatal="yes"), p2_yes)   # pass2 dissents
    _photo(store, "noflag.jpg", [], _p1(fatal="yes"), p2_no)              # no classical
    resolve_all(store, cfg)
    assert store.photo("dead.jpg")["verdict"] == "reject"
    assert store.photo("saved.jpg")["verdict"] == "needs-review"
    assert store.photo("noflag.jpg")["verdict"] == "needs-review"

def test_bucket_confidence_ladder(tmp_path):
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    _photo(store, "sure.jpg", [], _p1("travel", 0.92))
    _photo(store, "meh.jpg", [], _p1("travel", 0.5))
    _photo(store, "lost.jpg", [], _p1("travel", 0.1))
    _photo(store, "alien.jpg", [], _p1("not-a-bucket", 0.9))
    resolve_all(store, cfg)
    assert store.photo("sure.jpg")["verdict_info"]["bucket"] == "travel"
    assert store.photo("meh.jpg")["verdict_info"]["bucket"] == "everyday-misc"
    assert store.photo("lost.jpg")["verdict"] == "needs-review"
    assert store.photo("alien.jpg")["verdict"] == "needs-review"

def test_utility_bucket_needs_flag_and_confirm(tmp_path):
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    _photo(store, "shot.png", ["screenshot-candidate"], _p1(screenshot="yes"))
    _photo(store, "claims.jpg", [], _p1("people", 0.9, screenshot="yes"),
           {"keep_worthy": "yes", "real_camera_photo": "yes", "intentional_shot": "yes"})
    resolve_all(store, cfg)
    assert store.photo("shot.png")["verdict_info"]["bucket"] == "screenshots"
    assert store.photo("claims.jpg")["verdict_info"]["bucket"] == "people"  # normal flow

def test_group_losers_and_conflict(tmp_path):
    store = Store(tmp_path / "c.db"); cfg = load_config(None)
    for r in ["g1a.jpg", "g1b.jpg", "g2a.jpg", "g2b.jpg"]:
        _photo(store, r, [], _p1() if r in ("g1a.jpg", "g2a.jpg") else None)
    gid1 = store.add_group("burst", ["g1a.jpg", "g1b.jpg"])
    store.set_group(gid1, champion="g1a.jpg", info={"classical_agree": True, "reason": "r"})
    gid2 = store.add_group("burst", ["g2a.jpg", "g2b.jpg"])
    store.set_group(gid2, champion="g2a.jpg", info={"classical_agree": False, "reason": "r"})
    resolve_all(store, cfg)
    assert store.photo("g1b.jpg")["verdict"] == "duplicate-inferior"
    assert store.photo("g1a.jpg")["verdict"] == "keep"
    assert store.photo("g2a.jpg")["verdict"] == "needs-review"
    assert store.photo("g2b.jpg")["verdict"] == "needs-review"
