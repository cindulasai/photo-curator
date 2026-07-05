# photo-curator — Design Specification

**Date:** 2026-07-04
**Status:** Approved design, ready for implementation planning
**Deliverable:** An agent skill (SKILL.md + Python pipeline) that curates a folder of thousands of unsorted photos into an organized, explained, review-ready output using only local compute — classical computer vision plus a local vision LLM (via Ollama).

This document is self-contained. A coding agent must be able to implement the skill from this spec alone, without asking clarifying questions. Where a value is tunable, this spec names the default and where it lives in config.

---

## 1. Problem & Goals

Manually curating photos — culling the bad ones, collapsing duplicates, sorting into buckets, picking the shots worth sharing — costs users hours per batch. This skill automates it with a hard reliability constraint: **the system must never be confidently wrong.** Every automatic decision is either high-confidence and evidence-backed, or it is routed to a small human-review pile with the reasoning attached.

### 1.1 The contract

Given a source folder of photos, produce a **new** output folder containing:

1. `top-picks/` — the album-worthy best photos, flat, ready to drag into Amazon Photos.
2. `albums/` — top picks grouped by detected event.
3. `library/<bucket>/` — every keeper, organized into a category taxonomy.
4. `duplicates/` — near-duplicate and burst groups collapsed to a chosen best frame; inferior frames preserved and cross-referenced.
5. `rejected/<reason>/` — technically bad photos, set aside but fully inspectable.
6. `needs-review/` — everything the system was not sure about, with its reasoning.
7. `REPORT.md` — a human-readable account of every decision.
8. `manifest.json` — every decision, machine-readable.
9. `curation.db` — resumable run state (SQLite).

### 1.2 Hard requirements

- **R1 — Non-destructive:** Source photos are never modified, moved, renamed, or deleted. The pipeline opens source files read-only. Output uses hardlinks when the output directory is on the same filesystem, file copies otherwise.
- **R2 — Never confidently wrong:** No irreversible-feeling decision (reject, duplicate-inferior, top-pick) is made on a single uncorroborated judgment. See §5.
- **R3 — Resumable:** A run killed at any point resumes without repeating completed work. State is checkpointed to SQLite after every photo.
- **R4 — Deterministic:** Same input folder + same config + same model ⇒ same output. LLM calls use temperature 0; ties break on stable keys (file path ascending). Re-runs must not shuffle photos between buckets.
- **R5 — Model-agnostic:** Any vision LLM reachable through the adapter interface (§6.1) can power the pipeline, gated by the model qualification check (§6.5).
- **R6 — Local-only:** No network calls except to the local model server (default `http://localhost:11434`). No telemetry.
- **R7 — Explainable:** Every photo in the output is traceable: what was decided, by which stage, on what evidence, with what confidence.

### 1.3 Non-goals (v1)

- No photo editing or enhancement.
- No face **identity** clustering ("all photos of Mom") — v2, see §12. V1 is face-*aware* (counts, eyes-closed, expressions) but never identifies individuals.
- No video files (inventoried and listed in the report as skipped; never analyzed).
- No cloud service integration; no direct Amazon Photos upload (no public API exists). The deliverable is an upload-ready folder.
- No RAW development. RAW files (`.cr2 .cr3 .nef .arw .dng .orf .raf .rw2`) are inventoried; if a same-stem JPEG sibling exists the JPEG is analyzed and the RAW is noted as its sibling in the manifest; RAW-only files are listed in the report as skipped.
- No interactive review UI (the report + needs-review folder serve that role in v1).

### 1.4 Scale target

Designed for 1,000–10,000 photos per run. Must not fail on larger inputs, but performance targets (§10) are set at the 10k point.

---

## 2. Definitions

