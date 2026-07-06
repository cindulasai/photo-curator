import pytest
from pathlib import Path
from curator.budget import LLMBudgetCounter
from curator.config import load_config
from curator.db import Store
from curator.model import MockModel


def test_budget_counter_basic():
    b = LLMBudgetCounter(base_count=10, cap_fraction=0.15)
    assert b.remaining == 1   # floor(10 * 0.15) = 1
    assert b.charge() is True
    assert b.remaining == 0
    assert b.charge() is False  # exhausted
    assert b.remaining == 0


def test_budget_counter_zero_base():
    b = LLMBudgetCounter(base_count=0)
    assert b.remaining == 0
    assert b.charge() is False


def test_budget_counter_large():
    b = LLMBudgetCounter(base_count=100, cap_fraction=0.15)
    assert b.remaining == 15
    for _ in range(15):
        assert b.charge() is True
    assert b.charge() is False


def test_close_call_triggers_critique(tmp_path, img_factory):
    """When two burst frames have near-equal sharpness, critique round fires."""
    src = tmp_path / "src"
    img_factory(src / "a.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:00")
    img_factory(src / "b.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:01")  # same seed = same sharpness
    store = Store(tmp_path / "c.db")
    cfg = load_config(None)
    # Set up two photos in the same burst group
    store.upsert_photo("a.jpg", kind="photo", status="ok", stage_done=2,
                       sha256="aaa", size=100, ts=1000.0, ts_source="exif",
                       stage2={"lap_var_global": 80.0, "lap_var_center": 80.0,
                                "phash": 0, "flags": [], "work_path": str(src / "a.jpg")})
    store.upsert_photo("b.jpg", kind="photo", status="ok", stage_done=2,
                       sha256="bbb", size=100, ts=1001.0, ts_source="exif",
                       stage2={"lap_var_global": 82.0, "lap_var_center": 82.0,
                                "phash": 3, "flags": [], "work_path": str(src / "b.jpg")})
    gid = store.add_group("burst", ["a.jpg", "b.jpg"])

    calls = []
    def handler(paths, prompt, schema):
        calls.append(schema)
        # Tournament call: schema requires best_index
        if "best_index" in str(schema):
            return {"best_index": 0, "unsure": False, "reason": "first is better"}
        # Critique call: schema requires winner
        return {"winner": 1, "reason": "runner-up is better"}

    from curator.tournament import run_tournaments
    from curator.budget import LLMBudgetCounter
    budget = LLMBudgetCounter(base_count=10)  # cap = 1 extra call
    run_tournaments(src, store, cfg, MockModel(handler), budget=budget)

    # The critique round should have fired (at least 2 total analyze calls for this group)
    assert len(calls) >= 2


def test_budget_exhausted_no_critique(tmp_path, img_factory):
    """When budget is exhausted, no extra critique call is made."""
    src = tmp_path / "src"
    img_factory(src / "a.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:00")
    img_factory(src / "b.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:01")
    store = Store(tmp_path / "c.db")
    cfg = load_config(None)
    store.upsert_photo("a.jpg", kind="photo", status="ok", stage_done=2,
                       sha256="aaa", size=100, ts=1000.0, ts_source="exif",
                       stage2={"lap_var_global": 80.0, "lap_var_center": 80.0,
                                "phash": 0, "flags": [], "work_path": str(src / "a.jpg")})
    store.upsert_photo("b.jpg", kind="photo", status="ok", stage_done=2,
                       sha256="bbb", size=100, ts=1001.0, ts_source="exif",
                       stage2={"lap_var_global": 82.0, "lap_var_center": 82.0,
                                "phash": 3, "flags": [], "work_path": str(src / "b.jpg")})
    store.add_group("burst", ["a.jpg", "b.jpg"])
    calls = []
    def handler(paths, prompt, schema):
        calls.append(len(paths))
        return {"best_index": 0, "unsure": False, "reason": "better"}
    from curator.tournament import run_tournaments
    from curator.budget import LLMBudgetCounter
    budget = LLMBudgetCounter(base_count=0)  # zero budget → no critique
    run_tournaments(src, store, cfg, MockModel(handler), budget=budget)
    assert len(calls) == 1  # only the base tournament call, no critique
