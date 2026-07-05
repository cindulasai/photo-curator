# Photo Curator TUI App — Design Specification

Date: 2026-07-05
Status: approved direction; supersedes nothing — builds ON TOP of the v1
pipeline spec (`2026-07-04-photo-curator-design.md`), which remains normative
for the five-stage pipeline itself.

## 1. Goal

Turn the photo-curator pipeline into a product a non-technical person can use:
download one file, run it, pick a vision model, point at a folder, chat in
plain English, and get a curated library — then review the results visually in
a browser and have the app *learn their taste* from every correction.

Two implementation phases, each its own plan and shippable on its own:

- **Phase 1 — the app**: Textual TUI, LiteLLM model layer (all providers,
  vision-only), chat (before/during/after run), steering queue, one-click
  binaries for macOS/Linux/Windows.
- **Phase 2 — review + learning**: local web gallery served by the same
  binary, corrections log, global `memory.md` taste profile fed back into
  future runs.

## 2. Hard requirements

R1. **One language.** Python only. The web review UI is static HTML/JS/CSS
    bundled as package data — no Node, no Rust, no second toolchain.
R2. **Vision models only.** The model picker must never show a text-only
    model. Filtering is mechanical, never guessed (see §5.2).
R3. **Source photos remain read-only** (inherited from pipeline spec R1).
    The review UI moves photos only inside the curated output tree.
R4. **No silent intelligence.** Every chat suggestion becomes an auditable
    config delta recorded in the manifest. Every memory.md entry is written
    only after explicit user confirmation.
R5. **Deterministic core preserved.** Steering deltas apply at photo
    boundaries and are recorded with the photo index from which they took
    effect; a manifest plus its recorded deltas fully explains every decision.
R6. **Secrets in the OS keychain** (macOS Keychain, Windows Credential
    Manager, Linux Secret Service via the `keyring` library), with an
    encrypted-file fallback only when no keychain exists (headless Linux).
    API keys never appear in config files, logs, or the manifest.
R7. **Cloud honesty.** Choosing a cloud model triggers a one-time explicit
    consent screen: "Your photos will be sent to <provider>." Local models
    keep the v1 guarantee: photos never leave the machine.
R8. **Every model qualifies or is refused** — the existing 10-image
    calibration gate runs for cloud models too (cost shown first: ~10 images
    ≈ a fraction of a cent for most APIs).
R9. **Worst-case first-run path: 3 interactions** (pick model, pick folder,
    Enter). Everything detectable is detected, never asked.
R10. **TUI works over SSH and in every mainstream terminal** (no image
    protocols required anywhere in the TUI).

## 3. Repo & process layout

```
curator/
  tui/            Textual app: screens, widgets, app.py
  chat/           intent engine, steering queue, post-run Q&A, memory updater
  providers/      LiteLLM adapter, model registry, vision filter, keystore
  review/         HTTP server (stdlib), static/ web assets, corrections API
  ... (existing pipeline modules unchanged)
```

One process. The pipeline runs in a worker thread; the TUI owns the event
loop; the review server runs on a daemon thread only while reviewing. The
steering queue is the single thread-safe channel between chat and pipeline.

## 4. The TUI (Phase 1)

Framework: **Textual**. `photo-curator` with no arguments launches the TUI;
all existing CLI subcommands remain for scripting.

### 4.1 Screens

1. **Welcome / detect** — probes concurrently (2 s budget): Ollama reachable?
   which local models have a vision projector? which `*_API_KEY` env vars are
   set? previous config in `~/.photo-curator/`? Shows what it found. A
   returning user lands directly on Confirm with previous settings.
2. **Model picker** — one flat list, two tiers:
   - `RECOMMENDED` — models that pass our qualification gate (registry §5.3),
     each with badges: `local · free` or `api · ~$X per 1,000 photos`.
   - `ALL VISION MODELS` — the mechanically filtered rest.
   Selecting an uninstalled Ollama model offers `ollama pull` with progress.
   Selecting a cloud model prompts for the API key (masked, → keychain) and
   shows the R7 consent screen once per provider.
3. **Folder picker** — Textual DirectoryTree plus a paste-a-path input; live
   photo count and total size for the highlighted folder.
4. **Intent chat (optional)** — single prompt: *"Anything special you want?
   (Enter to just curate)"*. Free text → intent engine (§6.1) → shown back as
   a human-readable list of adjustments for confirmation.
