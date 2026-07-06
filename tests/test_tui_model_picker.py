# tests/test_tui_model_picker.py
from curator.config import load_config
from curator.providers.catalog import ModelEntry
from curator.providers.keystore import KeyStore
from curator.tui.app import CuratorApp
from curator.tui.detect import Detection

LOCAL = ModelEntry("ollama/qwen2.5vl:7b", "ollama", "ollama", True, 0.0, 0.0)
CLOUD = ModelEntry("gpt-4o-mini", "openai", "litellm", False, 1.5e-07, 6e-07)

def _app(tmp_path, catalog):
    det = Detection(True, [e for e in catalog if e.local], [], None)
    return CuratorApp(cfg=load_config(None), home=tmp_path,
                      keystore=KeyStore(home=tmp_path, backend="file"),
                      detection=det, catalog_fn=lambda cfg: catalog)

async def test_tiers_and_badges(tmp_path):
    app = _app(tmp_path, [LOCAL, CLOUD])
    async with app.run_test() as pilot:
        await pilot.press("enter")                       # welcome -> picker
        screen = app.screen
        labels = [str(o.prompt) for o in screen.query_one("#models")._options]
        joined = "\n".join(labels)
        assert "RECOMMENDED" in joined and "ALL VISION MODELS" in joined
        assert "local · free" in joined and "api · ~$" in joined
        assert "not pulled" in joined                    # registry gemma not installed

async def test_local_select_advances(tmp_path):
    app = _app(tmp_path, [LOCAL, CLOUD])
    async with app.run_test() as pilot:
        await pilot.press("enter")
        app.screen.select_model(LOCAL)                   # direct call = the handler body
        await pilot.pause()
        assert app.state.model_entry.id == LOCAL.id
        assert app.screen.__class__.__name__ == "FolderScreen"

async def test_cloud_needs_consent_then_key(tmp_path):
    app = _app(tmp_path, [LOCAL, CLOUD])
    async with app.run_test() as pilot:
        await pilot.press("enter")
        app.screen.select_model(CLOUD)
        await pilot.pause()
        assert app.screen.__class__.__name__ == "ConsentModal"
        await pilot.press("y")                           # consent
        await pilot.pause()
        assert app.screen.__class__.__name__ == "KeyModal"
        for ch in "sk-test-1":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.keystore.get("openai") == "sk-test-1"
        assert app.state.consented("openai")
        assert app.screen.__class__.__name__ == "FolderScreen"

async def test_cloud_with_existing_key_skips_modal(tmp_path):
    app = _app(tmp_path, [LOCAL, CLOUD])
    app.state.keystore.set("openai", "sk-already")
    app.state.record_consent("openai")
    async with app.run_test() as pilot:
        await pilot.press("enter")
        app.screen.select_model(CLOUD)
        await pilot.pause()
        assert app.screen.__class__.__name__ == "FolderScreen"
