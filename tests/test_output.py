from pathlib import Path
from curator.db import Store
from curator.config import load_config
from curator.output import materialize, link_or_copy

def _seed(tmp_path, img_factory):
    src = tmp_path / "src"
    for name in ["pick.jpg", "keep.jpg", "loser.jpg", "rej.jpg", "rev.jpg", "keep2.jpg"]:
        img_factory(src / name, "scene", seed=abs(hash(name)) % 100)
    store = Store(tmp_path / "c.db")
    def up(rel, verdict, vi, status="ok"):
        store.upsert_photo(rel, kind="photo", status=status, size=100,
                           sha256="ab" * 32, verdict=verdict, verdict_info=vi)
    up("pick.jpg", "top-pick", {"bucket": "people", "event": "2026-05-12 Rome travel",
                                "description": "joy", "evidence": ["x"]})
    up("keep.jpg", "keep", {"bucket": "travel", "evidence": ["x"]})
    up("keep2.jpg", "keep", {"bucket": "travel", "evidence": ["x"]})
    up("loser.jpg", "duplicate-inferior", {"reason": "tournament", "kept": "keep.jpg",
                                           "evidence": ["tournament-choice"]})
    up("rej.jpg", "reject", {"reason": "quality", "evidence": ["blur-extreme"]},
       status="excluded")
    up("rev.jpg", "needs-review", {"reason": "passes-disagree",
                                   "judgments": {"pass1": {"a": 1}}})
    gid = store.add_group("burst", ["keep.jpg", "loser.jpg"])
    store.set_group(gid, champion="keep.jpg", info={"reason": "sharper",
                                                    "classical_agree": True})
    return src, store

def test_tree_materialized(tmp_path, img_factory):
    src, store = _seed(tmp_path, img_factory)
    out = tmp_path / "curated"
    counts = materialize(src, store, load_config(None), out)
    assert (out / "top-picks" / "pick.jpg").exists()
    assert (out / "albums" / "2026-05-12-rome-travel" / "pick.jpg").exists()
    assert (out / "library" / "people" / "pick.jpg").exists()   # pick is also a keeper
    assert (out / "library" / "travel" / "keep.jpg").exists()
    assert (out / "duplicates" / "group-1" / "loser.jpg").exists()
    chosen = (out / "duplicates" / "group-1" / "CHOSEN.md").read_text()
    assert "keep.jpg" in chosen and "sharper" in chosen
    assert (out / "rejected" / "blurry" / "rej.jpg").exists()
    assert (out / "needs-review" / "rev.jpg").exists()
    assert "passes-disagree" in (out / "needs-review" / "rev.reason.md").read_text()

def test_source_untouched(tmp_path, img_factory):
    src, store = _seed(tmp_path, img_factory)
    import hashlib
    def tree_hash():
        h = hashlib.sha256()
        for p in sorted(src.rglob("*")):
            if p.is_file():
                h.update(p.read_bytes())
        return h.hexdigest()
    before = tree_hash()
    materialize(src, store, load_config(None), tmp_path / "curated")
    assert tree_hash() == before

def test_collision_suffix(tmp_path, img_factory):
    src = tmp_path / "src"
    img_factory(src / "a" / "x.jpg", "scene", seed=1)
    img_factory(src / "b" / "x.jpg", "scene", seed=2)
    store = Store(tmp_path / "c.db")
    for rel, sha in [("a/x.jpg", "11" * 32), ("b/x.jpg", "22" * 32)]:
        store.upsert_photo(rel, kind="photo", status="ok", sha256=sha, size=1,
                           verdict="keep", verdict_info={"bucket": "travel",
                                                         "evidence": []})
    out = tmp_path / "curated"
    materialize(src, store, load_config(None), out)
    files = sorted(p.name for p in (out / "library" / "travel").iterdir())
    assert "x.jpg" in files and "x-222222.jpg" in files