5. **Confirm** — model, folder, N photos, est. duration, est. $ (cloud),
   active memory.md preferences (count + expandable), the adjustments from
   step 4. Enter starts; `q` backs out.
6. **Run** — per-stage progress bars, ETA, live counters (rejected /
   groups / analyzed / top picks), cloud cost meter, scrolling decision log,
   and the always-open chat input (§6.2). Keys: `p` pause, `c` cancel
   (checkpointed — resumable), `?` help.
7. **Results** — executive summary; `r` opens the review gallery (Phase 2),
   `o` opens the output folder, chat remains open for post-run Q&A (§6.3).

Footer on every screen: contextual key hints + "just type to talk."

### 4.2 Testing the TUI

Textual's `Pilot` harness drives every screen headlessly in CI: key
sequences, focus order, and a full synthetic first-run journey (welcome →
results) against MockModel. No test requires a real terminal, model, or
network.

## 5. Model layer (Phase 1)

### 5.1 Adapter

`LiteLLMModel` implements the existing `VisionModel` protocol
(`analyze(image_paths, prompt, json_schema) -> dict`). It keeps the proven
reliability loop from `OllamaModel` — 3 transport retries, then up to 3
schema-repair cycles, then `InvalidOutput`. JSON is enforced via LiteLLM's
`response_format` json_schema support where the provider allows it, with
prompt-embedded schema + local `jsonschema` validation as the universal
fallback. `temperature=0`, fixed seed where supported. `OllamaModel` remains
the zero-dependency default for local use; LiteLLM is the door to everything
else.

### 5.2 Vision-only filtering (mechanical, three sources)

1. **LiteLLM capability metadata**: `litellm.supports_vision(model)` /
   `model_prices_and_context_window.json` — filters the static catalog.
2. **OpenRouter live catalog**: `GET /api/v1/models`, keep only models whose
   `architecture.input_modalities` includes `image`.
3. **Ollama local probe**: `/api/tags` + `/api/show` per model; keep models
   whose details/capabilities indicate a vision projector (`clip`, `mllama`,
   or `vision` capability flag).

A model that appears in none of these sources can still be entered manually
("Custom model…"), but it must pass the qualification gate before a run —
the gate is the final arbiter either way (R8).

### 5.3 Recommended registry

`curator/providers/registry.yaml`, shipped in the package and overridable by
`~/.photo-curator/registry.yaml`. Starter content (each entry ships with the
qualification evidence date; entries are re-verified when bumped):

| id | provider | class |
|---|---|---|
| `ollama/qwen2.5vl:7b` | local | default recommendation |
| `ollama/gemma3:12b`, `ollama/gemma3:4b` | local | low-RAM option |
| `ollama/llama3.2-vision:11b` | local | |
| `ollama/minicpm-v:8b` | local | |
| `gpt-4o-mini`, `gpt-4o` | OpenAI | |
| `gemini/gemini-2.0-flash` | Google | cheapest strong API |
| `anthropic/claude-3-5-haiku` class vision models | Anthropic | |
| `openrouter/*` | OpenRouter | any image-modality model, gate-verified |

Cost badges are computed from LiteLLM's price metadata × the app's measured
average tokens-per-photo (shipped constant, refined per run).

### 5.4 Keystore

`curator/providers/keystore.py`: `get(provider)`, `set(provider, key)`,
`delete(provider)`. Backend: `keyring`; fallback: `~/.photo-curator/keys.enc`
encrypted with a machine-local key file (0600). Env vars (`OPENAI_API_KEY`
etc.) are read but never written.

## 6. Chat (Phase 1)

One chat agent, three modes, one implementation. It talks through the same
`VisionModel`/LiteLLM layer (text-only calls allowed for chat itself). Every
chat call is schema-forced JSON, like every pipeline call.

### 6.1 Before the run — intent → config deltas

The intent engine translates free text into a validated **delta document**:

```json
{"deltas": [
  {"path": "triage.blur_sharp_min", "value": 80, "why": "user asked for stricter blur"},
  {"path": "buckets.disable", "op": "append", "value": "food-drink", "why": "user doesn't care about food"},
  {"path": "prompt_suffix", "op": "append",
   "value": "The user especially treasures photos of their daughter; weight emotional value of child photos highly.",
   "why": "user focus request"}
]}
```

Only whitelisted paths are steerable (`triage.*` thresholds, `top_picks.*`,
`buckets.disable/custom`, `rubric.*` weights, `prompt_suffix`,
`skip_globs`). Anything else → the agent explains it can't. Deltas are shown
to the user in plain English and applied only on confirmation. Applied deltas
are recorded in the manifest under `user_deltas` (R4).

