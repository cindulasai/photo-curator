# photo-curator

Local, trustworthy photo curation: classical computer vision measures what is
measurable (blur, exposure, duplicates); a local vision LLM judges only what
needs judgment (meaning, emotion, best-of-burst); and every uncertain decision
is routed to a small human-review pile instead of being guessed.

Design spec: `docs/superpowers/specs/2026-07-04-photo-curator-design.md`
Implementation plan: `docs/superpowers/plans/2026-07-05-photo-curator.md`
Agent skill entry point: `SKILL.md`

## Install & run

    pip install -e ".[dev]"
    python -m pytest                       # full test suite, no model needed
    ollama pull qwen2.5vl:7b
    photo-curator qualify                  # 10-image calibration gate
    photo-curator run <photo-folder> --dry-run
    photo-curator run <photo-folder>

## Documented deviations from the spec

1. **Calibration set is synthetic** (spec §6.5 envisioned some real photos):
   `scripts/build_calibration.py` generates all 10 images so the repo is
   self-contained; checks are limited to objective attributes (fatal blur,
   black frame, screenshot, document). Real-photo accuracy is covered by the
   golden harness below.
2. **Golden set ships as a harness + CI fixture set** (spec §11.2 envisions a
   ~150-photo human-labeled set): label your own photos in
   `golden/answers.yaml` (schema documented in `scripts/run_golden.py`) and run
   `python scripts/run_golden.py <curated-out> golden/answers.yaml`. The
   spec's bars are enforced whenever labels exist: reject precision >= 0.95,
   best-of-burst agreement >= 0.85, bucket accuracy >= 0.80, needs-review <= 0.10.
3. **Multi-image adapter**: `VisionModel.analyze` takes a list of images
   (spec §6.1 showed one) because tournaments and final verification are
   comparative multi-image calls.
4. **OpenCV pinned <5**: OpenCV 5 removed the bundled Haar cascade face
   detector; 4.x keeps face detection fully offline with no model downloads.

## Reliability model in one paragraph

Stage 2 (classical) never rejects alone except the narrow unsalvageable rule
(extreme blur AND extreme exposure/tiny AND no faces). The LLM never rejects
alone either: a reject needs a classical flag AND two differently-worded LLM
passes agreeing. Duplicate collapse needs the LLM tournament AND classical
sharpness to agree on the champion. Top picks pass a final "would a careful
human be embarrassed by this?" verification. Everything short of agreement
lands in needs-review with the evidence attached.
