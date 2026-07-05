from __future__ import annotations
from collections import Counter
from pathlib import Path
from PIL import Image
from . import prompts


def _thumb(photo: dict, source: Path, out: Path) -> str | None:
    src = Path((photo.get("stage2") or {}).get("work_path") or source / photo["rel_path"])
    if not src.exists():
        return None
    assets = out / "report-assets"
    assets.mkdir(parents=True, exist_ok=True)
    name = f"{(photo['sha256'] or 'x')[:12]}.jpg"
    dst = assets / name
    if not dst.exists():
        with Image.open(src) as img:
            img = img.convert("RGB")
            img.thumbnail((256, 256))
            img.save(dst, "JPEG", quality=80)
    return f"report-assets/{name}"


def write_report(store, cfg: dict, out_dir: Path, source: Path,
                 model_name: str, timings: dict) -> Path:
    out = Path(out_dir)
    photos = store.photos()
    by_verdict = Counter(p["verdict"] for p in photos if p["kind"] == "photo")
    n_photos = sum(1 for p in photos if p["kind"] == "photo")
    picks = [p for p in photos if p["verdict"] == "top-pick"]
    reviews = [p for p in photos if p["verdict"] == "needs-review"]
    keeps = [p for p in photos if p["verdict"] in ("keep", "top-pick")]
    skipped = [p for p in photos if p["status"] == "skipped"]
    corrupt = sum(1 for p in photos if p["status"] == "corrupt")

    L = ["# Curation Report", "",
         f"**{n_photos} photos** -> {len(picks)} top picks, "
         f"{by_verdict.get('keep', 0)} organized, "
         f"{by_verdict.get('duplicate-inferior', 0)} duplicates collapsed, "
         f"{by_verdict.get('reject', 0) + corrupt} rejected, "
         f"**{len(reviews)} need your eyes**.", "",
         f"Model: `{model_name}` - prompts: "
         f"{', '.join(f'{k} v{v}' for k, v in sorted(prompts.versions().items()))} - "
         f"total {sum(timings.values()):.0f}s", ""]

    L += ["## Top picks", ""]
    for p in sorted(picks, key=lambda p: -(p['verdict_info'].get('scores', {})
                                           .get('composite', 0))):
        vi = p["verdict_info"]
        t = _thumb(p, source, out)
        img = f"![]({t}) " if t else ""
        L.append(f"- {img}**{p['rel_path']}** - {vi.get('description', '')} "
                 f"_(event: {vi.get('event', '-')}, score "
                 f"{vi.get('scores', {}).get('composite', 0):.2f})_")
    L.append("")

    L += ["## Needs your eyes", "",
          f"{len(reviews)} photos ({len(reviews) * 100 // max(1, n_photos)}% of library):", ""]
    for p in reviews:
        vi = p["verdict_info"] or {}
        _thumb(p, source, out)
        L.append(f"- **{p['rel_path']}** - {vi.get('reason', '?')} "
                 f"(see `needs-review/`)")
    L.append("")

    L += ["## Double-check these", "",
          "Medium-confidence decisions that executed automatically:", ""]
    med = [p for p in photos if (p["verdict_info"] or {}).get("tier") == "medium"]
    by_type = Counter((p["verdict"], (p["verdict_info"] or {}).get("bucket"))
                      for p in med)
    for (verdict, bucket), n in sorted(by_type.items(), key=lambda x: str(x[0])):
        L.append(f"- {n} x {verdict} -> {bucket}")
    L.append("")

    L += ["## Events", "", "| event | photos | significance |", "|---|---|---|"]
    for e in store.events():
        L.append(f"| {e['name']} | {len(e['members'])} | {e['significance']}/4 |")
    L.append("")

    L += ["## Statistics", "", "| stage | seconds |", "|---|---|"]
    for k, v in sorted(timings.items()):
        L.append(f"| {k} | {v:.1f} |")
    L += ["", "| bucket | keeps |", "|---|---|"]
    bcounts = Counter((p["verdict_info"] or {}).get("bucket") for p in keeps)
    for b, n in bcounts.most_common():
        L.append(f"| {b} | {n} |")
    misc = bcounts.get("everyday-misc", 0)
    if keeps and misc / len(keeps) > 0.15:
        L += ["", f"WARNING: {misc * 100 // len(keeps)}% of keepers landed in "
              "everyday-misc - consider adding custom buckets or a stronger model."]
    L.append("")

    L += ["## Skipped files", ""]
    for p in skipped:
        L.append(f"- {p['rel_path']} ({p['kind']})")
    L.append("")

    path = out / "REPORT.md"
    path.write_text("\n".join(L))
    return path
