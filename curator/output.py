from __future__ import annotations
import json, os, re, shutil
from pathlib import Path
from .db import Store

_REJECT_DIR = {"quality": "blurry", "unsalvageable": "blurry", "accidental": "accidental"}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "unnamed"


def link_or_copy(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _make_thumb(src: Path, sha: str, thumb_root: Path) -> None:
    from PIL import Image, ImageOps
    dst = thumb_root / sha[:2] / f"{sha}.jpg"
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(src) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((256, 256))
            img.save(dst, "JPEG", quality=85)
    except Exception:
        pass  # corrupt or unsupported — skip silently


def _dest_name(rel_path: str, sha256: str, taken: set[str]) -> str:
    name = Path(rel_path).name
    if name in taken:
        stem, ext = Path(name).stem, Path(name).suffix
        name = f"{stem}-{(sha256 or '000000')[:6]}{ext}"
    taken.add(name)
    return name


def required_bytes(store: Store) -> int:
    return sum(p["size"] or 0 for p in store.photos()
               if p["verdict"] in ("top-pick", "keep", "duplicate-inferior",
                                   "reject", "needs-review")
               or p["status"] == "corrupt")


def materialize(source: Path, store: Store, cfg: dict, out_dir: Path) -> dict:
    source, out = Path(source), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    thumb_root = out / "report-assets" / "thumbs"
    counts: dict[str, int] = {}
    taken: dict[str, set] = {}
    placed: dict[str, str] = {}          # rel_path -> primary output path

    def place(rel: str, sha: str, folder: str) -> Path:
        names = taken.setdefault(folder, set())
        dst = out / folder / _dest_name(rel, sha, names)
        link_or_copy(source / rel, dst)
        counts[folder.split("/")[0]] = counts.get(folder.split("/")[0], 0) + 1
        placed.setdefault(rel, str(dst.relative_to(out)))
        if sha:
            _make_thumb(source / rel, sha, thumb_root)
        return dst

    group_of = {}
    for g in store.groups():
        for m in g["members"]:
            group_of[m] = g

    for p in store.photos():
        rel, sha, vi = p["rel_path"], p["sha256"] or "", p["verdict_info"] or {}
        if p["kind"] != "photo":
            continue
        if p["status"] == "corrupt":
            place(rel, sha, "rejected/corrupt")
        elif p["verdict"] == "top-pick":
            place(rel, sha, "top-picks")
            if vi.get("event"):
                place(rel, sha, f"albums/{slug(vi['event'])}")
            place(rel, sha, f"library/{vi['bucket']}")
        elif p["verdict"] == "keep":
            place(rel, sha, f"library/{vi['bucket']}")
        elif p["verdict"] == "duplicate-inferior":
            if vi.get("reason") == "exact-duplicate":
                place(rel, sha, "duplicates/exact")
            else:
                g = group_of.get(rel)
                place(rel, sha, f"duplicates/group-{g['id'] if g else 0}")
        elif p["verdict"] == "reject":
            place(rel, sha, f"rejected/{_REJECT_DIR.get(vi.get('reason'), 'blurry')}")
        elif p["verdict"] == "needs-review":
            dst = place(rel, sha, "needs-review")
            sidecar = dst.with_name(dst.stem + ".reason.md")
            sidecar.write_text(
                f"# Needs your eyes: {rel}\n\n"
                f"**Question:** {vi.get('reason', 'unknown')}\n\n"
                f"**Judgments recorded:**\n\n```json\n"
                f"{json.dumps(vi.get('judgments', vi), indent=2, sort_keys=True)}\n```\n")

    for g in store.groups():
        if not g["champion"]:
            continue
        gdir = out / f"duplicates/group-{g['id']}"
        if gdir.exists():
            info = g["info"] or {}
            (gdir / "CHOSEN.md").write_text(
                f"# Chosen frame: {g['champion']}\n\n"
                f"Kept at: `{placed.get(g['champion'], '(see library)')}`\n\n"
                f"Why: {info.get('reason', '')}\n")
    return counts