### 6.2 During the run — the steering queue

The chat input never blocks. Messages are classified:

- **Question** ("any gems yet?") → answered immediately from live run state
  (counters, recent decisions, current photo). Zero pipeline impact.
- **Steering** ("be stricter on blur", "skip the WhatsApp folder") → intent
  engine → delta → pushed to the thread-safe queue. The pipeline drains the
  queue at each photo boundary; the manifest records
  `{delta, effective_from_photo_index}` (R5). The log shows
  `↪ applied: stricter blur (photo #341 onward)`.
- **Impossible mid-run** (change model, change source folder) → honest
  refusal with options: finish, or cancel-and-restart (run is checkpointed).

### 6.3 After the run — Q&A over the manifest

Post-run questions are answered with the manifest + decision log as context:
"why was IMG_2041 rejected?" → the agent quotes the recorded evidence (blur
scores, both LLM passes, verdict tier). Commands ("move all beach photos to
travel") execute through the same corrections API as the review UI (§7.3),
so chat and clicks are equivalent and equally logged.

## 7. Review gallery (Phase 2)

### 7.1 Serving

`photo-curator review <curated-dir>` or `r` on the Results screen. Stdlib
`http.server` on `127.0.0.1:<random free port>`, bound to localhost only,
with a per-session token in the URL; opens the default browser. No external
network, no telemetry, nothing listens beyond the session.

### 7.2 UI (static, bundled)

- Sidebar: Top Picks, Albums, each library bucket, Duplicates, Rejected,
  Needs Review — with counts.
- Main: virtualized thumbnail grid (thumbnails generated during stage 5 into
  `report-assets/thumbs/`, 256 px). Click → full-size lightbox with the
  decision evidence (verdict, tier, reasons) alongside.
- Keyboard-first: arrows navigate, `G` promote to top-picks, `B` bucket
  picker (fuzzy), `X` reject, `U` undo, space multi-select, `Enter` lightbox.
- Needs Review is presented first ("42 photos need your eyes") as a
  one-by-one triage flow: keep / reject / re-bucket, single keystroke each.
- Chat panel docked right — same agent, same abilities as §6.3.

### 7.3 Corrections API

```
GET  /api/state                     → buckets, counts, photos, verdicts
POST /api/action {photo, from, to}  → move/promote/rescue/reject
POST /api/undo
POST /api/chat {message}            → chat agent reply (may include actions)
```

Every action: (a) moves the file inside the curated tree (hardlink-aware),
(b) appends a **correction event** to `~/.photo-curator/corrections.jsonl`:

```json
{"ts": "...", "run": "<manifest id>", "photo": "IMG_2041.jpg",
 "pipeline_said": {"verdict": "rejected", "why": "blur-extreme, 2 passes agreed"},
 "user_said": {"verdict": "top-pick"},
 "evidence": {"faces": 2, "sharpness": 18.4, "bucket": "kids-family",
              "llm_description": "two children laughing on a swing"}}
```

(c) updates `manifest.json` with a `user_overrides` section — the manifest
never lies about what the pipeline decided vs. what the human changed.

## 8. Learning: memory.md (Phase 2)

### 8.1 The file

`~/.photo-curator/memory.md` — global, plain English, user-ownable:

```markdown
# What I've learned about your taste
- Be lenient on blur when children are the subject. (learned 2026-07-05,
  from 7 rescues; applies as: blur leniency for photos with faces of kids)
- You rarely keep food photos; keep them out of highlights. (2026-07-05)
```

### 8.2 The loop

1. Review session ends (browser tab closed or explicit "done").
2. The memory updater clusters new correction events and asks the LLM to
   propose at most 3 generalizations, each tied to its evidence
   (schema-forced: `{statement, evidence_refs, confidence, config_hint?}`).
3. Proposals needing at least **3 consistent corrections** each are shown to
   the user: "I noticed you rescued 7 photos of kids — remember that you
   prefer keeping those even when soft? [Y/n]". Confirmed → appended to
   memory.md. Declined → recorded so it is not re-proposed (R4).
4. Next run: memory.md entries are injected as `prompt_suffix` deltas, and
   entries with a `config_hint` (e.g. blur leniency) also nudge the matching
   whitelisted threshold. Both appear in the Confirm screen and the manifest
   like any other delta — memory is just persistent, consented intent.

Contradiction rule: a new confirmed entry that conflicts with an old one
replaces it (the file keeps one line per preference, newest wins, history in
corrections.jsonl).

## 9. Loop engineering in the pipeline

Research verdict (kept deliberately narrow):

- **Objective stages stay single-pass.** Blur, exposure, duplicates: loops
  add cost, not accuracy. No change.
- **Confidence-gated critique loop** on the two subjective decisions:
  - *Best-of-burst*: when the tournament winner's classical-agreement ratio
    is within 10% of the runner-up (a genuinely close call), one extra
    critique round: show both frames, ask for a decisive comparison with
    stated reasons; disagree twice → needs-review (existing behavior).
  - *Highlights*: after the greedy selection, one evaluator pass scores the
    selected set against the rubric; picks scoring in the bottom decile with
    a rubric contradiction get one reconsider round against the next-best
    excluded candidate. Cap: one loop, never iterate to convergence.
- Hard budget: critique loops may add at most **+15% LLM calls** to a run
  (enforced counter; when exhausted, fall back to single-pass behavior).
  This keeps Gemma/Llama-class local models fast while measurably improving
  exactly the decisions users correct most.

## 10. Packaging & distribution (Phase 1)

- **GitHub Actions release matrix** → PyInstaller one-file binaries:
  `photo-curator-macos-arm64`, `-macos-x86_64`, `-linux-x86_64`,
  `-linux-arm64`, `-windows-x86_64.exe`. Textual, OpenCV-headless, Pillow,
  LiteLLM included; expect 80–120 MB.
- **Installer one-liners**: `curl -fsSL <url>/install.sh | sh` (macOS/Linux,
  picks the right binary, puts it on PATH) and an `install.ps1` for Windows.
- `pip install photo-curator` remains for Python users.
- CI smoke test per artifact: run the binary with `--version` and a headless
  Pilot journey on each OS runner before the release is published.
- macOS: binaries are ad-hoc signed; the README documents the
  right-click-open first-launch step (no notarization dependency in v1).

## 11. Error handling (additions over pipeline spec)

| Failure | Behavior |
|---|---|
| Ollama down / API unreachable at picker | Detected on Welcome; picker shows the model greyed with the reason and a fix hint |
| API key invalid | Caught at qualification (first real call); re-prompt for key, old key kept until new one works |
| Cloud rate limit / 429 mid-run | Exponential backoff ×5; then pause the run with a resumable prompt, never lose state |
| Cost meter exceeds user-set cap (optional cap asked on Confirm for cloud) | Auto-pause + ask |
| Review server port busy | Next free port; token URL printed and opened |
| Browser never opens (headless) | URL printed; gallery also usable from another machine ONLY if user passes `--host` explicitly |
| corrections.jsonl corrupt line | Skip line, warn, never block review |
| memory.md hand-edited into free-form prose | Fine by design — it is injected as text; only `config_hint` lines need structure and are regenerated from corrections if absent |
| Chat LLM returns invalid delta JSON after repairs | The message is answered conversationally with "I couldn't turn that into a safe change"; run untouched |

## 12. Testing requirements

1. Everything in the pipeline spec still passes untouched (63 tests).
2. TUI: Pilot-driven headless journeys — first run, returning user, cloud
   consent flow, mid-run steering, cancel/resume.
3. Intent engine: golden suite of ≥50 phrasings → expected delta documents
   (MockModel returns canned parses; a second suite validates the whitelist
   rejects out-of-bounds paths).
4. Steering: property test — a run with deltas applied at photo k equals a
   fresh run whose config changes at photo k (determinism with steering).
5. Review API: full CRUD + undo + corrections.jsonl append, via HTTP client
   against the real server on a synthetic curated tree.
6. Memory loop: corrections → proposals → confirm/decline → injection next
   run, all with MockModel.
7. Critique loops: forced-close-call fixtures prove the loop triggers, the
   budget caps it, and disagreement still lands in needs-review.
8. Packaging: per-OS CI smoke (binary boots, version, headless journey).

## 13. Out of scope (v-this)

- Editing photos, RAW development, video.
- Multi-user profiles / sync of memory.md across machines.
- Fine-tuned or embedding-based taste models (memory.md is the v1 learner).
- Mobile/native apps; remote (non-localhost) review by default.
- OAuth device flows for providers (API keys only in this phase; the
  keystore interface is written so OAuth tokens can slot in later).
