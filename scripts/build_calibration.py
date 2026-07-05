#!/usr/bin/env python3
"""Generate the synthetic calibration set (spec §6.5, deviation: fully synthetic)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.conftest import make_image

OUT = Path(__file__).resolve().parents[1] / "curator" / "data" / "calibration"
ANSWERS = [
    ("blur_a.png", "scene", {"blur": 14, "seed": 21}, "quality_judgment.fatal", "yes"),
    ("blur_b.png", "portrait", {"blur": 16, "seed": 22}, "quality_judgment.fatal", "yes"),
    ("black.png", "black", {}, "quality_judgment.fatal", "yes"),
    ("shot_a.png", "screenshot", {"seed": 1}, "utility.is_screenshot", "yes"),
    ("shot_b.png", "screenshot", {"seed": 2}, "utility.is_screenshot", "yes"),
    ("receipt.png", "white_doc", {}, "utility.is_document", "yes"),
    ("scene_a.png", "scene", {"seed": 11}, "quality_judgment.fatal", "no"),
    ("scene_b.png", "scene", {"seed": 12}, "quality_judgment.fatal", "no"),
    ("scene_c.png", "scene", {"seed": 13}, "utility.is_screenshot", "no"),
    ("scene_d.png", "scene", {"seed": 14}, "utility.is_document", "no"),
]

OUT.mkdir(parents=True, exist_ok=True)
answers = []
for fname, kind, kw, check, expect in ANSWERS:
    make_image(OUT / fname, kind, **kw)
    answers.append({"file": fname, "check": check, "expect": expect})
(OUT / "answers.json").write_text(json.dumps(answers, indent=2))
print(f"wrote {len(ANSWERS)} calibration images + answers.json to {OUT}")
