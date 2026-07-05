from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:                                   # HEIC support optional at runtime
    pass

from .db import Store

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".raf", ".rw2"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".3gp"}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_tree_hash(source: Path) -> str:
    lines = []
    for p in sorted(source.rglob("*")):
        if p.is_file() and not p.is_symlink():
            st = p.stat()
            lines.append(f"{p.relative_to(source)}|{st.st_size}|{st.st_mtime_ns}")
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _dms_to_deg(dms, ref):
    deg = float(dms[0]) + float(dms[1]) / 60 + float(dms[2]) / 3600
    return -deg if ref in ("S", "W") else deg


def _extract_exif(img: Image.Image) -> dict:
    ex = img.getexif()
    out = {"make": ex.get(271), "model": ex.get(272), "orientation": ex.get(274)}
    try:
        gps = ex.get_ifd(34853)
        if gps and 2 in gps and 4 in gps:
            out["gps"] = [_dms_to_deg(gps[2], gps.get(1, "N")),
                          _dms_to_deg(gps[4], gps.get(3, "E"))]
    except Exception:
        pass
    dt = ex.get(36867)
    if not dt:
        try:
            ifd = ex.get_ifd(0x8769)
            dt = ifd.get(36867) or ifd.get(36868)
        except Exception:
            dt = None
    out["datetime_original"] = dt
    return out


def _parse_exif_ts(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y:%m:%d %H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def run_stage1(source: Path, store: Store, cfg: dict) -> dict:
    source = Path(source)
    counts = {"photos": 0, "skipped": 0, "corrupt": 0, "exact_dupes": 0}
    files = sorted(p for p in source.rglob("*") if p.is_file() and not p.is_symlink())
    stems_with_photo = {p.with_suffix("").name.lower()
                        for p in files if p.suffix.lower() in PHOTO_EXTS}
    sha_map: dict[str, list[str]] = {}

    for p in files:
        rel = str(p.relative_to(source))
        existing = store.photo(rel)
        if existing and existing["stage_done"] >= 1:
            if existing["kind"] == "photo" and existing["status"] in ("ok", "excluded"):
                sha_map.setdefault(existing["sha256"], []).append(rel)
            continue                                  # resume: already inventoried
        st = p.stat()
        ext = p.suffix.lower()
        base = dict(size=st.st_size, mtime=st.st_mtime)
        if ext in PHOTO_EXTS:
            try:
                with Image.open(p) as img:
                    img.load()
                    exif = _extract_exif(img)
                    w, h = img.size
            except Exception:
                store.upsert_photo(rel, kind="photo", status="corrupt",
                                   stage_done=1, **base)
                counts["corrupt"] += 1
                continue
            ts = _parse_exif_ts(exif.get("datetime_original"))
            ts_source = "exif" if ts else "mtime"
            sha = file_sha256(p)
            store.upsert_photo(rel, kind="photo", status="ok", sha256=sha,
                               width=w, height=h, ts=ts or st.st_mtime,
                               ts_source=ts_source, exif=exif, stage_done=1, **base)
            sha_map.setdefault(sha, []).append(rel)
            counts["photos"] += 1
        elif ext in RAW_EXTS:
            sib = p.with_suffix("").name.lower() in stems_with_photo
            store.upsert_photo(rel, kind="raw", status="skipped", stage_done=1,
                               raw_sibling="jpeg-sibling" if sib else None, **base)
            counts["skipped"] += 1
        else:
            kind = "video" if ext in VIDEO_EXTS else "other"
            store.upsert_photo(rel, kind=kind, status="skipped", stage_done=1, **base)
            counts["skipped"] += 1

    for sha, rels in sorted(sha_map.items()):
        if len(rels) > 1:
            keeper = sorted(rels)[0]
            for loser in sorted(rels)[1:]:
                if (store.photo(loser) or {}).get("verdict"):
                    continue                          # resume: already marked
                store.update(loser, status="excluded", verdict="duplicate-inferior",
                             verdict_info={"reason": "exact-duplicate",
                                           "evidence": ["sha256-identical"],
                                           "kept": keeper})
                counts["exact_dupes"] += 1
    return counts
