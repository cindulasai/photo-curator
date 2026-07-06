import json, time
from unittest.mock import patch
from curator.config import load_config
from curator.db import Store
from curator.model import MockModel
from curator.providers.catalog import ModelEntry
from curator.tui.runner import PipelineRunner, factory_for

LOCAL = ModelEntry("ollama/qwen2.5vl:7b", "ollama", "ollama", True, 0.0, 0.0)


def _handler(paths, prompt, schema):
    if "required schema" in prompt or "single valid JSON" in prompt:
        pass
    props = schema.get("properties", {})
    if "keep_worthy" in props:
        return {"keep_worthy": "yes", "real_camera_photo": "yes",
                "intentional_shot": "yes", "note": "x"}
    if "best_index" in props:
        return {"best_index": 0, "reason": "x", "unsure": "no"}
    if "flags" in props:
        return {"flags": []}
    return {"bucket": {"primary": "everyday-misc", "confidence": 0.9, "alternates": []},
            "tags": [], "description": "x",
            "people": {"count": 0, "eyes_closed": "n/a", "expression_quality": "n/a"},
            "utility": {"is_screenshot": "no", "is_document": "no", "is_accidental": "no"},
            "quality_judgment": {"fatal": "no", "note": "x"},
            "rubric": {"emotional": 1, "people_engagement": 0, "composition_light": 1,
                       "scene_appeal": 1, "novelty": 0, "justifications": {}}}


def _wait(runner, timeout=60):
    t0 = time.time()
    while not runner.state.done:
        assert time.time() - t0 < timeout, "runner hung"
        time.sleep(0.05)


def test_runner_completes_and_applies_early_steer(tmp_path, img_factory):
    src = tmp_path / "src"
    for i in range(2):
        img_factory(src / f"p{i}.jpg", "scene", seed=i,
                    exif_dt=f"2026:05:12 10:0{i}:00")
    out = tmp_path / "out"
    r = PipelineRunner(source=src, out=out, model_entry=LOCAL, keystore=None,
                       cfg_deltas=[], skip_qualification=True,
                       model_factory=lambda cfg: MockModel(_handler))
    r.push([{"path": "prompt_suffix", "op": "append", "value": "KIDS FIRST", "why": ""}])
    r.start()
    _wait(r)
    assert r.state.exit_code == 0 and r.state.error is None
    assert (out / "REPORT.md").exists()
    store = Store(out / "curation.db")
    applied = json.loads(store.get_meta("user_deltas"))
    assert applied[0]["deltas"][0]["value"] == "KIDS FIRST"


def test_factory_for_local_builds_ollama():
    from curator.model import OllamaModel
    m = factory_for(LOCAL, None)(load_config(None))
    assert isinstance(m, OllamaModel)


def test_factory_for_cloud_builds_litellm(tmp_path):
    from curator.providers.keystore import KeyStore
    from curator.providers.litellm_model import LiteLLMModel
    cloud = ModelEntry("gpt-4o-mini", "openai", "litellm", False)
    ks = KeyStore(home=tmp_path, backend="file")
    m = factory_for(cloud, ks)(load_config(None))
    assert isinstance(m, LiteLLMModel)


def test_stop_cancels_cleanly(tmp_path):
    """stop() sets _cancel; _SteerProxy raises KeyboardInterrupt; thread exits cleanly."""
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"

    def mock_pipeline(args, model_factory=None, steer=None, notify=None):
        cfg = load_config(None)
        while True:
            steer(cfg, 0)   # raises KeyboardInterrupt when stop() is called
        return 0

    r = PipelineRunner(source=src, out=out, model_entry=LOCAL, keystore=None,
                       cfg_deltas=[], model_factory=lambda cfg: MockModel(_handler))

    import curator.tui.runner as runner_mod
    with patch.object(runner_mod, "run_pipeline", mock_pipeline):
        r.start()
        time.sleep(0.05)    # let worker start spinning
        r.stop()
        _wait(r, timeout=5)

    assert r.state.done is True


def test_pipeline_error_sets_state(tmp_path):
    """When run_pipeline raises, state.error is set and state.done is True."""
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"

    def mock_pipeline(args, model_factory=None, steer=None, notify=None):
        raise RuntimeError("boom")

    r = PipelineRunner(source=src, out=out, model_entry=LOCAL, keystore=None,
                       cfg_deltas=[], model_factory=lambda cfg: MockModel(_handler))

    import curator.tui.runner as runner_mod
    with patch.object(runner_mod, "run_pipeline", mock_pipeline):
        r.start()
        _wait(r, timeout=5)

    assert r.state.done is True
    assert r.state.error is not None
    assert "boom" in r.state.error
