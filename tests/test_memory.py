import json
from pathlib import Path
from curator.chat.memory import (
    load_memory, propose_memories, confirm_proposal, decline_proposal, inject_memory,
    MEMORY_FILE,
)
from curator.model import MockModel

CANNED_PROPOSALS = {"proposals": [
    {"statement": "Keep photos of kids even when slightly soft.",
     "evidence_refs": ["IMG_001.jpg", "IMG_002.jpg", "IMG_003.jpg"],
     "confidence": 0.85, "config_hint": "triage.blur_sharp_min", "key": "blur_kids"},
]}

def _model():
    def handler(paths, prompt, schema):
        return CANNED_PROPOSALS
    return MockModel(handler)

def test_propose_memories(tmp_path, monkeypatch):
    monkeypatch.setattr("curator.chat.memory.MEMORY_FILE", tmp_path / "memory.md")
    monkeypatch.setattr("curator.review.corrections.CORRECTIONS_HOME", tmp_path / ".photo-curator")
    corrections = [
        {"kind": "action", "photo": f"IMG_{i:03d}.jpg",
         "pipeline_said": {"verdict": "reject"}, "user_said": {"verdict": "keep"}}
        for i in range(5)
    ]
    from curator.config import load_config
    proposals = propose_memories(corrections, _model(), load_config(None))
    assert len(proposals) == 1
    assert proposals[0]["key"] == "blur_kids"

def test_confirm_writes_memory(tmp_path, monkeypatch):
    mf = tmp_path / "memory.md"
    monkeypatch.setattr("curator.chat.memory.MEMORY_FILE", mf)
    proposal = CANNED_PROPOSALS["proposals"][0]
    confirm_proposal(proposal)
    lines = load_memory.__wrapped__(mf) if hasattr(load_memory, '__wrapped__') else load_memory()
    # Just verify file was written
    assert mf.exists()
    content = mf.read_text()
    assert "Keep photos of kids" in content

def test_decline_records_to_corrections(tmp_path, monkeypatch):
    monkeypatch.setattr("curator.chat.memory.MEMORY_FILE", tmp_path / "memory.md")
    monkeypatch.setattr("curator.review.corrections.CORRECTIONS_HOME", tmp_path / ".photo-curator")
    proposal = {"key": "blur_kids", "statement": "x", "evidence_refs": [], "confidence": 0.5, "config_hint": None}
    decline_proposal(proposal)
    from curator.review.corrections import was_declined
    assert was_declined("blur_kids")

def test_inject_memory_adds_prompt_suffix(tmp_path, monkeypatch):
    mf = tmp_path / "memory.md"
    mf.write_text("# What I've learned\n- Prefer keeping kid photos.\n- Avoid food in highlights.\n")
    monkeypatch.setattr("curator.chat.memory.MEMORY_FILE", mf)
    from curator.config import load_config
    cfg = load_config(None)
    new_cfg = inject_memory(cfg)
    assert "Prefer keeping kid photos." in new_cfg["prompt_suffix"]
    assert "Avoid food in highlights." in new_cfg["prompt_suffix"]
    assert cfg["prompt_suffix"] == []  # original not mutated
