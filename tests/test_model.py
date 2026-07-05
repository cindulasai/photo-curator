import pytest
from curator.model import OllamaModel, MockModel, InvalidOutput
from tests.conftest import make_image

SCHEMA = {"type": "object", "properties": {"ok": {"type": "string", "enum": ["yes", "no"]}},
          "required": ["ok"], "additionalProperties": False}

class FakeResp:
    def __init__(self, content): self._c = content; self.status_code = 200
    def raise_for_status(self): pass
    def json(self): return {"message": {"content": self._c}}

def test_ollama_happy_path(tmp_path, monkeypatch):
    img = make_image(tmp_path / "a.jpg", "scene")
    sent = {}
    def fake_post(url, json=None, timeout=None):
        sent.update(json)
        return FakeResp('{"ok": "yes"}')
    monkeypatch.setattr("curator.model.requests.post", fake_post)
    m = OllamaModel("qwen2.5vl:7b", "http://localhost:11434")
    assert m.analyze([img], "prompt", SCHEMA) == {"ok": "yes"}
    assert sent["options"] == {"temperature": 0, "seed": 42}
    assert sent["format"] == SCHEMA and len(sent["messages"][0]["images"]) == 1

def test_ollama_repair_then_success(tmp_path, monkeypatch):
    img = make_image(tmp_path / "a.jpg", "scene")
    replies = iter(['not json at all', '{"ok": "yes"}'])
    calls = []
    def fake_post(url, json=None, timeout=None):
        calls.append(json["messages"][0]["content"])
        return FakeResp(next(replies))
    monkeypatch.setattr("curator.model.requests.post", fake_post)
    m = OllamaModel("m", "http://x")
    assert m.analyze([img], "prompt", SCHEMA) == {"ok": "yes"}
    assert "not json at all" in calls[1]          # repair prompt embeds bad output

def test_ollama_gives_up(tmp_path, monkeypatch):
    img = make_image(tmp_path / "a.jpg", "scene")
    monkeypatch.setattr("curator.model.requests.post",
                        lambda *a, **k: FakeResp('{"ok": "MAYBE"}'))   # schema-invalid forever
    with pytest.raises(InvalidOutput):
        OllamaModel("m", "http://x").analyze([img], "prompt", SCHEMA)

def test_mock_model_validates(tmp_path):
    img = make_image(tmp_path / "a.jpg", "scene")
    m = MockModel(lambda paths, prompt, schema: {"ok": "yes"})
    assert m.analyze([img], "p", SCHEMA)["ok"] == "yes"
    bad = MockModel(lambda *a: {"ok": "MAYBE"})
    with pytest.raises(InvalidOutput):
        bad.analyze([img], "p", SCHEMA)
