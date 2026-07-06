import pytest
from curator.chat.deltas import DeltaError, apply_deltas, describe, validate_deltas
from curator.config import load_config

def test_set_and_append():
    cfg = load_config(None)
    out = apply_deltas(cfg, [
        {"path": "triage.blur_sharp_min", "value": 80},
        {"path": "buckets.disable", "op": "append", "value": "food-drink"},
        {"path": "prompt_suffix", "op": "append",
         "value": "Weight photos of children highly."},
    ])
    assert out["triage"]["blur_sharp_min"] == 80
    assert "food-drink" in out["buckets"]["disable"]
    assert out["prompt_suffix"] == ["Weight photos of children highly."]
    assert cfg["triage"]["blur_sharp_min"] == 60.0          # original untouched

def test_append_dedupes_and_defaults_op():
    cfg = load_config(None)
    d = validate_deltas({"deltas": [{"path": "skip_globs", "value": "WhatsApp/*"}]})
    assert d[0]["op"] == "append"                            # list paths default to append
    out = apply_deltas(cfg, d + d)
    assert out["skip_globs"] == ["WhatsApp/*"]

def test_whitelist_rejects():
    for bad in ["model", "ollama_url", "llm.seed", "events.gap_hours", "nonsense"]:
        with pytest.raises(DeltaError):
            validate_deltas({"deltas": [{"path": bad, "value": 1}]})

def test_bad_shape_rejects():
    with pytest.raises(DeltaError):
        validate_deltas({"deltas": [{"path": "triage.blur_sharp_min"}]})   # no value
    with pytest.raises(DeltaError):
        validate_deltas({"deltas": [{"path": "rubric.emotional", "op": "delete", "value": 0}]})

def test_describe_human_readable():
    lines = describe([{"path": "triage.blur_sharp_min", "op": "set", "value": 80,
                       "why": "stricter blur"}])
    assert lines == ["set triage.blur_sharp_min -> 80  (stricter blur)"]
