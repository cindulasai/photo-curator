from pathlib import Path
import yaml
from curator.config import load_config, config_hash, active_buckets, DEFAULTS

def test_defaults_load_without_file():
    cfg = load_config(None)
    assert cfg["model"] == "qwen2.5vl:7b"
    assert cfg["triage"]["blur_sharp_min"] == 60.0
    assert abs(sum(cfg["rubric"].values()) - 1.0) < 1e-9

def test_user_file_deep_merges(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"triage": {"blur_sharp_min": 80}, "model": "gemma3:12b"}))
    cfg = load_config(p)
    assert cfg["model"] == "gemma3:12b"
    assert cfg["triage"]["blur_sharp_min"] == 80
    assert cfg["triage"]["blur_extreme_max"] == 25.0  # untouched default survives

def test_config_hash_stable_and_sensitive():
    a, b = load_config(None), load_config(None)
    assert config_hash(a) == config_hash(b)
    b["triage"]["blur_sharp_min"] = 61.0
    assert config_hash(a) != config_hash(b)

def test_active_buckets_disable_and_custom(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"buckets": {
        "disable": ["vehicles"],
        "custom": [{"key": "my-artwork", "description": "Paintings and drawings made by me"}]}}))
    keys = [b["key"] for b in active_buckets(load_config(p))]
    assert "vehicles" not in keys and "my-artwork" in keys and "everyday-misc" in keys
    art = [b for b in active_buckets(load_config(p)) if b["key"] == "my-artwork"][0]
    assert art["utility"] is False  # custom default
