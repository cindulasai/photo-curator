from curator.config import load_config
from curator.events import cluster_events, haversine_km

ROME, PARIS = (41.89, 12.48), (48.86, 2.35)

def _p(rel, ts, gps=None, bucket="travel", ts_source="exif"):
    return {"rel_path": rel, "ts": ts, "ts_source": ts_source,
            "exif": {"gps": list(gps)} if gps else {},
            "verdict_info": {"bucket": bucket}}

def test_haversine_sane():
    assert 1050 < haversine_km(ROME, PARIS) < 1150

def test_time_gap_splits():
    base = 1778916000.0     # 2026-05-16 UTC-ish
    photos = [_p("a.jpg", base), _p("b.jpg", base + 3600),
              _p("c.jpg", base + 3600 * 10)]                    # 9h later -> new event
    evs = cluster_events(photos, load_config(None))
    assert len(evs) == 2 and evs[0]["members"] == ["a.jpg", "b.jpg"]

def test_gps_jump_splits_and_names_city():
    base = 1778916000.0
    photos = [_p("r1.jpg", base, ROME), _p("r2.jpg", base + 60, ROME),
              _p("p1.jpg", base + 120, PARIS)]                  # same minute, 1100km away
    evs = cluster_events(photos, load_config(None))
    assert len(evs) == 2
    assert "Rome" in evs[0]["name"] and "travel" in evs[0]["name"]
    assert "Paris" in evs[1]["name"]

def test_significance_formula():
    base = 1778916000.0
    photos = [_p(f"x{i:02d}.jpg", base + i * 60, (10.0, 10.0)) for i in range(25)]
    photos += [_p(f"home{i:02d}.jpg", base + 10 * 86400 + i, ROME) for i in range(50)]
    evs = cluster_events(photos, load_config(None))
    trip = [e for e in evs if "x00.jpg" in e["members"]][0]
    assert trip["significance"] >= 2                             # n>=20 and away
