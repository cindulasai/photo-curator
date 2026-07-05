import json
from pathlib import Path
from curator.cli import main, run_pipeline
from curator.model import MockModel
from tests.test_stage3 import _router

def _factory(cfg):
    return MockModel(_router)

def _mk_source(tmp_path, img_factory):
    src = tmp_path / "src"
    img_factory(src / "a.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:00")
    img_factory(src / "b.jpg", "portrait", seed=2, exif_dt="2026:05:12 10:01:00")
    img_factory(src / "junk.jpg", "black", blur=15)
    return src

class _Args:
    def __init__(self, source, out, **kw):
        self.source, self.out = str(source), str(out)
        self.config = kw.get("config"); self.model = kw.get("model")
        self.fast = kw.get("fast", False); self.resume = kw.get("resume", False)
        self.dry_run = kw.get("dry_run", False)
        self.skip_qualification = kw.get("skip_qualification", True)

def test_full_run_produces_outputs(tmp_path, img_factory):
    src = _mk_source(tmp_path, img_factory)
    out = tmp_path / "curated"
    rc = run_pipeline(_Args(src, out), _factory)
    assert rc == 0
    assert (out / "REPORT.md").exists() and (out / "manifest.json").exists()
    assert (out / "curation.db").exists()
    m = json.loads((out / "manifest.json").read_text())
    assert m["run"]["model"] == "mock"
    verdicts = {p["rel_path"]: p["verdict"] for p in m["photos"]}
    assert verdicts["junk.jpg"] == "reject"          # stage2 auto-reject
    assert verdicts["a.jpg"] in ("keep", "top-pick")

def test_dry_run_stops_before_llm(tmp_path, img_factory, capsys):
    src = _mk_source(tmp_path, img_factory)
    rc = run_pipeline(_Args(src, tmp_path / "c2", dry_run=True), _factory)
    assert rc == 0
    assert "survivors" in capsys.readouterr().out
    assert not (tmp_path / "c2" / "REPORT.md").exists()

def test_resume_guard_refuses_config_change(tmp_path, img_factory):
    src = _mk_source(tmp_path, img_factory)
    out = tmp_path / "c3"
    assert run_pipeline(_Args(src, out), _factory) == 0
    import yaml
    cfgfile = tmp_path / "other.yaml"
    cfgfile.write_text(yaml.safe_dump({"triage": {"blur_sharp_min": 99}}))
    rc = run_pipeline(_Args(src, out, config=str(cfgfile), resume=True), _factory)
    assert rc == 3

def test_main_argparse_smoke(tmp_path, img_factory):
    src = _mk_source(tmp_path, img_factory)
    rc = main(["run", str(src), "--out", str(tmp_path / "c4"),
               "--skip-qualification", "--dry-run"])
    assert rc == 0
