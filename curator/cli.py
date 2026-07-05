from __future__ import annotations
import argparse, shutil, sys, time
from datetime import datetime, timezone
from pathlib import Path
from .config import config_hash, load_config
from .db import Store
from .inventory import run_stage1, source_tree_hash
from .manifest import write_manifest
from .model import ModelError, OllamaModel
from .output import materialize, required_bytes
from .qualification import run_gate
from .report import write_report
from .stage2 import run_stage2
from .stage3 import run_stage3
from .stage4 import run_stage4

ALTERNATIVES = "qwen2.5vl:7b, gemma3:12b, llama3.2-vision:11b"


def _default_factory(cfg):
    return OllamaModel(cfg["model"], cfg["ollama_url"], cfg["llm"]["timeout_s"],
                       cfg["llm"]["seed"], cfg["llm"]["analyze_edge_px"])


def _default_out(source: Path, store: Store) -> Path:
    ts = [p["ts"] for p in store.photos(status="ok") if p["ts_source"] == "exif"]
    if ts:
        d = datetime.fromtimestamp(max(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        return source.parent / f"curated-{d}"
    return source.parent / "curated-run"


def run_pipeline(args, model_factory=_default_factory, steer=None, notify=None) -> int:
    say = notify or print
    cfg = load_config(Path(args.config) if args.config else None)
    if args.model:
        cfg["model"] = args.model
    source = Path(args.source).resolve()
    if not source.is_dir():
        print(f"source is not a directory: {source}", file=sys.stderr)
        return 1

    out = Path(args.out).resolve() if args.out else None
    if out is None:
        probe = source.parent / ".photo-curator-probe.db"
        tmp_store = Store(probe)
        run_stage1(source, tmp_store, cfg)
        out = _default_out(source, tmp_store)
        tmp_store.close()
        probe.unlink()
    out.mkdir(parents=True, exist_ok=True)
    store = Store(out / "curation.db")

    chash, shash = config_hash(cfg), source_tree_hash(source)
    prev_c, prev_s = store.get_meta("config_hash"), store.get_meta("source_hash")
    if prev_c is not None:
        mismatches = [n for n, a, b in [("config", prev_c, chash),
                                        ("source tree", prev_s, shash)] if a != b]
        if mismatches and args.resume:
            print(f"refusing to resume: {', '.join(mismatches)} changed since the "
                  f"run started. Start a fresh --out directory.", file=sys.stderr)
            return 3
        if mismatches and not args.resume:
            print(f"out dir already contains a run with different "
                  f"{', '.join(mismatches)}. Use a new --out.", file=sys.stderr)
            return 3
    store.set_meta("config_hash", chash)
    store.set_meta("source_hash", shash)

    timings = {}
    t0 = time.time()
    s1 = run_stage1(source, store, cfg)
    timings["stage1_s"] = time.time() - t0
    say(f"[stage 1/5] {s1['photos']} photos, {s1['skipped']} skipped, "
        f"{s1['corrupt']} corrupt, {s1['exact_dupes']} exact dupes")

    t0 = time.time()
    s2 = run_stage2(source, store, cfg, out / ".work")
    timings["stage2_s"] = time.time() - t0
    survivors = sum(1 for p in store.photos(status="ok") if p["stage_done"] >= 2)
    say(f"[stage 2/5] {s2['auto_rejected']} auto-rejected, {s2['groups']} groups, "
        f"{survivors} survivors")

    if args.dry_run:
        say(f"dry-run: {survivors} survivors of {s1['photos']} photos would reach "
            f"the LLM - est {survivors * 8 / 3600:.1f}h at 8 s/photo")
        store.close()
        return 0

    model = model_factory(cfg)
    if not args.skip_qualification:
        passed, results = run_gate(model, cfg)
        if not passed:
            ok_n = sum(r["ok"] for r in results)
            print(f"Model {model.name()} failed qualification ({ok_n}/10). "
                  f"This model cannot power reliable curation.\n"
                  f"Tested alternatives: {ALTERNATIVES}", file=sys.stderr)
            for r in results:
                print(f"  {'PASS' if r['ok'] else 'FAIL'} {r['file']} "
                      f"{r['check']}: expected {r['expect']}, got {r['got']}",
                      file=sys.stderr)
            return 2

    if args.fast:
        for p in store.photos(status="ok"):
            if (p["stage_done"] == 2 and p["verdict"] is None
                    and p["stage2"]["faces"] == 0 and p["stage2"]["flags"]):
                store.update(p["rel_path"], stage3={"fast_skipped": True}, stage_done=3)

    done = {"n": 0, "t0": time.time()}
    def progress(msg):
        done["n"] += 1
        if done["n"] % 25 == 0:
            i, total = msg.split("/")
            rate = (time.time() - done["t0"]) / done["n"]
            eta = (int(total) - int(i)) * rate
            say(f"[stage 3/5] {msg} analyzed - ETA {eta / 60:.0f}m")

    t0 = time.time()
    try:
        run_stage3(source, store, cfg, model, progress, steer=steer)
    except ModelError as exc:
        print(f"Run interrupted - {exc}\nResume with: photo-curator run {source} "
              f"--out {out} --resume", file=sys.stderr)
        return 4
    timings["stage3_s"] = time.time() - t0

    t0 = time.time()
    try:
        s4 = run_stage4(source, store, cfg, model)
    except ModelError as exc:
        print(f"Run interrupted in ranking - {exc}\nResume with: photo-curator run "
              f"{source} --out {out} --resume", file=sys.stderr)
        return 4
    timings["stage4_s"] = time.time() - t0
    say(f"[stage 4/5] {s4['top_picks']} top picks across {s4['events']} events")

    need = required_bytes(store)
    free = shutil.disk_usage(out).free
    if need > free:
        print(f"insufficient disk: need {need} bytes, have {free}", file=sys.stderr)
        return 5

    t0 = time.time()
    materialize(source, store, cfg, out)
    write_report(store, cfg, out, source, model.name(), timings)
    timings["stage5_s"] = time.time() - t0
    write_manifest(store, cfg, out, model.name(), timings, shash)

    reviews = len(store.photos(verdict="needs-review"))
    say(f"[stage 5/5] done -> {out}\n{reviews} photos need your eyes - "
        f"see {out / 'REPORT.md'}")
    store.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="photo-curator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="curate a folder of photos")
    r.add_argument("source")
    r.add_argument("--out"); r.add_argument("--config"); r.add_argument("--model")
    r.add_argument("--fast", action="store_true")
    r.add_argument("--resume", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--skip-qualification", action="store_true")
    q = sub.add_parser("qualify", help="test a model against the calibration set")
    q.add_argument("--config"); q.add_argument("--model")
    q.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "qualify":
        cfg = load_config(Path(args.config) if args.config else None)
        if args.model:
            cfg["model"] = args.model
        model = _default_factory(cfg)
        passed, results = run_gate(model, cfg, force=args.force)
        for r_ in results:
            print(f"{'PASS' if r_['ok'] else 'FAIL'} {r_['file']} {r_['check']}: "
                  f"expected {r_['expect']}, got {r_['got']}")
        print("QUALIFIED" if passed else f"REFUSED - alternatives: {ALTERNATIVES}")
        return 0 if passed else 2
    return run_pipeline(args)


if __name__ == "__main__":
    sys.exit(main())
