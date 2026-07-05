from curator.db import Store

def test_upsert_update_roundtrip(tmp_path):
    s = Store(tmp_path / "c.db")
    s.upsert_photo("a/x.jpg", kind="photo", status="ok", size=10)
    s.update("a/x.jpg", stage2={"flags": ["blur-soft"], "lap_var_global": 12.5}, stage_done=2)
    row = s.photo("a/x.jpg")
    assert row["stage2"]["flags"] == ["blur-soft"] and row["stage_done"] == 2
    assert s.photo("missing.jpg") is None

def test_photos_filter_and_order(tmp_path):
    s = Store(tmp_path / "c.db")
    for p in ["b.jpg", "a.jpg", "c.jpg"]:
        s.upsert_photo(p, kind="photo", status="ok")
    s.update("c.jpg", status="corrupt")
    rows = s.photos(status="ok")
    assert [r["rel_path"] for r in rows] == ["a.jpg", "b.jpg"]

def test_groups_and_events(tmp_path):
    s = Store(tmp_path / "c.db")
    for p in ["a.jpg", "b.jpg"]:
        s.upsert_photo(p, kind="photo", status="ok")
    gid = s.add_group("burst", ["b.jpg", "a.jpg"])
    s.set_group(gid, champion="a.jpg", info={"reason": "eyes open"})
    g = s.groups()[0]
    assert g["members"] == ["a.jpg", "b.jpg"] and g["champion"] == "a.jpg"
    s.add_event("2026-05-12 travel", 1.0, 2.0, 3, ["a.jpg"])
    assert s.events()[0]["members"] == ["a.jpg"]

def test_meta_and_reopen(tmp_path):
    s = Store(tmp_path / "c.db"); s.set_meta("config_hash", "abc"); s.close()
    s2 = Store(tmp_path / "c.db")
    assert s2.get_meta("config_hash") == "abc"
