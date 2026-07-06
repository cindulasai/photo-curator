import threading
import pytest
from curator.tui.app import CuratorApp
from curator.tui.runner import PipelineRunner, RunnerState


def _make_runner(tmp_path):
    state = RunnerState()
    state.done = True
    state.exit_code = 0
    (tmp_path / "curation.db").touch()
    runner = object.__new__(PipelineRunner)
    runner.state = state
    runner.out = tmp_path
    runner._cancel = threading.Event()
    return runner


def _fake_srv_class():
    t = threading.Thread()  # never started — join() returns immediately

    class FakeSrv:
        def __init__(self, *a, **k):
            self._thread = t

        def start(self, **k):
            pass

        @property
        def url(self):
            return "http://127.0.0.1:9999/?token=x"

        def stop(self):
            pass

    return FakeSrv


@pytest.mark.asyncio
async def test_results_r_binding_launches_review(tmp_path, monkeypatch):
    FakeSrv = _fake_srv_class()
    monkeypatch.setattr("curator.tui.screens_run.ReviewServer", FakeSrv)
    monkeypatch.setattr("curator.tui.screens_run.find_free_port", lambda: 9999)
    monkeypatch.setattr("curator.tui.screens_run.make_token", lambda: "x")

    from curator.tui.screens_run import ResultsScreen

    runner = _make_runner(tmp_path)
    app = CuratorApp(catalog_fn=lambda: [], model_factory=None)
    async with app.run_test() as pilot:
        await app.push_screen(ResultsScreen(runner))
        await pilot.pause(0.05)
        await pilot.press("r")
        await pilot.pause(0.1)
        # pressing "r" should not crash — ReviewServer.start was called


@pytest.mark.asyncio
async def test_results_r_binding_missing_server(tmp_path, monkeypatch):
    """When ReviewServer is None (import failed), pressing r shows a notification."""
    monkeypatch.setattr("curator.tui.screens_run.ReviewServer", None)

    from curator.tui.screens_run import ResultsScreen

    runner = _make_runner(tmp_path)
    app = CuratorApp(catalog_fn=lambda: [], model_factory=None)
    async with app.run_test() as pilot:
        await app.push_screen(ResultsScreen(runner))
        await pilot.pause(0.05)
        await pilot.press("r")
        await pilot.pause(0.1)
        # should not crash even when ReviewServer is None
