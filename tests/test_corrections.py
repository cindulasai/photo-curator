import json
from pathlib import Path

from curator.review.corrections import append_correction, load_corrections, was_declined


def test_append_and_load(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "curator.review.corrections.CORRECTIONS_HOME", tmp_path / ".photo-curator"
    )
    ev1 = {
        "kind": "action",
        "run": "run-abc",
        "photo": "IMG_001.jpg",
        "pipeline_said": {"verdict": "reject"},
        "user_said": {"verdict": "keep"},
    }
    ev2 = {
        "kind": "action",
        "run": "run-abc",
        "photo": "IMG_002.jpg",
        "pipeline_said": {"verdict": "keep"},
        "user_said": {"verdict": "top-pick"},
    }
    append_correction(ev1)
    append_correction(ev2)
    all_evs = load_corrections()
    assert len(all_evs) == 2
    assert all_evs[0]["photo"] == "IMG_001.jpg"


def test_filter_by_run(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "curator.review.corrections.CORRECTIONS_HOME", tmp_path / ".photo-curator"
    )
    append_correction(
        {
            "kind": "action",
            "run": "run-A",
            "photo": "x.jpg",
            "pipeline_said": {},
            "user_said": {},
        }
    )
    append_correction(
        {
            "kind": "action",
            "run": "run-B",
            "photo": "y.jpg",
            "pipeline_said": {},
            "user_said": {},
        }
    )
    assert len(load_corrections(run_id="run-A")) == 1


def test_malformed_line_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "curator.review.corrections.CORRECTIONS_HOME", tmp_path / ".photo-curator"
    )
    home = tmp_path / ".photo-curator"
    home.mkdir(parents=True, exist_ok=True)
    (home / "corrections.jsonl").write_text("not json\n")
    assert load_corrections() == []


def test_was_declined(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "curator.review.corrections.CORRECTIONS_HOME", tmp_path / ".photo-curator"
    )
    assert not was_declined("blur-leniency-kids")
    append_correction({"kind": "declined", "key": "blur-leniency-kids"})
    assert was_declined("blur-leniency-kids")