| Term | Meaning |
|---|---|
| **Photo** | A decodable raster image file: `.jpg .jpeg .png .heic .heif .webp .tif .tiff .bmp .gif` (first frame). |
| **Verdict** | The single final disposition of a photo: `top-pick`, `keep`, `duplicate-inferior`, `reject`, `needs-review`. |
| **Bucket** | A category folder in the taxonomy (§7). Every `keep` and `top-pick` photo has exactly one primary bucket. |
| **Burst group** | Photos taken ≤ 3 s apart (EXIF `DateTimeOriginal`) with pHash Hamming distance ≤ 10, transitively grouped. |
| **Near-dupe group** | Photos with pHash Hamming distance ≤ 6 regardless of timestamp, transitively grouped. Burst groups subsume near-dupe groups when they overlap. |
| **High-stakes decision** | reject, duplicate-inferior, or top-pick — decisions a user might never revisit or that represent them publicly. |
| **Classical stage** | Deterministic non-ML or lightweight-ML computation (Stage 2). |
| **Confidence tier** | `high` / `medium` / `low`, computed per §5.2 — never taken solely from the model's self-report. |

---

## 3. User Experience

### 3.1 Invocation

The skill is invoked with a source folder and produces output next to it by default:

```
photo-curator run <SOURCE_DIR> [--out <OUT_DIR>] [--config curator.config.yaml]
                  [--model qwen2.5vl:7b] [--fast] [--resume] [--dry-run]
```

