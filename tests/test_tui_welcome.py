from pathlib import Path
from curator.config import load_config
from curator.providers.catalog import ModelEntry
from curator.providers.keystore import KeyStore
from curator.tui.app import CuratorApp
from curator.tui.detect import Detection

def _detection():
    return Detection(ollama_up=True,
                     local_models=[ModelEntry("ollama/qwen2.5vl:7b", "ollama",
                                              "ollama", True, 0.0, 0.0)],
                     env_keys=["openai"], prior=None)

def _app(tmp_path):
    return CuratorApp(cfg=load_config(None), home=tmp_path,
                      keystore=KeyStore(home=tmp_path, backend="file"),
                      detection=_detection(),
                      catalog_fn=lambda cfg: _detection().local_models)

async def test_welcome_shows_detection(tmp_path):
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        text = str(app.screen.query_one("#status").render())
        assert "Ollama: running" in text
        assert "qwen2.5vl:7b" in text
        assert "openai" in text                       # env key found

async def test_enter_advances_to_model_picker(tmp_path):
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert app.screen.__class__.__name__ == "ModelPickerScreen"

def test_detect_offline(tmp_path, monkeypatch):
    import requests
    from curator.tui import detect as d
    monkeypatch.setattr(d, "ollama_vision_models", lambda url, timeout=2.0: [])
    def boom(*a, **k): raise requests.ConnectionError()
    monkeypatch.setattr(d.requests, "get", boom)
    det = d.detect(load_config(None), home=tmp_path)
    assert det.ollama_up is False and det.local_models == []

def test_consent_persists(tmp_path):
    from curator.tui.state import AppState
    st = AppState(cfg=load_config(None),
                  keystore=KeyStore(home=tmp_path, backend="file"), home=tmp_path)
    assert not st.consented("openai")
    st.record_consent("openai")
    st2 = AppState(cfg=load_config(None),
                   keystore=KeyStore(home=tmp_path, backend="file"), home=tmp_path)
    assert st2.consented("openai")
