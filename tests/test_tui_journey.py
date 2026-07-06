import pytest
from curator.config import load_config
from curator.model import MockModel
from curator.providers.catalog import ModelEntry
from curator.providers.keystore import KeyStore
from curator.tui.app import CuratorApp
from curator.tui.detect import Detection
from tests.test_runner import _handler
from tests.test_qualification import _smart_handler

LOCAL = ModelEntry("ollama/qwen2.5vl:7b", "ollama", "ollama", True, 0.0, 0.0)


def _journey_handler(paths, prompt, schema):
    name = paths[0].name if paths else ""
    if name.startswith(("blur", "black", "shot", "receipt", "scene_")) and name.endswith(".png"):
        return _smart_handler(paths, prompt, schema)
    return _handler(paths, prompt, schema)


@pytest.mark.asyncio
async def test_first_run_journey_to_results(tmp_path, img_factory):
    src = tmp_path / "src"
    for i in range(2):
        img_factory(src / f"p{i}.jpg", "scene", seed=i,
                    exif_dt=f"2026:05:12 10:0{i}:00")

    def factory(cfg):
        return MockModel(_journey_handler)

    app = CuratorApp(cfg=load_config(None), home=tmp_path / "home",
                     keystore=KeyStore(home=tmp_path / "home", backend="file"),
                     detection=Detection(True, [LOCAL], [], None),
                     catalog_fn=lambda cfg: [LOCAL], model_factory=factory)
    async with app.run_test() as pilot:
        await pilot.press("enter")                 # 1: welcome -> picker
        app.screen.select_model(LOCAL)             # 2: model
        await pilot.pause()
        app.screen.set_folder(src)                 # 3: folder
        await pilot.pause()
        await pilot.press("enter")                 # skip intent
        await pilot.pause()
        await pilot.press("enter")                 # confirm -> run
        for _ in range(200):                       # wait for pipeline thread
            await pilot.pause(delay=0.1)
            if app.screen.__class__.__name__ == "ResultsScreen":
                break
        assert app.screen.__class__.__name__ == "ResultsScreen"
        out = src.parent.glob("curated-*")
        assert any((d / "REPORT.md").exists() for d in out)
