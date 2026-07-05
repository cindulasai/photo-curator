# Photo Curator — Sort Thousands of Photos in Minutes, Not Hours

**Photo Curator** is a free, open-source tool that automatically organizes your photo library the way *you* would — if you had all day and never got tired.

You point it at a folder. It quietly goes through every photo, decides what's worth keeping, groups similar shots, picks the best one from each burst, sorts everything into tidy albums, and even picks your highlights for you. Your originals are never touched.

---

## Why people love it

Most of us have thousands of photos sitting in a folder somewhere — blurry shots, duplicates, accidental presses of the shutter button, and in between all that, genuine memories worth keeping. Sorting through them by hand takes hours and it's exhausting.

Photo Curator handles the tedious part. It does what a careful human would do: throw out the obviously bad shots, pick the sharpest photo from a burst, sort everything into the right album, and surface the handful of photos that really matter.

It runs entirely on your computer. Your photos never leave your machine.

---

## What it does

- **Cleans up the junk** — blurry shots, too-dark or washed-out photos, accidental captures, duplicates
- **Picks the best from each burst** — when you shot 6 frames of the same moment, it keeps the sharpest one
- **Sorts into 16 albums automatically** — People, Travel, Nature, Celebrations, Kids & Family, Food, Pets, and more
- **Builds a highlights reel** — finds your top photos for sharing or an album
- **Never deletes anything** — everything it rejects goes into a "review" folder so you always have the final say
- **Works offline, completely private** — powered by a local AI model running on your own computer

---

## How it works (the short version)

It uses two things together: classic image analysis (checking sharpness, brightness, and whether photos look identical) plus a local AI vision model that actually *looks* at your photos and understands what's in them — just like you would.

When it's confident, it acts. When it's not sure, it sets the photo aside for you to check. It never guesses on anything important.

---

## Quick start

You'll need [Python 3.11+](https://python.org) and [Ollama](https://ollama.com) installed.

```bash
# Install
pip install -e ".[dev]"

# Pull the vision model (free, runs locally)
ollama pull qwen2.5vl:7b

# Check the model is good enough
photo-curator qualify

# Preview what it would do — no changes made
photo-curator run ~/Pictures --dry-run

# Run it
photo-curator run ~/Pictures
```

After it runs, you'll find a new folder next to your photos with everything neatly organized, a visual report showing what it did and why, and a small "needs-review" pile for anything it wasn't sure about.

---

## What you get

```
curated-2026-07-05/
├── top-picks/          ← your highlights, ready to share
├── albums/             ← organized by event and place
├── library/            ← everything sorted into 16 categories
├── duplicates/         ← grouped, best one marked
├── rejected/           ← blurry, dark, accidental — safe to delete
├── needs-review/       ← it wasn't sure; your call
└── REPORT.md           ← a plain-English summary of every decision
```

---

## Works with any vision AI model

Built around [Ollama](https://ollama.com), so it works with Qwen, LLaVA, Gemma, Llama, and any other model that can look at images. The built-in qualification test checks that your chosen model is sharp enough before it touches your library.

---

## Safe by design

- Your originals are **never modified or moved**
- Every decision comes with a plain-English reason
- Anything uncertain lands in `needs-review/`, never in the bin
- Two AI passes required before anything is marked as reject — it can't be trigger-happy

---

## Run the tests

No model or photos needed — the full test suite runs on synthetic images:

```bash
python -m pytest
```

63 tests. All pass.

---

## For the curious

The full design spec lives in `docs/superpowers/specs/` and the agent skill entry point is `SKILL.md` — useful if you want to wire this into your own AI agent or workflow.
