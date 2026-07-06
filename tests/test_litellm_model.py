# tests/test_litellm_model.py
import sys, types
import pytest
from curator.model import InvalidOutput, ModelError
from tests.conftest import make_image

SCHEMA = {"type": "object", "properties": {"ok": {"type": "string", "enum": ["yes", "no"]}},
          "required": ["ok"], "additionalProperties": False}

class FakeUsageResp:
    def __init__(self, content):
        msg = types.SimpleNamespace(content=content)
        self.choices = [types.SimpleNamespace(message=msg)]

def _install_fake_litellm(monkeypatch, completion):
    fake = types.ModuleType("litellm")
    fake.completion = completion
    fake.completion_cost = lambda resp: 0.001
    class RateLimitError(Exception): pass
    fake.RateLimitError = RateLimitError
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake

class FakeKeystore:
    def get(self, provider): return "sk-test"

def _model():
    from curator.providers.litellm_model import LiteLLMModel
    return LiteLLMModel("gpt-4o-mini", FakeKeystore())

def test_happy_path_vision_message(tmp_path, monkeypatch):
    img = make_image(tmp_path / "a.jpg", "scene")
    sent = {}
    def completion(**kw):
        sent.update(kw)
        return FakeUsageResp('{"ok": "yes"}')
    fake_litellm = _install_fake_litellm(monkeypatch, completion)
    m = _model()
    assert m.analyze([img], "prompt", SCHEMA) == {"ok": "yes"}
    content = sent["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "prompt"}
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert sent["temperature"] == 0
    assert "api_key" not in sent
    assert fake_litellm.openai_key == "sk-test"
    assert sent["response_format"]["json_schema"]["schema"] == SCHEMA
    assert m.cost_usd == pytest.approx(0.001)

def test_text_only_call(monkeypatch):
    sent = {}
    def completion(**kw):
        sent.update(kw)
        return FakeUsageResp('{"ok": "no"}')
    _install_fake_litellm(monkeypatch, completion)
    assert _model().analyze([], "just text", SCHEMA) == {"ok": "no"}
    assert sent["messages"][0]["content"] == "just text"

def test_schema_fallback_on_unsupported(monkeypatch):
    calls = []
    def completion(**kw):
        calls.append(kw)
        if "response_format" in kw:
            raise ValueError("response_format is not supported for this model")
        return FakeUsageResp('{"ok": "yes"}')
    _install_fake_litellm(monkeypatch, completion)
    m = _model()
    assert m.analyze([], "p", SCHEMA) == {"ok": "yes"}
    assert "response_format" not in calls[-1]
    assert "ONLY a single valid JSON object" in calls[-1]["messages"][0]["content"]

def test_rate_limit_backoff_then_error(monkeypatch):
    def completion(**kw):
        raise sys.modules["litellm"].RateLimitError("429")
    _install_fake_litellm(monkeypatch, completion)
    from curator.providers import litellm_model
    monkeypatch.setattr(litellm_model, "_sleep", lambda s: None)
    with pytest.raises(ModelError):
        _model().analyze([], "p", SCHEMA)

def test_repair_then_invalid(monkeypatch):
    def completion(**kw):
        return FakeUsageResp('{"ok": "MAYBE"}')
    _install_fake_litellm(monkeypatch, completion)
    with pytest.raises(InvalidOutput):
        _model().analyze([], "p", SCHEMA)

def test_provider_detection():
    from curator.providers.litellm_model import LiteLLMModel
    ks = FakeKeystore()
    assert LiteLLMModel("gpt-4o-mini", ks).provider() == "openai"
    assert LiteLLMModel("gemini/gemini-2.0-flash", ks).provider() == "gemini"
    assert LiteLLMModel("openrouter/google/gemma-3-27b-it", ks).provider() == "openrouter"
    assert LiteLLMModel("anthropic/claude-sonnet", ks).provider() == "anthropic"
