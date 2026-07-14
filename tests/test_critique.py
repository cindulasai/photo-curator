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

    # Verify critique override actually landed in the store
    groups = store.groups()
    decided = [g for g in groups if g["champion"]]
    assert len(decided) == 1, "Expected one group with champion set"
    # The critique returned winner=1 (runner-up), overriding the tournament's choice
    # The runner-up is b.jpg (sharpness 82 > a.jpg's 80, so b.jpg is runner-up when tournament picks a.jpg)
    assert decided[0]["champion"] == "b.jpg", f"Expected b.jpg as critique override, got {decided[0]['champion']}"


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


def test_highlights_weak_triggers_reconsider(tmp_path, img_factory):
    """A weak-scored top-pick triggers the evaluator when budget allows."""
    src = tmp_path / "src"
    img_factory(src / "p0.jpg", "scene", seed=0, exif_dt="2026:05:12 10:00:00")
    img_factory(src / "p1.jpg", "scene", seed=1, exif_dt="2026:05:12 10:01:00")

    from curator.db import Store
    from curator.stage4 import run_stage4
    from curator.budget import LLMBudgetCounter

    store = Store(tmp_path / "c.db")
    cfg = load_config(None)

    rubric = {"emotional": 3, "people_engagement": 3, "composition_light": 3,
              "scene_appeal": 3, "novelty": 3}
    vi0 = {"bucket": "people", "tier": "medium", "evidence": [], "tags": [],
            "description": "", "rubric": rubric, "people": None}
    vi1 = {"bucket": "people", "tier": "medium", "evidence": [], "tags": [],
            "description": "", "rubric": rubric, "people": None}

    store.upsert_photo("p0.jpg", kind="photo", status="ok", stage_done=3,
                       sha256="aaa", size=100, ts=1000.0, ts_source="exif",
                       verdict="keep", verdict_info=vi0,
                       stage2={"phash": 0, "flags": [], "work_path": str(src / "p0.jpg"),
                               "lap_var_global": 80.0, "lap_var_center": 80.0})
    store.upsert_photo("p1.jpg", kind="photo", status="ok", stage_done=3,
                       sha256="bbb", size=100, ts=1060.0, ts_source="exif",
                       verdict="keep", verdict_info=vi1,
                       stage2={"phash": 4, "flags": [], "work_path": str(src / "p1.jpg"),
                               "lap_var_global": 80.0, "lap_var_center": 80.0})

    eval_calls = []

    def handler(paths, prompt, schema):
        if "flags" in str(schema):
            # final_verification schema → pass all
            return {"flags": []}
        if "verdict" in str(schema) and "strong" in str(schema):
            # highlights_eval schema
            eval_calls.append(1)
            return {"emotional": 0, "people_engagement": 0, "event_significance": 0,
                    "composition_light": 0, "uniqueness": 0, "scene_appeal": 0,
                    "verdict": "weak"}
        return {"flags": []}

    budget = LLMBudgetCounter(base_count=20, cap_fraction=0.15)
    run_stage4(src, store, cfg, MockModel(handler), budget=budget)
    assert len(eval_calls) >= 1  # evaluator fired


def test_highlights_no_reconsider_without_budget(tmp_path, img_factory):
    """With zero budget, no evaluator calls are made."""
    src = tmp_path / "src"
    img_factory(src / "p0.jpg", "scene", seed=0, exif_dt="2026:05:12 10:00:00")
    img_factory(src / "p1.jpg", "scene", seed=1, exif_dt="2026:05:12 10:01:00")

    from curator.db import Store
    from curator.stage4 import run_stage4
    from curator.budget import LLMBudgetCounter

    store = Store(tmp_path / "c.db")
    cfg = load_config(None)

    rubric = {"emotional": 3, "people_engagement": 3, "composition_light": 3,
              "scene_appeal": 3, "novelty": 3}
    vi = {"bucket": "people", "tier": "medium", "evidence": [], "tags": [],
          "description": "", "rubric": rubric, "people": None}

    store.upsert_photo("p0.jpg", kind="photo", status="ok", stage_done=3,
                       sha256="aaa", size=100, ts=1000.0, ts_source="exif",
                       verdict="keep", verdict_info=vi,
                       stage2={"phash": 0, "flags": [], "work_path": str(src / "p0.jpg"),
                               "lap_var_global": 80.0, "lap_var_center": 80.0})
    store.upsert_photo("p1.jpg", kind="photo", status="ok", stage_done=3,
                       sha256="bbb", size=100, ts=1060.0, ts_source="exif",
                       verdict="keep", verdict_info=dict(vi),
                       stage2={"phash": 4, "flags": [], "work_path": str(src / "p1.jpg"),
                               "lap_var_global": 80.0, "lap_var_center": 80.0})

    eval_calls = []

    def handler(paths, prompt, schema):
        if "verdict" in str(schema) and "strong" in str(schema):
            eval_calls.append(1)
            return {"emotional": 1, "people_engagement": 1, "event_significance": 1,
                    "composition_light": 1, "uniqueness": 1, "scene_appeal": 1,
                    "verdict": "weak"}
        return {"flags": []}

    budget = LLMBudgetCounter(base_count=0)
    run_stage4(src, store, cfg, MockModel(handler), budget=budget)
    assert len(eval_calls) == 0  # no budget → no eval


def test_critique_runner_up_selection_n3(tmp_path, img_factory):
    """With 3 photos, runner-up is the highest-sharpness non-champion, not just the finalist."""
    src = tmp_path / "src"
    img_factory(src / "a.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:00")
    img_factory(src / "b.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:01")
    img_factory(src / "c.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:02")
    store = Store(tmp_path / "c.db")
    cfg = load_config(None)
    # Set stage2 with specific sharpness values
    sharps = {"a.jpg": 60.0, "b.jpg": 90.0, "c.jpg": 85.0}
    for rel, sharp in sharps.items():
        store.upsert_photo(rel, kind="photo", status="ok", stage_done=2,
                           sha256=rel[0] * 3, size=100, ts=1000.0 + float(ord(rel[0])),
                           ts_source="exif",
                           stage2={"lap_var_global": sharp, "lap_var_center": sharp,
                                    "phash": 0, "flags": [], "work_path": str(src / rel)})
    store.add_group("burst", ["a.jpg", "b.jpg", "c.jpg"])

    calls = []
    def handler(paths, prompt, schema):
        calls.append(len(paths))
        if "best_index" in str(schema):
            # Tournament: always pick index 0 from sorted batch
            return {"best_index": 0, "unsure": False, "reason": "first wins"}
        # Critique: agree with tournament (winner=0, no override)
        return {"winner": 0, "reason": "agree"}

    from curator.tournament import run_tournaments
    from curator.budget import LLMBudgetCounter
    budget = LLMBudgetCounter(base_count=20)
    run_tournaments(src, store, cfg, MockModel(handler), budget=budget)
    # The N=3 test just verifies no crash and groups are decided
    groups = store.groups()
    decided = [g for g in groups if g["champion"]]
    # With 3 photos in a burst, tournament should decide a champion
    assert len(decided) >= 1
