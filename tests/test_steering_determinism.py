"""Spec §12.4: a run steered at photo k equals a fresh run whose config
changes at photo k. With k=0 that means: steered run == config-from-start."""
import argparse, json
from curator.cli import run_pipeline
from curator.chat.steering import SteeringQueue
from curator.config import load_config
from curator.model import MockModel
from tests.test_runner import _handler
from tests.test_qualification import _smart_handler

def _h(paths, prompt, schema):
    name = paths[0].name if paths else ""
    if name.endswith(".png") and name.split("_")[0] in (
            "blur", "black", "shot", "receipt", "scene"):
        return _smart_handler(paths, prompt, schema)
    return _handler(paths, prompt, schema)

def _args(src, out):
    return argparse.Namespace(source=str(src), out=str(out), config=None,
                              model=None, fast=False, resume=False,
                              dry_run=False, skip_qualification=True)

def _manifest(out):
    m = json.loads((out / "manifest.json").read_text())
    m.pop("timings", None)
    return m

def test_steer_at_zero_equals_config_from_start(tmp_path, img_factory):
    src = tmp_path / "src"
    for i in range(3):
        img_factory(src / f"p{i}.jpg", "scene", seed=i,
                    exif_dt=f"2026:05:12 10:0{i}:00")
    delta = [{"path": "prompt_suffix", "op": "append",
              "value": "KIDS FIRST", "why": ""}]
    # Run A: steered from photo 0
    steer = SteeringQueue()
    steer.push(delta)
    a_out = tmp_path / "a"
    assert run_pipeline(_args(src, a_out), model_factory=lambda c: MockModel(_h),
                        steer=steer) == 0
    # Run B: same delta baked into the config file from the start
    import yaml
    from curator.chat.deltas import apply_deltas
    cfg_f = tmp_path / "cfg.yaml"
    cfg_f.write_text(yaml.safe_dump(apply_deltas(load_config(None), delta)))
    b_out = tmp_path / "b"
    b_args = _args(src, b_out)
    b_args.config = str(cfg_f)
    assert run_pipeline(b_args, model_factory=lambda c: MockModel(_h)) == 0
    ma, mb = _manifest(a_out), _manifest(b_out)
    # config hashes legitimately differ (steering is not in the file config);
    # every DECISION must be identical
    ma.pop("config_hash", None); mb.pop("config_hash", None)
    ma.pop("config", None); mb.pop("config", None)
    ma.get("run", {}).pop("config_hash", None)
    mb.get("run", {}).pop("config_hash", None)
    assert ma == mb
