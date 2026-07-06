from collections import Counter
from curator.chat.qa import answer, build_context
from curator.config import load_config
from curator.db import Store
from curator.model import MockModel


def _store(tmp_path):
    s = Store(tmp_path / "c.db")
    s.upsert_photo("IMG_2041.jpg", kind="photo", status="excluded", stage_done=4,
                   verdict="rejected",
                   verdict_info={"reason": "blur-extreme", "tier": "high"},
                   stage2={"flags": ["blur-extreme"], "lap_var_global": 8.1},
                   stage3={"pass1": {"quality_judgment": {"fatal": "yes", "note": "unsalvageably blurred"}}})
    s.upsert_photo("IMG_2042.jpg", kind="photo", status="ok", stage_done=4,
                   verdict="keep", verdict_info={"bucket": "travel", "tier": "medium"})
    return s


def test_build_context_matches_mentions(tmp_path):
    ctx = build_context(_store(tmp_path), "why was IMG_2041.jpg rejected?")
    assert ctx["summary"]["verdicts"] == {"rejected": 1, "keep": 1}
    assert len(ctx["photos"]) == 1
    assert ctx["photos"][0]["rel_path"] == "IMG_2041.jpg"
    assert ctx["photos"][0]["verdict_info"]["reason"] == "blur-extreme"


def test_no_mention_summary_only(tmp_path):
    ctx = build_context(_store(tmp_path), "how did it go overall?")
    assert ctx["photos"] == [] and ctx["summary"]["total"] == 2


def test_answer_pipes_context(tmp_path):
    seen = {}

    def handler(paths, prompt, schema):
        seen["prompt"] = prompt
        return {"reply": "It was fatally blurred - both passes agreed."}

    out = answer(MockModel(handler), _store(tmp_path), load_config(None),
                 "why was IMG_2041.jpg rejected?")
    assert "blurred" in out
    assert "blur-extreme" in seen["prompt"]
