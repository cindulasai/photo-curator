import sys, types
from curator.providers.catalog import (ModelEntry, all_vision_models,
                                       litellm_vision_models, ollama_vision_models,
                                       openrouter_vision_models)
from curator.config import load_config

class FakeResp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p
    def raise_for_status(self): pass

def test_ollama_probe_filters_vision(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResp({"models": [{"name": "qwen2.5vl:7b"}, {"name": "llama3:8b"}]})
    def fake_post(url, json=None, timeout=None):
        if json["model"] == "qwen2.5vl:7b":
            return FakeResp({"capabilities": ["completion", "vision"],
                             "details": {"families": ["qwen2vl"]}})
        return FakeResp({"capabilities": ["completion"],
                         "details": {"families": ["llama"]}})
    monkeypatch.setattr("curator.providers.catalog.requests.get", fake_get)
    monkeypatch.setattr("curator.providers.catalog.requests.post", fake_post)
    out = ollama_vision_models("http://localhost:11434")
    assert [e.id for e in out] == ["ollama/qwen2.5vl:7b"]
    assert out[0].local and out[0].input_cost == 0.0

def test_ollama_down_returns_empty(monkeypatch):
    import requests
    def boom(*a, **k): raise requests.ConnectionError()
    monkeypatch.setattr("curator.providers.catalog.requests.get", boom)
    assert ollama_vision_models("http://localhost:11434") == []

def test_litellm_filter(monkeypatch):
    fake = types.ModuleType("litellm")
    fake.model_cost = {
        "gpt-4o-mini": {"supports_vision": True, "mode": "chat",
                        "litellm_provider": "openai",
                        "input_cost_per_token": 1.5e-07, "output_cost_per_token": 6e-07},
        "gpt-3.5-turbo": {"supports_vision": False, "mode": "chat",
                          "litellm_provider": "openai"},
        "whisper-1": {"supports_vision": False, "mode": "audio_transcription"},
    }
    monkeypatch.setitem(sys.modules, "litellm", fake)
    out = litellm_vision_models()
    assert [e.id for e in out] == ["gpt-4o-mini"]
    assert out[0].provider == "openai" and not out[0].local

def test_openrouter_modality_filter(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResp({"data": [
            {"id": "google/gemini-2.0-flash", "architecture":
             {"input_modalities": ["text", "image"]},
             "pricing": {"prompt": "0.0000001", "completion": "0.0000004"}},
            {"id": "meta/llama-3-8b", "architecture": {"input_modalities": ["text"]},
             "pricing": {}},
        ]})
    monkeypatch.setattr("curator.providers.catalog.requests.get", fake_get)
    out = openrouter_vision_models()
    assert [e.id for e in out] == ["openrouter/google/gemini-2.0-flash"]

def test_all_dedupes(monkeypatch):
    monkeypatch.setattr("curator.providers.catalog.ollama_vision_models",
                        lambda url, timeout=2.0: [ModelEntry("ollama/a", "ollama", "ollama", True)])
    monkeypatch.setattr("curator.providers.catalog.litellm_vision_models",
                        lambda: [ModelEntry("x", "openai", "litellm", False)])
    monkeypatch.setattr("curator.providers.catalog.openrouter_vision_models",
                        lambda timeout=3.0: [ModelEntry("x", "openrouter", "openrouter", False)])
    out = all_vision_models(load_config(None))
    assert [e.id for e in out] == ["ollama/a", "x"]

def test_all_sorted_globally(monkeypatch):
    # ollama returns "zzz/model", litellm returns "aaa/model" — final list must be sorted
    monkeypatch.setattr("curator.providers.catalog.ollama_vision_models",
                        lambda url, timeout=2.0: [ModelEntry("zzz/model", "ollama", "ollama", True)])
    monkeypatch.setattr("curator.providers.catalog.litellm_vision_models",
                        lambda: [ModelEntry("aaa/model", "openai", "litellm", False)])
    monkeypatch.setattr("curator.providers.catalog.openrouter_vision_models",
                        lambda timeout=3.0: [])
    out = all_vision_models(load_config(None))
    assert [e.id for e in out] == ["aaa/model", "zzz/model"]

def test_litellm_not_installed_returns_empty(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    assert litellm_vision_models() == []
