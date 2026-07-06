import yaml
from curator.providers.catalog import ModelEntry
from curator.providers.registry import (AVG_TOKENS_PER_PHOTO, est_cost_per_1000,
                                        load_registry, tiered)

def test_load_shipped_registry():
    reg = load_registry()
    assert reg[0]["id"] == "ollama/qwen2.5vl:7b"
    assert all("id" in e and "note" in e for e in reg)

def test_user_override_prepends(tmp_path):
    f = tmp_path / "registry.yaml"
    f.write_text(yaml.safe_dump({"recommended": [
        {"id": "ollama/my-model:1b", "note": "mine", "verified": "2026-07-06"}]}))
    reg = load_registry(user_path=f)
    assert reg[0]["id"] == "ollama/my-model:1b"
    assert any(e["id"] == "gpt-4o-mini" for e in reg)

def test_cost_estimate():
    e = ModelEntry("gpt-4o-mini", "openai", "litellm", False,
                   input_cost=1.5e-07, output_cost=6e-07)
    i, o = AVG_TOKENS_PER_PHOTO
    assert est_cost_per_1000(e) == round((1.5e-07 * i + 6e-07 * o) * 1000, 2)
    assert est_cost_per_1000(ModelEntry("x", "p", "litellm", False)) is None

def test_tiered_synthesizes_uninstalled_ollama():
    catalog = [ModelEntry("ollama/qwen2.5vl:7b", "ollama", "ollama", True, 0.0, 0.0),
               ModelEntry("gpt-4o-mini", "openai", "litellm", False, 1.5e-07, 6e-07),
               ModelEntry("openrouter/x/y", "openrouter", "openrouter", False)]
    rec, rest = tiered(catalog, load_registry())
    ids = [e.id for e in rec]
    assert ids[0] == "ollama/qwen2.5vl:7b" and rec[0].installed
    gemma = next(e for e in rec if e.id == "ollama/gemma3:12b")
    assert gemma.installed is False and gemma.local
    assert [e.id for e in rest] == ["openrouter/x/y"]
