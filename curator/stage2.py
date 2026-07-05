from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageOps

from . import metrics
from .db import Store
from .grouping import build_groups, phash64


def _working_copy(src_file: Path, out: Path, edge: int) -> Image.Image:
    with Image.open(src_file) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((edge, edge))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "JPEG", quality=90)
        return img.copy()


def _flags(s2: dict, photo: dict, t: dict) -> list[str]:
    flags = []
    lo, hi = s2["lap_var_global"], s2["lap_var_center"]
    if max(lo, hi) < t["blur_extreme_max"]:
        flags.append("blur-extreme")
    elif max(lo, hi) < t["blur_sharp_min"]:
        flags.append("blur-soft")
    if s2["pct_black"] >= t["black_extreme"] or s2["pct_white"] >= t["white_extreme"]:
        flags.append("exposure-extreme")
    elif s2["pct_black"] >= t["exposure_poor"] or s2["pct_white"] >= t["exposure_poor"]:
        flags.append("exposure-poor")
    fmt = "PNG" if photo["rel_path"].lower().endswith(".png") else "JPEG"
    if metrics.is_screenshot_candidate(photo["width"], photo["height"],
                                       (photo.get("exif") or {}).get("make"), fmt):
        flags.append("screenshot-candidate")
    if s2["white_ratio"] >= t["doc_white_min"] and s2["edge_density"] >= t["doc_edge_min"]:
        flags.append("document-candidate")
    return flags


def run_stage2(source: Path, store: Store, cfg: dict, workdir: Path) -> dict:
    source, workdir = Path(source), Path(workdir)
    t = cfg["triage"]
    summary = {"auto_rejected": 0, "groups": 0, "flagged": 0}

    for photo in store.photos(status="ok"):
        if photo["stage_done"] >= 2:
            continue
        rel = photo["rel_path"]
        try:
            work = workdir / f"{photo['sha256']}_{Path(rel).stem}.jpg"
            img = _working_copy(source / rel, work, t["working_edge_px"])
            gray = metrics.to_gray(img)
            g, c = metrics.blur_scores(gray)
            pb, pw = metrics.exposure_stats(gray)
            wr, ed = metrics.doc_stats(gray)
            s2 = {"lap_var_global": round(g, 2), "lap_var_center": round(c, 2),
                  "pct_black": round(pb, 2), "pct_white": round(pw, 2),
                  "white_ratio": round(wr, 4), "edge_density": round(ed, 4),
                  "faces": metrics.face_count(gray), "phash": phash64(img),
                  "work_path": str(work)}
            s2["flags"] = _flags(s2, photo, t)
            if s2["flags"]:
                summary["flagged"] += 1
            mp = photo["width"] * photo["height"] / 1e6
            second = ("exposure-extreme" if "exposure-extreme" in s2["flags"]
                      else f"tiny-{mp:.2f}MP" if mp < t["min_megapixels"] else None)
            if "blur-extreme" in s2["flags"] and second and s2["faces"] == 0:
                store.update(rel, stage2=s2, stage_done=2, status="excluded",
                             verdict="reject",
                             verdict_info={"reason": "unsalvageable",
                                           "evidence": ["blur-extreme", second, "no-faces"]})
                summary["auto_rejected"] += 1
            else:
                store.update(rel, stage2=s2, stage_done=2)
        except Exception as exc:                       # never crash the run
            store.update(rel, stage_done=2, verdict="needs-review",
                         verdict_info={"reason": "pipeline-error", "evidence": [repr(exc)]})

    if not store.groups():
        photos = [p for p in store.photos(status="ok")
                  if p["stage_done"] >= 2 and p.get("stage2")]
        for grp in build_groups(photos, cfg):
            store.add_group(grp["kind"], grp["members"])
            summary["groups"] += 1
    return summary
