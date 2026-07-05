import json
from curator.config import load_config
from curator.model import MockModel
from curator.qualification import run_gate

def _smart_handler(paths, prompt, schema):
    name = paths[0].name
    fatal = "yes" if name.startswith(("blur", "black")) else "no"
    shot = "yes" if name.startswith("shot") else "no"
    doc = "yes" if name.startswith("receipt") else "no"
    return {"bucket": {"primary": "everyday-misc", "confidence": 0.9, "alternates": []},
            "tags": [], "description": "x",
            "people": {"count": 0, "eyes_closed": "n/a", "expression_quality": "n/a"},
            "utility": {"is_screenshot": shot, "is_document": doc, "is_accidental": "no"},
            "quality_judgment": {"fatal": fatal, "note": "x"},
            "rubric": {"emotional": 0, "people_engagement": 0, "composition_light": 1,
                       "scene_appeal": 1, "novelty": 0, "justifications": {}}}

def _dumb_handler(paths, prompt, schema):
    out = _smart_handler(paths, prompt, schema)
    out["quality_judgment"] = {"fatal": "no", "note": "x"}   # misses all 3 fatal checks
    return out

def test_good_model_passes(tmp_path):
    ok, results = run_gate(MockModel(_smart_handler), load_config(None), cache_dir=tmp_path)
    assert ok and len(results) == 10 and all(r["ok"] for r in results)

def test_weak_model_refused(tmp_path):
    ok, results = run_gate(MockModel(_dumb_handler), load_config(None), cache_dir=tmp_path)
    assert not ok and sum(not r["ok"] for r in results) == 3

def test_cache_hit_skips_calls(tmp_path):
    m = MockModel(_smart_handler)
    run_gate(m, load_config(None), cache_dir=tmp_path)
    n = len(m.calls)
    ok, _ = run_gate(m, load_config(None), cache_dir=tmp_path)
    assert ok and len(m.calls) == n               # no new calls
    cached = json.loads((tmp_path / "qualification.json").read_text())
    assert cached["mock"]["passed"] is True
