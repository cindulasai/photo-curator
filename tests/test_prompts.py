import pytest
from curator.config import load_config
from curator.prompts import render, load_schema, versions

def test_render_substitutes_taxonomy():
    cfg = load_config(None)
    p = render("analyze_photo", cfg)
    assert "everyday-misc" in p and "Genuinely uncategorizable" in p
    assert "<<" not in p

def test_custom_bucket_reaches_prompt(tmp_path):
    import yaml
    f = tmp_path / "c.yaml"
    f.write_text(yaml.safe_dump({"buckets": {"custom": [
        {"key": "my-artwork", "description": "Paintings and drawings made by me"}]}}))
    assert "my-artwork" in render("analyze_photo", load_config(f))

def test_unfilled_placeholder_raises():
    with pytest.raises(ValueError):
        render("tournament", load_config(None))   # requires COUNT sub

def test_schemas_load_and_versions():
    for name in ["analyze", "reworded", "tournament", "verification"]:
        s = load_schema(name)
        assert s["type"] == "object" and s["additionalProperties"] is False
    v = versions()
    assert v["analyze_photo"] == 1 and v["json_repair"] == 1
