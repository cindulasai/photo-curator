from __future__ import annotations
import csv, math
from collections import Counter
from datetime import datetime, timezone
from importlib.resources import files


def haversine_km(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((lat2 - lat1) / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def _cities() -> list[tuple[str, float, float]]:
    text = files("curator").joinpath("data/cities.csv").read_text()
    return [(r["city"], float(r["lat"]), float(r["lon"]))
            for r in csv.DictReader(text.splitlines())]


def _nearest_city(centroid, max_km=100.0):
    best, dist = None, max_km
    for name, lat, lon in _cities():
        d = haversine_km(centroid, (lat, lon))
        if d <= dist:
            best, dist = name, d
    return best


def _gps(p):
    g = (p.get("exif") or {}).get("gps")
    return tuple(g) if g else None


def _modal_location(photos):
    cells = Counter(
        (round(g[0], 1), round(g[1], 1))
        for g in (_gps(p) for p in photos) if g)
    return cells.most_common(1)[0][0] if cells else None


def cluster_events(photos: list[dict], cfg: dict) -> list[dict]:
    e = cfg["events"]
    photos = sorted(photos, key=lambda p: (p["ts"], p["rel_path"]))
    modal = _modal_location(photos)
    clusters, cur = [], []
    for p in photos:
        if cur:
            prev = cur[-1]
            gap = p["ts"] - prev["ts"] > e["gap_hours"] * 3600
            g1, g2 = _gps(prev), _gps(p)
            jump = bool(g1 and g2) and haversine_km(g1, g2) > e["gps_jump_km"]
            if gap or jump:
                clusters.append(cur)
                cur = []
        cur.append(p)
    if cur:
        clusters.append(cur)

    out = []
    for members in clusters:
        n = len(members)
        start, end = members[0]["ts"], members[-1]["ts"]
        gps_pts = [g for g in (_gps(p) for p in members) if g]
        centroid = (sum(g[0] for g in gps_pts) / len(gps_pts),
                    sum(g[1] for g in gps_pts) / len(gps_pts)) if gps_pts else None
        away = 1 if (centroid and modal and
                     haversine_km(centroid, modal) >= e["gps_jump_km"]) else 0
        sig = min(4, (n >= 20) + (n >= 60) + away + (end - start >= 172800))
        buckets = Counter(p["verdict_info"]["bucket"] for p in members
                          if p.get("verdict_info", {}).get("bucket")
                          and p["verdict_info"]["bucket"] not in
                          ("screenshots", "documents-receipts",
                           "whiteboards-notes", "products-shopping"))
        dom = buckets.most_common(1)[0][0] if buckets else "everyday-misc"
        all_mtime = all(p.get("ts_source") == "mtime" for p in members)
        if all_mtime:
            name = f"undated {dom}"
        else:
            date = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%d")
            city = _nearest_city(centroid) if centroid else None
            name = " ".join(x for x in [date, city, dom] if x)
        out.append({"name": name, "start_ts": start, "end_ts": end,
                    "significance": sig,
                    "members": sorted(p["rel_path"] for p in members)})
    return out