- `--out` default: sibling directory `curated-<YYYY-MM-DD>` (date from the newest photo's EXIF, not wall clock, to preserve R4; falls back to `curated-run` if no EXIF dates exist).
- `--fast`: top-picks-only mode — skips per-photo bucket classification for photos that classical triage scores below the highlight shortlist line; report notes reduced coverage.
- `--resume`: continue an interrupted run found in `<OUT_DIR>/curation.db`. Refuses if config or source tree hash changed, with a clear message.
- `--dry-run`: run Stages 1–2 only and print the funnel forecast (how many photos would reach the LLM, ETA).

Progress output: one line per stage with live counter, ETA for Stage 3 (`[stage 3/5] 2,341/4,207 analyzed — ETA 1h 52m`).

### 3.2 What the user does when it finishes

1. Skim `REPORT.md` executive summary.
2. Look through `needs-review/` (target: < 5% of library) and the report's "double-check these" list.
3. Drag `top-picks/` (or an `albums/` subfolder) into Amazon Photos.

---

## 4. Architecture — the five-stage funnel

Rationale: at thousands of photos, a local 7B VLM at ~5–15 s/photo cannot look at everything first. Cheap deterministic algorithms measure what is objectively measurable (blur, exposure, duplication) and the LLM spends its attention only on judgment calls. This mirrors production systems (Google Photos Memories filters "bad, boring, sensitive" with cheap signals before aesthetic models run).

```
PHOTOS (N)
  │
  ▼ Stage 1  Inventory          EXIF, hashes, corrupt detection        ~seconds
  ▼ Stage 2  Classical triage   blur/exposure/dupes/bursts/utility     ~ms per photo
  ▼ Stage 3  Vision LLM pass    semantics, quality, rubric, tournaments (survivors only)
  ▼ Stage 4  Rank & assemble    verdicts, top-picks, diversity, albums  pure code
  ▼ Stage 5  Output & report    folder tree, REPORT.md, manifest.json   pure code
```

Each stage reads its input from and writes its results to `curation.db`. A stage is complete when every photo has a row for that stage; `--resume` restarts at the first incomplete photo of the first incomplete stage.

### 4.1 Stage 1 — Inventory

For every file under `SOURCE_DIR` (recursive, following no symlinks):

- Record: relative path, byte size, mtime, SHA-256.
- If extension in photo list (§2): decode header; extract EXIF `DateTimeOriginal`, camera make/model, GPS lat/lon, orientation, pixel dimensions. Files that fail to decode → `corrupt` flag (they will appear in `rejected/corrupt/`).
- Non-photo files (video, RAW without JPEG sibling, other) → recorded, marked `skipped`, listed in report.
- Exact duplicates: identical SHA-256 → all but one (lowest path sort order survives) marked `duplicate-inferior` with reason `exact-duplicate`, no further processing. This is safe without LLM corroboration because byte-identity is certain (documented exception to R2's two-signal rule).

**Timestamp policy:** `DateTimeOriginal` → else `CreateDate` → else file mtime, with the source recorded (`exif` | `mtime`) since mtime is unreliable; photos with mtime-only dates are excluded from event *naming* but still grouped.

### 4.2 Stage 2 — Classical triage

Operates on a downscaled working copy (longest edge 1536 px) held in a working cache. All thresholds live in config under `triage:` with these defaults:

**Blur (two signals, to protect bokeh portraits):**
- `lap_var_global`: variance of Laplacian on grayscale full frame.
- `lap_var_center`: same on center 50% crop.
- Sharp enough if `max(lap_var_global, lap_var_center) ≥ 60`. Below 25 on both → `blur-extreme` flag. Between → `blur-soft` flag (LLM will judge whether the softness is artistic or fatal).

**Exposure:**
- `pct_black`: % pixels with luma < 8; `pct_white`: % pixels with luma > 247.
- `pct_black ≥ 85` or `pct_white ≥ 85` → `exposure-extreme` flag (near-black/near-white frames, lens-cap shots). `≥ 40` → `exposure-poor` flag for LLM review.

**Utility-shot candidates (flags only; LLM confirms in Stage 3):**
- Screenshot candidate: no camera make in EXIF AND pixel dimensions exactly match a known device-resolution table (shipped as data file) or PNG source.
- Document/receipt candidate: white-pixel ratio ≥ 55% AND high horizontal edge density (text lines).

**Duplicates & bursts:** pHash (64-bit DCT hash) on every photo; BK-tree or sorted-prefix search for pairs within Hamming ≤ 10; group per §2 definitions. Within each group, compute classical rank hints (sharpness, exposure) for the Stage 3 tournament.

**Auto-reject rule (the only Stage-2 rejection):** a photo is rejected without LLM review only if **all three** hold: (1) `blur-extreme` flag set, (2) `exposure-extreme` flag set OR decoded size < 0.1 MP, (3) no face detected (fast classical face detector, e.g. a lightweight SSD/Haar pass — detection only, no identity). Reason recorded as `unsalvageable`. Everything else proceeds or is queued.

Stage 2 output per photo: numeric scores + flags. **No bucket guesses, no aesthetic scores** — those are Stage 3's job.

### 4.3 Stage 3 — Vision LLM semantic pass

Input: all photos not yet rejected/marked exact-duplicate, downscaled to longest edge 1024 px. Two call types:

**(a) Single-photo analysis** — one call per photo, JSON-schema-forced (§6.3), returning: primary bucket + confidence, tags, one-sentence description, people block (count, any eyes-closed, expression quality), utility confirmation (is this really a screenshot/receipt?), quality judgment for `blur-soft`/`exposure-poor` flagged photos (artistic vs. fatal), highlight rubric scores (§5.4), and `unsure` markers wherever the model cannot tell. High-stakes signals get a **second pass** with differently-worded prompt (§6.4); disagreement → confidence drops per §5.2.

**(b) Group tournament** — for each burst/near-dupe group: comparative selection in batches of ≤ 4 frames ("which frame is best and why — consider sharpness, eyes, expressions, composition"), winners advance until one champion remains. Comparative judgment is markedly more reliable for VLMs than absolute scoring. Champion inherits group's Stage-3(a) analysis; losers become `duplicate-inferior` **only if** the tournament decision and classical rank hints agree on a clearly-better champion; if classical hints contradict the LLM choice, the whole group → needs-review.

Checkpoint after every call. Malformed JSON → 2 retries with repair prompt → then that photo → `needs-review` with reason `model-output-invalid`.

### 4.4 Stage 4 — Ranking & assembly (pure code)

1. **Verdict resolution** per photo using the decision table in §5.3.
2. **Composite highlight score** = weighted rubric (§5.4) with technical quality as a gate: photos with fatal quality judgments are ineligible for top-pick regardless of emotional score.
3. **Top-pick selection with diversity constraints:** target size `top_picks.target` (default: `max(20, 2% of keepers)`, cap 300). Greedy selection by composite score subject to: ≤ `top_picks.max_per_event` (default 15) per event cluster, ≤ 3 per burst-adjacent time window (60 s), and bucket spread (no single bucket > 50% of the album unless the library itself is that skewed).
4. **Event clustering:** time-gap clustering on timestamps (new event when gap > 6 h or GPS jump > 50 km); events named from date + dominant bucket + GPS locality when available (offline reverse-geocode table shipped with the skill; no network).
5. **Final top-pick verification pass:** one LLM call over the selected set (thumbnails, batched) asking only: "flag any image a careful human curator would NOT put in a family album (offensive, embarrassing, private-document, badly broken)." Flagged → needs-review, next candidate promoted. This is the last line of defense on the highest-stakes output.

### 4.5 Stage 5 — Output & report (pure code)

- Materialize the tree of §1.1 (hardlink when same filesystem, else copy; preserve original filenames, disambiguate collisions with a short hash suffix).
- `duplicates/<group-id>/` contains inferior frames plus a `CHOSEN.md` naming the champion's output path and the tournament reasoning.
- `needs-review/` items each get a sidecar `<name>.reason.md`: what was being decided, both/all judgments, what the user should look at.
- Write `REPORT.md` (§8.2) and `manifest.json` (§8.3).
- Preflight: required disk space estimated after Stage 4; abort cleanly with the number if insufficient.

---

## 5. The decision model

### 5.1 Verdicts

Exactly one per photo: `top-pick` · `keep` · `duplicate-inferior` · `reject` · `needs-review`. `needs-review` is a real verdict, not a failure state — the design goal is that it stays small (< 5% of the library on typical phone-camera input) but it has no cap: correctness beats tidiness.

### 5.2 Confidence computation

Model self-reported confidence is used only as one input — it is known to be poorly calibrated. Per judged attribute:

| Evidence pattern | Tier |
|---|---|
| Two LLM passes agree AND classical signals (where applicable) concur | **high** |
| Passes agree but a relevant classical signal conflicts, or single-pass judgment (low-stakes attributes) with model confidence ≥ 0.8 | **medium** |
| Passes disagree, or model answered `unsure`, or model confidence < 0.5 | **low** |

### 5.3 Verdict decision table (asymmetric stakes)

| Decision | Requirement | On failure |
|---|---|---|
| `reject` (quality) | High tier: classical extreme flag AND LLM confirms unsalvageable (both passes) | needs-review |
| `reject` (utility, e.g. accidental pocket shot) | High tier: LLM both passes agree AND a classical utility/extreme flag exists | needs-review |
| `duplicate-inferior` | Tournament champion clear AND classical rank hints agree | whole group needs-review |
| `top-pick` | Eligible (quality gate passed), survives diversity selection AND final verification pass | drop to `keep` (verification flag → needs-review) |
| `keep` in bucket | Medium tier or better on bucket classification | `keep` in `everyday-misc` if model gave a low-confidence guess; needs-review only if model said `unsure` entirely |
| Utility buckets (`screenshots`, `documents-receipts`, …) | Classical candidate flag AND LLM confirmation (single pass suffices — low stakes, recoverable) | normal bucket flow |

Wrong-bucket placement is recoverable (annoying at worst) → medium confidence suffices. Rejection and duplicate-collapse might never be revisited by the user → two independent agreeing signals, always. Nothing is deleted under any circumstances.

### 5.4 Highlight rubric

Six axes, each scored 0–4 by the LLM with a one-line justification (surfaced in the report):

| Axis | Weight | What 4 means |
|---|---|---|
| Emotional signal | 0.30 | Genuine laughter/embrace/tears-of-joy/milestone moment |
| People engagement | 0.20 | Subjects present, engaged, eyes open, natural expressions |
| Event significance | 0.15 | Part of a detected significant event (trip, celebration) — computed from event clusters, not asked of the LLM |
| Composition & light | 0.15 | Strong composition, beautiful or interesting light |
| Uniqueness | 0.10 | Unlike anything else in the library (computed: pHash distance to library + LLM novelty judgment) |
| Scene appeal | 0.10 | Objectively appealing subject (landscape, architecture, food styling) |

Technical quality is a **gate**, not an axis: a slightly soft photo of a hug outranks a tack-sharp photo of a wall, but a fatally blurred hug is ineligible. Weights configurable under `rubric:`.

### 5.5 Determinism rules

Temperature 0 on all LLM calls; seed pinned where the server honors it. All iteration orders are sorted (path ascending). Tournament batch composition is deterministic (sorted by path). Tie-breaks: higher classical sharpness, then earlier timestamp, then path ascending.

---

## 6. Vision-LLM interface

### 6.1 Adapter

```python
class VisionModel(Protocol):
    def analyze(self, image_path: Path, prompt: str, json_schema: dict) -> dict: ...
    def name(self) -> str: ...   # e.g. "ollama/qwen2.5vl:7b"
```

Default implementation: Ollama HTTP API with `format: <json_schema>` (structured output mode). The adapter handles: image downscale/encode, timeout (default 120 s/call), 2 retries on transport error, JSON validation against the schema, and the malformed-output repair prompt. Everything above the adapter is model-agnostic (R5).

**Tested defaults** (from published comparisons of Ollama vision models): primary `qwen2.5vl:7b` (best structured-output reliability), alternates `gemma3:12b`, `llama3.2-vision:11b`. The skill documents these but runs whatever passes qualification (§6.5).

### 6.2 Prompting principles (mandated, not advisory)

1. **JSON schema forced** on every call — never free text.
2. **Binary/enum sub-questions** instead of open scales wherever possible ("any eyes closed: yes/no/unsure" beats "rate the faces").
3. **`unsure` is always a schema-legal answer** and prompts explicitly say choosing it is correct when uncertain (abstention beats guessing).
4. **Comparative over absolute** for selection tasks (tournaments, §4.3b).
5. **Two-pass with rewording** for high-stakes attributes: pass 2 uses inverted framing (e.g. pass 1 "is this photo unsalvageably bad?", pass 2 "could a reasonable person want to keep this photo?") so agreement means the judgment survives reframing.
6. **No leading context**: the model is never told what Stage 2 concluded when confirming (it gets the raw question) — classical and LLM signals stay independent so their agreement is meaningful.
7. **One image per single-photo call; ≤ 4 per tournament call** — local VLM accuracy degrades with many images per context.

### 6.3 Single-photo analysis schema (normative)

```json
{
  "bucket": {"primary": "<taxonomy-key>", "confidence": 0.0, "alternates": ["<key>"]},
  "tags": ["<taxonomy-key>", "..."],
  "description": "<one sentence>",
  "people": {"count": 0, "eyes_closed": "yes|no|unsure|n/a",
             "expression_quality": "great|ok|poor|unsure|n/a"},
  "utility": {"is_screenshot": "yes|no|unsure", "is_document": "yes|no|unsure",
              "is_accidental": "yes|no|unsure"},
  "quality_judgment": {"fatal": "yes|no|unsure", "note": "<why>"},
  "rubric": {"emotional": 0, "people_engagement": 0, "composition_light": 0,
             "scene_appeal": 0, "novelty": 0, "justifications": {"<axis>": "<one line>"}},
  "unsure_notes": "<anything the model could not determine>"
}
```

(Exact JSON-Schema file with enums/ranges ships in the repo; this shows shape and intent. `rubric.event significance` and final `uniqueness` are computed in Stage 4, not asked.)

### 6.4 Prompt templates

The repo ships versioned prompt files (`prompts/*.md`, referenced by name+version in the manifest for reproducibility): `analyze_photo v1`, `analyze_photo_reworded v1` (the inverted-framing second pass), `tournament v1`, `final_verification v1`, `json_repair v1`. Prompts embed the active taxonomy (names + one-line descriptions, including user-defined buckets) and the rubric definitions verbatim. Changing a prompt file is a versioned event visible in future manifests.

### 6.5 Model qualification gate

Before Stage 3 of any run (cached per model+version for 30 days in `~/.photo-curator/qualification.json`):

- 10 bundled calibration images with known answers: extreme blur ×2, screenshot ×2, receipt ×1, clear portrait (eyes open) ×1, portrait eyes closed ×1, landscape ×1, food ×1, near-black frame ×1.
- Model must: return schema-valid JSON on 10/10 calls and match the known answer on ≥ 9/10 checks.
- Failure → run refuses to start: *"Model X failed qualification (7/10). This model cannot power reliable curation. Tested alternatives: qwen2.5vl:7b …"* This is how "any model can use the skill" stays honest rather than silently degrading.

---

## 7. Taxonomy & configuration

### 7.1 Default taxonomy (16 buckets)

| Key | Description (verbatim in prompts) |
|---|---|
| `people` | Portraits, group shots, candids where people are the subject |
| `celebrations` | Birthdays, weddings, holidays, parties, ceremonies |
| `kids-family` | Children and family life moments |
| `travel` | Trips and vacations — landmarks, hotels, journeys |
| `nature-outdoors` | Landscapes, hikes, beaches, gardens, sky |
| `urban-architecture` | Cities, buildings, streets, interiors as subject |
| `events-performances` | Concerts, sports, shows, public events |
| `food-drink` | Meals, dishes, drinks, restaurants, cooking |
| `pets-animals` | Pets and animals as the subject |
| `hobbies-activities` | Sports, crafts, games, projects being done |
| `vehicles` | Cars, bikes, boats, planes as the subject |
| `screenshots` | Device screenshots (utility) |
| `documents-receipts` | Documents, receipts, IDs, forms, labels (utility) |
| `whiteboards-notes` | Whiteboards, handwritten notes, slides (utility) |
| `products-shopping` | Products photographed for reference/shopping (utility) |
| `everyday-misc` | Genuinely uncategorizable everyday shots — the honest fallback |

Rules: one **primary** bucket per photo (folder placement) + any number of tags (manifest only). Utility buckets are excluded from top-picks and highlight scoring. `everyday-misc` exists so nothing is force-fitted — a healthy run puts < 15% there; the report warns if more (signal of taxonomy mismatch or model weakness).

### 7.2 `curator.config.yaml`

```yaml
model: qwen2.5vl:7b
ollama_url: http://localhost:11434
buckets:
  disable: []                    # keys to turn off
  custom:
    - key: my-artwork
      description: "Paintings and drawings made by me"
      utility: false
triage: { blur_sharp_min: 60, blur_extreme_max: 25, ... }   # all §4.2 thresholds
top_picks: { target: auto, max_per_event: 15 }
rubric:  { emotional: 0.30, people_engagement: 0.20, ... }   # §5.4 weights
```

Custom buckets are injected into prompts exactly like defaults. Config hash is recorded in the manifest; `--resume` refuses on mismatch.

---

## 8. Output artifacts

### 8.1 Folder tree — see §1.1. Naming: original filenames preserved; collisions get `-<6-char-sha>` suffix. Every output file's provenance (source path) is in the manifest.

### 8.2 `REPORT.md` (normative sections, in order)

1. **Executive summary** — counts funnel: "9,412 photos → 214 top picks, 6,890 organized, 1,977 duplicates collapsed, 289 rejected, 42 need your eyes." Plus run duration, model used, prompt versions.
2. **Top picks gallery** — thumbnail (embedded, max 256 px), one-line description, event, composite score.
3. **Needs your eyes** — every needs-review item: what was being decided, the conflicting/uncertain judgments verbatim, what to look at.
4. **Double-check these** — medium-confidence decisions that executed (bucket placements, borderline rejects that cleared the bar), grouped by type.
5. **Events detected** — timeline of event clusters with names and photo counts.
6. **Statistics** — per-stage timings, funnel percentages, bucket distribution, `everyday-misc` health warning if > 15%.
7. **Skipped files** — videos, RAW-only, unreadable.

### 8.3 `manifest.json`

One record per source file: source path, sha256, verdict, primary bucket, tags, all classical scores, all LLM judgments (both passes where taken) with prompt version, confidence tier per attribute, group memberships (burst/dupe/event), output path(s), and for every executed decision the evidence list that satisfied §5.3. Top-level: run config hash, model name+digest, prompt versions, skill version, stage timings. This file is the API for any downstream tool (including the v2 review UI).

---

## 9. Error handling

| Failure | Behavior |
|---|---|
| Corrupt/undecodable file | Quarantined to `rejected/corrupt/` listing, run continues |
| LLM malformed JSON | 2 repair retries → photo to needs-review (`model-output-invalid`) |
| Ollama unreachable mid-run | Checkpoint, exit with resume instructions (`--resume`) |
| Model qualification failure | Refuse to start, name tested alternatives |
| Disk space insufficient (preflight) | Abort before Stage 5 with required vs. available bytes |
| Source tree changed under `--resume` | Refuse with diff summary |
| Single photo panics any stage | Catch, log, photo → needs-review (`pipeline-error`), run continues |

Universal principle: **every failure degrades to "a human looks at this one photo" — never to a wrong automatic decision.**

---

## 10. Performance targets (10,000 photos, Apple-silicon Mac, 7B model)

- Stage 1 + 2 combined: ≤ 30 minutes.
- Stage 3: live progress + ETA; throughput bounded by model (~5–15 s/photo on 40–70% survivors); full run ≤ 8 h unattended (overnight-friendly).
- `--fast` mode: ≤ 2 h by restricting LLM calls to the highlight shortlist.
- Memory: streaming, O(1) in library size aside from the pHash index; ≤ 4 GB RSS for the pipeline itself.
- Resume overhead: ≤ 60 s to re-reach steady state.

---

## 11. Testing & acceptance criteria

1. **Unit tests** (CI, no model needed): every classical algorithm against fixture images — synthetic blur ladder, generated exposure extremes, real screenshots/receipts, constructed burst sequences, pHash collision cases, EXIF edge cases (missing dates, GPS absent), collision-suffix naming, resume-state machinery (kill/restart mid-stage), determinism of Stage 4 given fixed Stage 1–3 inputs.
2. **Golden-set benchmark** (CI with model, nightly): ~150 photos shipped in-repo with human ground truth (bucket, quality verdict, best-of-burst choice, top-pick-worthiness). Minimum bars: **reject precision ≥ 95%** (a wrongly rejected good photo is a betrayal; recall is secondary), best-of-burst agreement ≥ 85%, bucket accuracy ≥ 80% with ≤ 10% of errors being non-adjacent (e.g. `travel` vs `nature-outdoors` is adjacent; `people` vs `documents-receipts` is not), needs-review rate ≤ 10% on the golden set.
3. **Determinism test:** full pipeline twice on golden set → byte-identical `manifest.json` (modulo timing fields, which live in a separate section).
4. **Qualification-gate test:** a deliberately weak mock model must be refused.
5. **Non-destructiveness test:** run completes → source tree byte-identical (hash the tree before/after in CI).

Acceptance for v1 ship: all five layers green, plus one real-world validation run on a ≥ 2,000-photo personal library where the human reviewer finds **zero confidently-wrong high-stakes decisions** (wrong rejects, wrong duplicate collapses, embarrassing top picks). Bucket quibbles are acceptable; betrayals are not.

---

## 12. v2 roadmap (out of scope, recorded so v1 doesn't paint us into corners)

- **Face identity clustering:** detect → embed → cluster → user labels clusters; person-based albums and "best photo of each person per event." The manifest schema reserves a `faces` block per photo.
- **Interactive review UI:** local web page over `manifest.json` for approving/overriding; the manifest is designed as its API.
- **Incremental mode:** re-run on a growing folder, only new photos processed (curation.db already keyed by sha256 to enable this).
- **Learning from overrides:** user corrections in needs-review feed threshold/prompt adjustments.

---

## 13. Research grounding (key sources)

- Google Photos Memories curation architecture (cheap filters → aesthetic models → dedup): [People+AI Research, Google](https://medium.com/people-ai-research/a-snapshot-of-ai-powered-reminiscing-in-google-photos-5a05d2f2aa46)
- Professional AI culling criteria (blur, closed eyes, expressions, duplicates): [Aftershoot](https://aftershoot.com/blog/best-culling-software/), [Narrative Select](https://narrative.so/select)
- No-reference IQA (BRISQUE/NIQE family): [UT Austin LIVE](http://live.ece.utexas.edu/research/Quality/nrqa.htm)
- Aesthetic assessment lineage (NIMA/AVA, CLIP-based predictors): [survey](https://arxiv.org/pdf/2103.11616), [LAION-Aesthetics](https://laion.ai/blog/laion-aesthetics/)
- Perceptual hashing for near-dupes: [Hoyt, duplicate image detection](https://benhoyt.com/writings/duplicate-image-detection/)
- Local VLM comparison, structured-output reliability (Qwen2.5-VL leading): [PhotoPrism model comparison](https://docs.photoprism.app/developer-guide/vision/model-comparison/), [Qwen2.5-VL vs Llama 3.2](https://www.labellerr.com/blog/qwen-2-5-vl-vs-llama-3-2/)
- VLM hallucination mitigation (self-consistency, abstention): [arXiv 2509.23236](https://arxiv.org/html/2509.23236v1), [arXiv 2604.06195](https://arxiv.org/pdf/2604.06195)
