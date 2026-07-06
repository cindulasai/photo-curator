# tests/test_tui_setup_flow.py
from curator.config import load_config
from curator.model import MockModel
from curator.providers.catalog import ModelEntry
from curator.providers.keystore import KeyStore
from curator.tui.app import CuratorApp
from curator.tui.detect import Detection
from curator.tui.screens_folder import count_photos

LOCAL = ModelEntry("ollama/qwen2.5vl:7b", "ollama", "ollama", True, 0.0, 0.0)

def _app(tmp_path, model_factory=None):
    det = Detection(True, [LOCAL], [], None)
    return CuratorApp(cfg=load_config(None), home=tmp_path / "home",
                      keystore=KeyStore(home=tmp_path / "home", backend="file"),
                      detection=det, catalog_fn=lambda cfg: [LOCAL],
                      model_factory=model_factory)

def _photos(tmp_path, img_factory, n=2):
    src = tmp_path / "src"
    for i in range(n):
        img_factory(src / f"p{i}.jpg", "scene", seed=i,
                    exif_dt=f"2026:05:12 10:0{i}:00")
    return src

def test_count_photos(tmp_path, img_factory):
    src = _photos(tmp_path, img_factory, 3)
    (src / "note.txt").write_text("x")
    assert count_photos(src) == 3

async def test_folder_to_intent_skip_to_confirm(tmp_path, img_factory):
    src = _photos(tmp_path, img_factory)
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("enter")                      # welcome -> picker
        app.screen.select_model(LOCAL)                  # picker -> folder
        await pilot.pause()
        folder_screen = app.screen
        folder_screen.set_folder(src)                   # same as tree/path selection
        await pilot.pause()
        assert app.state.folder == src
        assert app.screen.__class__.__name__ == "IntentScreen"
        await pilot.press("enter")                      # empty input = skip
        await pilot.pause()
        assert app.screen.__class__.__name__ == "ConfirmScreen"
        text = str(app.screen.query_one("#summary").render())
        assert "2 photos" in text and "qwen2.5vl:7b" in text
        assert (tmp_path / "home" / "last_run.json").exists()

async def test_intent_parses_and_accept(tmp_path, img_factory):
    src = _photos(tmp_path, img_factory)
    canned = {"deltas": [{"path": "triage.blur_sharp_min", "op": "set",
                          "value": 80, "why": "stricter"}], "reply": "Done."}
    app = _app(tmp_path, model_factory=lambda cfg: MockModel(lambda *a: canned))
    async with app.run_test() as pilot:
        await pilot.press("enter")
        app.screen.select_model(LOCAL)
        await pilot.pause()
        app.screen.set_folder(src)
        await pilot.pause()
        intent = app.screen
        intent.query_one("#wish").value = "be stricter about blur"
        await pilot.press("enter")
        await pilot.pause(delay=0.5)                    # worker parses
        assert "blur_sharp_min" in str(intent.query_one("#parsed").render())
        await pilot.press("a")                          # accept
        await pilot.pause()
        assert app.state.deltas == canned["deltas"]
        assert app.screen.__class__.__name__ == "ConfirmScreen"
