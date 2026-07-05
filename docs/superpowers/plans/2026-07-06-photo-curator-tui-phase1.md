# Photo Curator TUI App — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the photo-curator TUI app: Textual UI, any vision model via LiteLLM (vision-only picker), OS-keychain keystore, chat before/during/after runs with auditable config deltas, and per-OS one-file binaries.

**Architecture:** One Python process. The Textual app owns the event loop; the existing 5-stage pipeline runs in a worker thread; a thread-safe SteeringQueue is the only channel between chat and pipeline, drained at photo boundaries. LiteLLM sits behind the existing `VisionModel` protocol next to `OllamaModel`.

**Tech Stack:** Python ≥3.11, Textual, LiteLLM, keyring, PyInstaller, GitHub Actions. Existing: Pillow, OpenCV(<5), ImageHash, PyYAML, requests, jsonschema, pytest.

## Global Constraints (from spec §2)

- R1: Python only; no Node/Rust anywhere.
- R2: model picker shows vision models only; filtering is mechanical (LiteLLM `supports_vision`, OpenRouter `input_modalities`, Ollama capability probe).
- R3: source photos read-only (inherited; do not touch pipeline write paths).
- R4: every chat suggestion becomes an auditable config delta; recorded in the run's store meta `user_deltas` and manifest.
- R5: steering deltas apply at photo boundaries, recorded with `effective_from` photo index; resume re-applies recorded deltas.
- R6: secrets via `keyring` (macOS Keychain / Windows Credential Manager / Secret Service); encrypted-file fallback only when no keychain backend exists; keys never in config files, logs, or manifest.
- R7: cloud model selection shows a one-time per-provider consent screen.
- R8: qualification gate (existing `run_gate`) required for every model, local or cloud.
- R9: worst-case first-run path is 3 interactions (model, folder, Enter).
- R10: no terminal image protocols; TUI must work over SSH.
- Textual/LiteLLM/keyring live in the `app` optional-dependency extra; `curator.tui` imports must not break `pip install photo-curator` base installs.
- Existing 63 tests must stay green after every task.
- Work on branch `tui-phase1`, merge to `main` when the plan completes.

## File structure

```
curator/providers/__init__.py       (empty)
curator/providers/keystore.py       KeyStore: keyring + encrypted-file fallback (Task 1)
curator/providers/catalog.py        ModelEntry + 3 vision-only sources (Task 4)
curator/providers/registry.yaml     shipped recommended models (Task 5)
curator/providers/registry.py       registry load/merge, tiering, cost estimate (Task 5)
curator/providers/litellm_model.py  LiteLLMModel (VisionModel impl) (Task 6)
curator/chat/__init__.py            (empty)
curator/chat/deltas.py              whitelist, validate, apply, describe (Task 2)
curator/chat/steering.py            SteeringQueue (Task 3, with pipeline hooks)
curator/chat/intent.py              free text -> delta doc (Task 7)
curator/chat/qa.py                  post-run Q&A over the store (Task 8)
curator/prompts/intent.md, qa.md    (Tasks 7, 8)
curator/schemas/intent.schema.json, qa.schema.json
curator/tui/__init__.py             (empty)
curator/tui/detect.py               environment detection (Task 9)
curator/tui/state.py                AppState dataclass (Task 9)
curator/tui/app.py                  CuratorApp + screen wiring (Task 9)
curator/tui/screens.py              all screens (Tasks 9-12; one file, screens are small)
curator/tui/runner.py               PipelineRunner thread (Task 11)
packaging/photo-curator.spec        PyInstaller spec (Task 14)
scripts/install.sh, scripts/install.ps1 (Task 14)
.github/workflows/release.yml       (Task 14)
```

Pipeline files modified: `curator/config.py` (+2 default keys), `curator/prompts.py` (suffix injection), `curator/inventory.py` (skip_globs), `curator/stage3.py` (steer hook), `curator/cli.py` (notify/steer params, no-args TUI launch, --version).

---

### Task 0: Branch + extras + test plumbing

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `photo-curator[app]` extra; `asyncio_mode=auto` so Textual Pilot tests are plain `async def`.

- [ ] **Step 1: Branch**

```bash
git checkout -b tui-phase1
```

- [ ] **Step 2: Edit pyproject.toml** — replace the `[project.optional-dependencies]` section with:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "textual>=0.60", "keyring>=24"]
app = ["textual>=0.60", "litellm>=1.40", "keyring>=24"]
```

and append at the end of the file:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

Note: `litellm` is NOT in dev — tests stub it via `sys.modules` so CI stays light.

- [ ] **Step 3: Install and verify baseline**

Run: `pip install -e ".[dev]" && python -m pytest -q`
Expected: `63 passed`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml && git commit -m "chore: app extras + pytest-asyncio for TUI phase 1"
```

---

### Task 1: KeyStore

**Files:**
- Create: `curator/providers/__init__.py` (empty), `curator/providers/keystore.py`
- Test: `tests/test_keystore.py`

**Interfaces:**
- Produces: `KeyStore(home: Path|None = None, backend: str = "auto")` with `get(provider) -> str|None`, `set(provider, key)`, `delete(provider)`, attribute `using_keychain: bool`. Env var (`OPENAI_API_KEY` etc. per `ENV_MAP`) always wins on `get`. `ENV_MAP: dict[str, str]` module constant.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_keystore.py
from curator.providers.keystore import KeyStore, ENV_MAP

def test_file_fallback_roundtrip(tmp_path):
    ks = KeyStore(home=tmp_path, backend="file")
    assert ks.get("openai") is None
    ks.set("openai", "sk-test-123")
    assert ks.get("openai") == "sk-test-123"
    assert KeyStore(home=tmp_path, backend="file").get("openai") == "sk-test-123"  # persists
    ks.delete("openai")
    assert ks.get("openai") is None

def test_key_never_stored_plaintext(tmp_path):
    ks = KeyStore(home=tmp_path, backend="file")
    ks.set("openrouter", "sk-or-SECRETVALUE")
    blobs = b"".join(p.read_bytes() for p in tmp_path.iterdir())
    assert b"SECRETVALUE" not in blobs

def test_env_var_wins(tmp_path, monkeypatch):
    ks = KeyStore(home=tmp_path, backend="file")
    ks.set("openai", "sk-stored")
    monkeypatch.setenv(ENV_MAP["openai"], "sk-env")
    assert ks.get("openai") == "sk-env"

def test_unknown_provider_env_name(tmp_path, monkeypatch):
    monkeypatch.setenv("FOO_API_KEY", "sk-foo")
    assert KeyStore(home=tmp_path, backend="file").get("foo") == "sk-foo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_keystore.py -q`
Expected: FAIL — `ModuleNotFoundError: curator.providers`

- [ ] **Step 3: Implement**

```python
# curator/providers/keystore.py
from __future__ import annotations
import base64, hashlib, json, os, secrets
from pathlib import Path

SERVICE = "photo-curator"
ENV_MAP = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
           "gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY",
           "deepseek": "DEEPSEEK_API_KEY", "minimax": "MINIMAX_API_KEY"}


def _keystream(key: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(out[:n])


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, _keystream(key, len(data))))


class KeyStore:
    """API keys: OS keychain via `keyring`; encrypted-file fallback when no
    keychain backend exists (R6). Env vars always win and are never written."""

    def __init__(self, home: Path | None = None, backend: str = "auto"):
        self.home = Path(home) if home else Path.home() / ".photo-curator"
        self._kr = self._load_keyring() if backend == "auto" else None
        self.using_keychain = self._kr is not None

    @staticmethod
    def _load_keyring():
        try:
            import keyring
            kr = keyring.get_keyring()
            if "fail" in type(kr).__module__ or "null" in type(kr).__module__:
                return None
            return keyring
        except Exception:
            return None

    def get(self, provider: str) -> str | None:
        env = os.environ.get(ENV_MAP.get(provider, f"{provider.upper()}_API_KEY"))
        if env:
            return env
        if self._kr:
            return self._kr.get_password(SERVICE, provider)
        return self._file_all().get(provider)

    def set(self, provider: str, key: str) -> None:
        if self._kr:
            self._kr.set_password(SERVICE, provider, key)
            return
        data = self._file_all()
        data[provider] = key
        self._file_save(data)

    def delete(self, provider: str) -> None:
        if self._kr:
            try:
                self._kr.delete_password(SERVICE, provider)
            except Exception:
                pass
            return
        data = self._file_all()
        data.pop(provider, None)
        self._file_save(data)

    # ---- encrypted-file fallback ----
    def _machine_key(self) -> bytes:
        kf = self.home / ".machine-key"
        if not kf.exists():
            self.home.mkdir(parents=True, exist_ok=True)
            kf.write_bytes(secrets.token_bytes(32))
            kf.chmod(0o600)
        return kf.read_bytes()

    def _file_all(self) -> dict:
        f = self.home / "keys.enc"
        if not f.exists():
            return {}
        blob = base64.b64decode(f.read_bytes())
        return json.loads(_xor(blob, self._machine_key()))

    def _file_save(self, data: dict) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        blob = _xor(json.dumps(data).encode(), self._machine_key())
        f = self.home / "keys.enc"
        f.write_bytes(base64.b64encode(blob))
        f.chmod(0o600)
```

Also create empty `curator/providers/__init__.py`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_keystore.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add curator/providers tests/test_keystore.py
git commit -m "feat: KeyStore - keychain-first secret storage with encrypted fallback"
```

---

### Task 2: Config deltas (whitelist, apply, describe)

**Files:**
- Create: `curator/chat/__init__.py` (empty), `curator/chat/deltas.py`
- Test: `tests/test_deltas.py`

**Interfaces:**
- Consumes: `curator.config.DEFAULTS` shape (dot paths like `triage.blur_sharp_min`).
- Produces: `DeltaError(ValueError)`; `validate_deltas(doc: dict) -> list[dict]` (normalizes `op`/`why`, raises DeltaError); `apply_deltas(cfg: dict, deltas: list[dict]) -> dict` (pure, deep-copies); `describe(deltas) -> list[str]`. Delta shape: `{"path": str, "op": "set"|"append", "value": any, "why": str}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deltas.py
import pytest
from curator.chat.deltas import DeltaError, apply_deltas, describe, validate_deltas
from curator.config import load_config

def test_set_and_append():
    cfg = load_config(None)
    out = apply_deltas(cfg, [
        {"path": "triage.blur_sharp_min", "value": 80},
        {"path": "buckets.disable", "op": "append", "value": "food-drink"},
        {"path": "prompt_suffix", "op": "append",
         "value": "Weight photos of children highly."},
    ])
    assert out["triage"]["blur_sharp_min"] == 80
    assert "food-drink" in out["buckets"]["disable"]
    assert out["prompt_suffix"] == ["Weight photos of children highly."]
    assert cfg["triage"]["blur_sharp_min"] == 60.0          # original untouched

def test_append_dedupes_and_defaults_op():
    cfg = load_config(None)
    d = validate_deltas({"deltas": [{"path": "skip_globs", "value": "WhatsApp/*"}]})
    assert d[0]["op"] == "append"                            # list paths default to append
    out = apply_deltas(cfg, d + d)
    assert out["skip_globs"] == ["WhatsApp/*"]

def test_whitelist_rejects():
    for bad in ["model", "ollama_url", "llm.seed", "events.gap_hours", "nonsense"]:
        with pytest.raises(DeltaError):
            validate_deltas({"deltas": [{"path": bad, "value": 1}]})

def test_bad_shape_rejects():
    with pytest.raises(DeltaError):
        validate_deltas({"deltas": [{"path": "triage.blur_sharp_min"}]})   # no value
    with pytest.raises(DeltaError):
        validate_deltas({"deltas": [{"path": "rubric.emotional", "op": "delete", "value": 0}]})

def test_describe_human_readable():
    lines = describe([{"path": "triage.blur_sharp_min", "op": "set", "value": 80,
                       "why": "stricter blur"}])
    assert lines == ["set triage.blur_sharp_min -> 80  (stricter blur)"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_deltas.py -q`
Expected: FAIL — `ModuleNotFoundError: curator.chat`

- [ ] **Step 3: Implement**

```python
# curator/chat/deltas.py
from __future__ import annotations
import copy

# Spec §6.1 — ONLY these paths are steerable. llm.*, model, events.* are not.
WHITELIST_PREFIXES = ("triage.", "top_picks.", "rubric.")
WHITELIST_EXACT = {"buckets.disable", "buckets.custom", "prompt_suffix", "skip_globs"}
_LIST_PATHS = {"buckets.disable", "buckets.custom", "prompt_suffix", "skip_globs"}
_OPS = {"set", "append"}


class DeltaError(ValueError):
    pass


def _allowed(path: str) -> bool:
    return path in WHITELIST_EXACT or path.startswith(WHITELIST_PREFIXES)


def validate_deltas(doc: dict) -> list[dict]:
    deltas = doc.get("deltas")
    if not isinstance(deltas, list):
        raise DeltaError("deltas must be a list")
    for d in deltas:
        if not isinstance(d, dict) or "path" not in d or "value" not in d:
            raise DeltaError(f"delta needs path and value: {d!r}")
        if not _allowed(d["path"]):
            raise DeltaError(f"path not steerable: {d['path']}")
        d.setdefault("op", "append" if d["path"] in _LIST_PATHS else "set")
        if d["op"] not in _OPS:
            raise DeltaError(f"unknown op: {d['op']}")
        d.setdefault("why", "")
    return deltas


def apply_deltas(cfg: dict, deltas: list[dict]) -> dict:
    out = copy.deepcopy(cfg)
    for d in validate_deltas({"deltas": deltas}):
        node = out
        parts = d["path"].split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        leaf = parts[-1]
        if d["op"] == "append":
            cur = list(node.get(leaf) or [])
            vals = d["value"] if isinstance(d["value"], list) else [d["value"]]
            node[leaf] = cur + [v for v in vals if v not in cur]
        else:
            node[leaf] = d["value"]
    return out


def describe(deltas: list[dict]) -> list[str]:
    lines = []
    for d in deltas:
        verb = "add" if d.get("op") == "append" else "set"
        line = f"{verb} {d['path']} -> {d['value']}"
        if d.get("why"):
            line += f"  ({d['why']})"
        lines.append(line)
    return lines
```

Also create empty `curator/chat/__init__.py`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_deltas.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add curator/chat tests/test_deltas.py
git commit -m "feat: whitelisted config deltas - validate, apply, describe"
```

---

### Task 3: Pipeline hooks — prompt_suffix, skip_globs, steer callback

**Files:**
- Modify: `curator/config.py`, `curator/prompts.py`, `curator/inventory.py`, `curator/stage3.py`, `curator/cli.py`
- Test: `tests/test_pipeline_hooks.py`

**Interfaces:**
- Produces: `cfg["prompt_suffix"]: list[str]` and `cfg["skip_globs"]: list[str]` in DEFAULTS; `render(name, cfg)` appends suffix block for the four analysis prompts; `run_stage1` skips glob-matched files; `run_stage3(..., steer=None)` where `steer(cfg, idx) -> dict|None` is called before each photo — returning a dict swaps cfg AND re-renders prompts; `run_pipeline(args, model_factory, steer=None, notify=None)` where notify replaces prints.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_hooks.py
from curator.config import load_config
from curator.db import Store
from curator.inventory import run_stage1
from curator.prompts import render

def test_prompt_suffix_injected():
    cfg = load_config(None)
    cfg["prompt_suffix"] = ["Weight photos of children highly."]
    for name in ["analyze_photo", "analyze_photo_reworded"]:
        assert "Weight photos of children highly." in render(name, cfg)
    assert "children" in render("tournament", cfg, COUNT=2)
    base = load_config(None)
    assert "children" not in render("analyze_photo", base)

def test_skip_globs_in_stage1(tmp_path, img_factory):
    src = tmp_path / "src"
    img_factory(src / "keep.jpg", "scene", seed=1)
    img_factory(src / "WhatsApp" / "wa1.jpg", "scene", seed=2)
    cfg = load_config(None)
    cfg["skip_globs"] = ["WhatsApp/*"]
    store = Store(tmp_path / "c.db")
    s = run_stage1(src, store, cfg)
    assert s["photos"] == 1 and s["skipped"] == 1
    assert store.photo("WhatsApp/wa1.jpg")["status"] == "skipped"

def test_stage3_steer_swaps_cfg(tmp_path, img_factory):
    from curator.model import MockModel
    from curator.stage2 import run_stage2
    from curator.stage3 import run_stage3
    src = tmp_path / "src"
    for i in range(3):
        img_factory(src / f"p{i}.jpg", "scene", seed=10 + i,
                    exif_dt=f"2026:05:12 10:0{i}:00")
    cfg = load_config(None)
    store = Store(tmp_path / "c.db")
    run_stage1(src, store, cfg)
    run_stage2(src, store, cfg, tmp_path / "work")
    prompts_seen = []
    def handler(paths, prompt, schema):
        prompts_seen.append(prompt)
        return {"bucket": {"primary": "everyday-misc", "confidence": 0.9, "alternates": []},
                "tags": [], "description": "x",
                "people": {"count": 0, "eyes_closed": "n/a", "expression_quality": "n/a"},
                "utility": {"is_screenshot": "no", "is_document": "no", "is_accidental": "no"},
                "quality_judgment": {"fatal": "no", "note": "x"},
                "rubric": {"emotional": 1, "people_engagement": 0, "composition_light": 1,
                           "scene_appeal": 1, "novelty": 0, "justifications": {}}}
    def steer(cfg_in, idx):
        if idx == 1:                       # apply before the 2nd photo
            out = dict(cfg_in)
            out["prompt_suffix"] = ["STEERED"]
            return out
        return None
    run_stage3(src, store, cfg, MockModel(handler), steer=steer)
    assert "STEERED" not in prompts_seen[0]
    assert all("STEERED" in p for p in prompts_seen[1:])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_pipeline_hooks.py -q`
Expected: FAIL — suffix absent / `KeyError: 'skip_globs'` / unexpected keyword `steer`

- [ ] **Step 3: Implement the four patches**

`curator/config.py` — in `DEFAULTS`, after the `"fast"` line add:

```python
    "prompt_suffix": [],   # plain-English user preferences, appended to analysis prompts
    "skip_globs": [],      # rel-path globs excluded at inventory
```

`curator/prompts.py` — at the end of `render`, replace `return text` with:

```python
    suffix = cfg.get("prompt_suffix") or []
    if suffix and name in ("analyze_photo", "analyze_photo_reworded",
                           "tournament", "final_verification"):
        text += ("\n\nThe photo owner asked you to honor these preferences:\n"
                 + "\n".join(f"- {s}" for s in suffix))
    return text
```

`curator/inventory.py` — add `import fnmatch` at the top, and inside `run_stage1`'s `for p in files:` loop, right after `rel = str(p.relative_to(source))` and the resume check, insert:

```python
        if any(fnmatch.fnmatch(rel, g) for g in cfg.get("skip_globs", [])):
            store.upsert_photo(rel, kind="photo", status="skipped", stage_done=1,
                               size=p.stat().st_size, mtime=p.stat().st_mtime)
            counts["skipped"] += 1
            continue
```

(Place it BEFORE the `st = p.stat()` line; keep the existing resume check above it.)

`curator/stage3.py` — change the signature and loop head:

```python
def run_stage3(source: Path, store: Store, cfg: dict, model,
               progress: Callable[[str], None] = lambda s: None,
               steer: Callable[[dict, int], dict | None] | None = None) -> dict:
```

and at the top of the `for i, photo in enumerate(todo, 1):` body insert:

```python
        if steer is not None:
            new_cfg = steer(cfg, i - 1)
            if new_cfg is not None:                      # boundary-applied delta (R5)
                cfg = new_cfg
                a_prompt = prompts.render("analyze_photo", cfg)
                r_prompt = prompts.render("analyze_photo_reworded", cfg)
```

`curator/cli.py` — change `run_pipeline` signature to
`def run_pipeline(args, model_factory=_default_factory, steer=None, notify=None) -> int:`
add at the top of the function body:

```python
    say = notify or print
```

replace every bare `print(f"[stage ...` call with `say(...)` (stderr prints stay `print(..., file=sys.stderr)`), and pass `steer=steer` into the `run_stage3(...)` call.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: 63 + 3 new = 66 passed (config_hash changes with the two new DEFAULTS keys — no test asserts a literal hash, so nothing else breaks)

- [ ] **Step 5: Commit**

```bash
git add curator/config.py curator/prompts.py curator/inventory.py curator/stage3.py curator/cli.py tests/test_pipeline_hooks.py
git commit -m "feat: pipeline hooks - prompt_suffix, skip_globs, boundary steer callback"
```

---

### Task 3b: SteeringQueue

**Files:**
- Create: `curator/chat/steering.py`
- Test: `tests/test_steering.py`

**Interfaces:**
- Consumes: `validate_deltas`, `apply_deltas` (Task 2); `Store.set_meta/get_meta` (existing).
- Produces: `SteeringQueue(store=None)` — `.push(deltas: list[dict])` (validates, raises DeltaError), `.__call__(cfg, idx) -> dict|None` (drains queue; None when empty — stage3 skips re-render), `.applied: list[{"deltas", "effective_from"}]`, `.load_applied(cfg) -> dict` (resume: re-applies recorded deltas from store meta `user_deltas`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_steering.py
import json, pytest
from curator.chat.deltas import DeltaError
from curator.chat.steering import SteeringQueue
from curator.config import load_config
from curator.db import Store

def test_drain_at_boundary(tmp_path):
    store = Store(tmp_path / "c.db")
    q = SteeringQueue(store)
    cfg = load_config(None)
    assert q(cfg, 0) is None                                  # empty -> None
    q.push([{"path": "triage.blur_sharp_min", "value": 80}])
    out = q(cfg, 3)
    assert out["triage"]["blur_sharp_min"] == 80
    assert q(out, 4) is None                                  # drained
    assert q.applied == [{"deltas": [{"path": "triage.blur_sharp_min", "op": "set",
                                      "value": 80, "why": ""}], "effective_from": 3}]
    assert json.loads(store.get_meta("user_deltas"))[0]["effective_from"] == 3

def test_push_validates():
    with pytest.raises(DeltaError):
        SteeringQueue().push([{"path": "llm.seed", "value": 1}])

def test_resume_reapplies(tmp_path):
    store = Store(tmp_path / "c.db")
    q1 = SteeringQueue(store)
    cfg = load_config(None)
    q1.push([{"path": "prompt_suffix", "value": "keep kids"}])
    cfg = q1(cfg, 5)
    q2 = SteeringQueue(store)                                 # fresh process
    resumed = q2.load_applied(load_config(None))
    assert resumed["prompt_suffix"] == ["keep kids"]
    assert q2.applied and q2.applied[0]["effective_from"] == 5
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_steering.py -q`
Expected: FAIL — no module `curator.chat.steering`

- [ ] **Step 3: Implement**

```python
# curator/chat/steering.py
from __future__ import annotations
import json, queue
from .deltas import apply_deltas, validate_deltas


class SteeringQueue:
    """Thread-safe channel: chat pushes deltas, the pipeline drains them at
    photo boundaries (spec §6.2, R5). Applied deltas are persisted to the
    run's store meta so resume re-applies them."""

    def __init__(self, store=None):
        self._q: queue.Queue = queue.Queue()
        self._store = store
        self.applied: list[dict] = []

    def push(self, deltas: list[dict]) -> None:
        validate_deltas({"deltas": deltas})
        self._q.put(deltas)

    def __call__(self, cfg: dict, idx: int) -> dict | None:
        changed = False
        while True:
            try:
                deltas = self._q.get_nowait()
            except queue.Empty:
                break
            cfg = apply_deltas(cfg, deltas)
            self.applied.append({"deltas": deltas, "effective_from": idx})
            changed = True
        if changed and self._store is not None:
            self._store.set_meta("user_deltas", json.dumps(self.applied))
        return cfg if changed else None

    def load_applied(self, cfg: dict) -> dict:
        if self._store is not None:
            raw = self._store.get_meta("user_deltas")
            if raw:
                self.applied = json.loads(raw)
                for entry in self.applied:
                    cfg = apply_deltas(cfg, entry["deltas"])
        return cfg
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_steering.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add curator/chat/steering.py tests/test_steering.py
git commit -m "feat: thread-safe SteeringQueue with resume re-apply"
```

---

### Task 4: Vision-only model catalog

**Files:**
- Create: `curator/providers/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Produces: `@dataclass ModelEntry(id, provider, source, local, input_cost=None, output_cost=None, installed=True)`; `ollama_vision_models(url, timeout=2.0) -> list[ModelEntry]`; `litellm_vision_models() -> list[ModelEntry]` (imports litellm lazily); `openrouter_vision_models(timeout=3.0) -> list[ModelEntry]`; `all_vision_models(cfg, include_openrouter=True) -> list[ModelEntry]` (dedup by id, ollama first). All network failures return `[]` — never raise (R2 filtering is best-effort; the gate is the arbiter).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_catalog.py
import sys, types
from curator.providers.catalog import (ModelEntry, all_vision_models,
                                       litellm_vision_models, ollama_vision_models,
                                       openrouter_vision_models)
from curator.config import load_config

class FakeResp:
    def __init__(self, payload): self._p = payload
    def json(self): return self._p
    def raise_for_status(self): pass

def test_ollama_probe_filters_vision(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResp({"models": [{"name": "qwen2.5vl:7b"}, {"name": "llama3:8b"}]})
    def fake_post(url, json=None, timeout=None):
        if json["model"] == "qwen2.5vl:7b":
            return FakeResp({"capabilities": ["completion", "vision"],
                             "details": {"families": ["qwen2vl"]}})
        return FakeResp({"capabilities": ["completion"],
                         "details": {"families": ["llama"]}})
    monkeypatch.setattr("curator.providers.catalog.requests.get", fake_get)
    monkeypatch.setattr("curator.providers.catalog.requests.post", fake_post)
    out = ollama_vision_models("http://localhost:11434")
    assert [e.id for e in out] == ["ollama/qwen2.5vl:7b"]
    assert out[0].local and out[0].input_cost == 0.0

def test_ollama_down_returns_empty(monkeypatch):
    import requests
    def boom(*a, **k): raise requests.ConnectionError()
    monkeypatch.setattr("curator.providers.catalog.requests.get", boom)
    assert ollama_vision_models("http://localhost:11434") == []

def test_litellm_filter(monkeypatch):
    fake = types.ModuleType("litellm")
    fake.model_cost = {
        "gpt-4o-mini": {"supports_vision": True, "mode": "chat",
                        "litellm_provider": "openai",
                        "input_cost_per_token": 1.5e-07, "output_cost_per_token": 6e-07},
        "gpt-3.5-turbo": {"supports_vision": False, "mode": "chat",
                          "litellm_provider": "openai"},
        "whisper-1": {"supports_vision": False, "mode": "audio_transcription"},
    }
    monkeypatch.setitem(sys.modules, "litellm", fake)
    out = litellm_vision_models()
    assert [e.id for e in out] == ["gpt-4o-mini"]
    assert out[0].provider == "openai" and not out[0].local

def test_openrouter_modality_filter(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResp({"data": [
            {"id": "google/gemini-2.0-flash", "architecture":
             {"input_modalities": ["text", "image"]},
             "pricing": {"prompt": "0.0000001", "completion": "0.0000004"}},
            {"id": "meta/llama-3-8b", "architecture": {"input_modalities": ["text"]},
             "pricing": {}},
        ]})
    monkeypatch.setattr("curator.providers.catalog.requests.get", fake_get)
    out = openrouter_vision_models()
    assert [e.id for e in out] == ["openrouter/google/gemini-2.0-flash"]

def test_all_dedupes(monkeypatch):
    monkeypatch.setattr("curator.providers.catalog.ollama_vision_models",
                        lambda url, timeout=2.0: [ModelEntry("ollama/a", "ollama", "ollama", True)])
    monkeypatch.setattr("curator.providers.catalog.litellm_vision_models",
                        lambda: [ModelEntry("x", "openai", "litellm", False)])
    monkeypatch.setattr("curator.providers.catalog.openrouter_vision_models",
                        lambda timeout=3.0: [ModelEntry("x", "openrouter", "openrouter", False)])
    out = all_vision_models(load_config(None))
    assert [e.id for e in out] == ["ollama/a", "x"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_catalog.py -q`
Expected: FAIL — no module `curator.providers.catalog`

- [ ] **Step 3: Implement**

```python
# curator/providers/catalog.py
from __future__ import annotations
from dataclasses import dataclass
import requests


@dataclass
class ModelEntry:
    id: str
    provider: str
    source: str            # "ollama" | "litellm" | "openrouter" | "custom"
    local: bool
    input_cost: float | None = None    # USD per token
    output_cost: float | None = None
    installed: bool = True


def ollama_vision_models(url: str, timeout: float = 2.0) -> list[ModelEntry]:
    base = url.rstrip("/")
    try:
        tags = requests.get(f"{base}/api/tags", timeout=timeout).json().get("models", [])
    except (requests.RequestException, ValueError):
        return []
    out = []
    for m in tags:
        name = m.get("name", "")
        try:
            show = requests.post(f"{base}/api/show", json={"model": name},
                                 timeout=timeout).json()
        except (requests.RequestException, ValueError):
            continue
        caps = set(show.get("capabilities") or [])
        fams = set((show.get("details") or {}).get("families") or [])
        if "vision" in caps or fams & {"clip", "mllama"}:
            out.append(ModelEntry(id=f"ollama/{name}", provider="ollama",
                                  source="ollama", local=True,
                                  input_cost=0.0, output_cost=0.0))
    return sorted(out, key=lambda e: e.id)


def litellm_vision_models() -> list[ModelEntry]:
    try:
        import litellm
    except ImportError:
        return []
    out = []
    for mid, info in litellm.model_cost.items():
        if not info.get("supports_vision"):
            continue
        if info.get("mode") not in (None, "chat"):
            continue
        out.append(ModelEntry(id=mid, provider=info.get("litellm_provider", "unknown"),
                              source="litellm", local=False,
                              input_cost=info.get("input_cost_per_token"),
                              output_cost=info.get("output_cost_per_token")))
    return sorted(out, key=lambda e: e.id)


def openrouter_vision_models(timeout: float = 3.0) -> list[ModelEntry]:
    try:
        data = requests.get("https://openrouter.ai/api/v1/models",
                            timeout=timeout).json().get("data", [])
    except (requests.RequestException, ValueError):
        return []
    out = []
    for m in data:
        arch = m.get("architecture") or {}
        mods = arch.get("input_modalities") or str(arch.get("modality", "")).split("+")
        if "image" not in mods:
            continue
        pr = m.get("pricing") or {}
        def _f(x):
            try:
                return float(x) or None
            except (TypeError, ValueError):
                return None
        out.append(ModelEntry(id=f"openrouter/{m['id']}", provider="openrouter",
                              source="openrouter", local=False,
                              input_cost=_f(pr.get("prompt")),
                              output_cost=_f(pr.get("completion"))))
    return sorted(out, key=lambda e: e.id)


def all_vision_models(cfg: dict, include_openrouter: bool = True) -> list[ModelEntry]:
    entries = ollama_vision_models(cfg["ollama_url"]) + litellm_vision_models()
    if include_openrouter:
        entries += openrouter_vision_models()
    seen, out = set(), []
    for e in entries:
        if e.id not in seen:
            seen.add(e.id)
            out.append(e)
    return out
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_catalog.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add curator/providers/catalog.py tests/test_catalog.py
git commit -m "feat: mechanical vision-only model catalog (ollama/litellm/openrouter)"
```

---

### Task 5: Recommended registry + cost badges

**Files:**
- Create: `curator/providers/registry.yaml`, `curator/providers/registry.py`
- Modify: `pyproject.toml` (force-include the yaml)
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `ModelEntry` (Task 4).
- Produces: `load_registry(user_path: Path|None = None) -> list[dict]` (entries `{id, note, verified}`, user file overrides/prepends by id); `est_cost_per_1000(entry: ModelEntry) -> float|None` (USD, rounded 2dp); `tiered(catalog: list[ModelEntry], registry: list[dict]) -> tuple[list[ModelEntry], list[ModelEntry]]` — recommended tier keeps registry order, synthesizes `installed=False` entries for uninstalled ollama models; second element is the rest of the catalog. `AVG_TOKENS_PER_PHOTO = (900, 350)` module constant.

- [ ] **Step 1: Create the shipped registry**

```yaml
# curator/providers/registry.yaml
# Models verified against the 10-image qualification gate. Order = display order.
recommended:
  - id: ollama/qwen2.5vl:7b
    note: best local all-rounder (default)
    verified: 2026-07-05
  - id: ollama/gemma3:12b
    note: strong local, ~12 GB RAM
    verified: 2026-07-05
  - id: ollama/gemma3:4b
    note: low-RAM local option
    verified: 2026-07-05
  - id: ollama/llama3.2-vision:11b
    note: solid local alternative
    verified: 2026-07-05
  - id: ollama/minicpm-v:8b
    note: fast local option
    verified: 2026-07-05
  - id: gpt-4o-mini
    note: cheapest strong API pick
    verified: 2026-07-05
  - id: gpt-4o
    note: highest-quality API pick
    verified: 2026-07-05
  - id: gemini/gemini-2.0-flash
    note: cheapest strong API (Google)
    verified: 2026-07-05
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_registry.py
import yaml
from curator.providers.catalog import ModelEntry
from curator.providers.registry import (AVG_TOKENS_PER_PHOTO, est_cost_per_1000,
                                        load_registry, tiered)

def test_load_shipped_registry():
    reg = load_registry()
    assert reg[0]["id"] == "ollama/qwen2.5vl:7b"
    assert all("id" in e and "note" in e for e in reg)

def test_user_override_prepends(tmp_path):
    f = tmp_path / "registry.yaml"
    f.write_text(yaml.safe_dump({"recommended": [
        {"id": "ollama/my-model:1b", "note": "mine", "verified": "2026-07-06"}]}))
    reg = load_registry(user_path=f)
    assert reg[0]["id"] == "ollama/my-model:1b"
    assert any(e["id"] == "gpt-4o-mini" for e in reg)

def test_cost_estimate():
    e = ModelEntry("gpt-4o-mini", "openai", "litellm", False,
                   input_cost=1.5e-07, output_cost=6e-07)
    i, o = AVG_TOKENS_PER_PHOTO
    assert est_cost_per_1000(e) == round((1.5e-07 * i + 6e-07 * o) * 1000, 2)
    assert est_cost_per_1000(ModelEntry("x", "p", "litellm", False)) is None

def test_tiered_synthesizes_uninstalled_ollama():
    catalog = [ModelEntry("ollama/qwen2.5vl:7b", "ollama", "ollama", True, 0.0, 0.0),
               ModelEntry("gpt-4o-mini", "openai", "litellm", False, 1.5e-07, 6e-07),
               ModelEntry("openrouter/x/y", "openrouter", "openrouter", False)]
    rec, rest = tiered(catalog, load_registry())
    ids = [e.id for e in rec]
    assert ids[0] == "ollama/qwen2.5vl:7b" and rec[0].installed
    gemma = next(e for e in rec if e.id == "ollama/gemma3:12b")
    assert gemma.installed is False and gemma.local
    assert [e.id for e in rest] == ["openrouter/x/y"]
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_registry.py -q`
Expected: FAIL — no module `curator.providers.registry`

- [ ] **Step 4: Implement**

```python
# curator/providers/registry.py
from __future__ import annotations
from importlib.resources import files
from pathlib import Path
import yaml
from .catalog import ModelEntry

AVG_TOKENS_PER_PHOTO = (900, 350)   # measured input/output average per analyze call


def load_registry(user_path: Path | None = None) -> list[dict]:
    shipped = yaml.safe_load(
        files("curator").joinpath("providers/registry.yaml").read_text())["recommended"]
    if user_path is None:
        user_path = Path.home() / ".photo-curator" / "registry.yaml"
    if Path(user_path).exists():
        user = (yaml.safe_load(Path(user_path).read_text()) or {}).get("recommended", [])
        user_ids = {e["id"] for e in user}
        return user + [e for e in shipped if e["id"] not in user_ids]
    return shipped


def est_cost_per_1000(entry: ModelEntry) -> float | None:
    if entry.input_cost is None or entry.output_cost is None:
        return None
    i, o = AVG_TOKENS_PER_PHOTO
    return round((entry.input_cost * i + entry.output_cost * o) * 1000, 2)


def tiered(catalog: list[ModelEntry], registry: list[dict]
           ) -> tuple[list[ModelEntry], list[ModelEntry]]:
    by_id = {e.id: e for e in catalog}
    rec: list[ModelEntry] = []
    for r in registry:
        if r["id"] in by_id:
            rec.append(by_id[r["id"]])
        elif r["id"].startswith("ollama/"):   # pullable but not installed
            rec.append(ModelEntry(id=r["id"], provider="ollama", source="ollama",
                                  local=True, input_cost=0.0, output_cost=0.0,
                                  installed=False))
        # cloud registry entries missing from the catalog are dropped (stale id)
    rec_ids = {e.id for e in rec}
    rest = [e for e in catalog if e.id not in rec_ids]
    return rec, rest
```

`pyproject.toml` — in `[tool.hatch.build.targets.wheel.force-include]` add:

```toml
"curator/providers/registry.yaml" = "curator/providers/registry.yaml"
```

- [ ] **Step 5: Run tests, commit**

Run: `python -m pytest tests/test_registry.py -q` — Expected: 4 passed

```bash
git add curator/providers/registry.yaml curator/providers/registry.py pyproject.toml tests/test_registry.py
git commit -m "feat: recommended model registry with cost-per-1000-photos badges"
```

---

### Task 6: LiteLLMModel adapter

**Files:**
- Create: `curator/providers/litellm_model.py`
- Test: `tests/test_litellm_model.py`

**Interfaces:**
- Consumes: `curator.model` internals `_encode`, `_validate`, `JSON_REPAIR_V1`, `ModelError`, `InvalidOutput`; `KeyStore.get` (Task 1).
- Produces: `LiteLLMModel(model: str, keystore, timeout_s=120, seed=42, edge_px=1024)` implementing `VisionModel` (`analyze`, `name`), plus `cost_usd: float` (accumulated) and `provider() -> str`. Text-only calls: `analyze([], prompt, schema)` sends a plain string content. Backoff on rate limits: 5 tries with `_sleep` (patchable), then `ModelError` (the CLI already treats ModelError as pause-and-resume). Providers without json_schema support: first such error flips to prompt-embedded schema mode for the rest of the run.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_litellm_model.py
import sys, types
import pytest
from curator.model import InvalidOutput, ModelError
from tests.conftest import make_image

SCHEMA = {"type": "object", "properties": {"ok": {"type": "string", "enum": ["yes", "no"]}},
          "required": ["ok"], "additionalProperties": False}

class FakeUsageResp:
    def __init__(self, content):
        msg = types.SimpleNamespace(content=content)
        self.choices = [types.SimpleNamespace(message=msg)]

def _install_fake_litellm(monkeypatch, completion):
    fake = types.ModuleType("litellm")
    fake.completion = completion
    fake.completion_cost = lambda resp: 0.001
    class RateLimitError(Exception): pass
    fake.RateLimitError = RateLimitError
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake

class FakeKeystore:
    def get(self, provider): return "sk-test"

def _model():
    from curator.providers.litellm_model import LiteLLMModel
    return LiteLLMModel("gpt-4o-mini", FakeKeystore())

def test_happy_path_vision_message(tmp_path, monkeypatch):
    img = make_image(tmp_path / "a.jpg", "scene")
    sent = {}
    def completion(**kw):
        sent.update(kw)
        return FakeUsageResp('{"ok": "yes"}')
    _install_fake_litellm(monkeypatch, completion)
    m = _model()
    assert m.analyze([img], "prompt", SCHEMA) == {"ok": "yes"}
    content = sent["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "prompt"}
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert sent["temperature"] == 0 and sent["api_key"] == "sk-test"
    assert sent["response_format"]["json_schema"]["schema"] == SCHEMA
    assert m.cost_usd == pytest.approx(0.001)

def test_text_only_call(monkeypatch):
    sent = {}
    def completion(**kw):
        sent.update(kw)
        return FakeUsageResp('{"ok": "no"}')
    _install_fake_litellm(monkeypatch, completion)
    assert _model().analyze([], "just text", SCHEMA) == {"ok": "no"}
    assert sent["messages"][0]["content"] == "just text"

def test_schema_fallback_on_unsupported(monkeypatch):
    calls = []
    def completion(**kw):
        calls.append(kw)
        if "response_format" in kw:
            raise ValueError("response_format is not supported for this model")
        return FakeUsageResp('{"ok": "yes"}')
    _install_fake_litellm(monkeypatch, completion)
    m = _model()
    assert m.analyze([], "p", SCHEMA) == {"ok": "yes"}
    assert "response_format" not in calls[-1]
    assert "ONLY a single valid JSON object" in calls[-1]["messages"][0]["content"]

def test_rate_limit_backoff_then_error(monkeypatch):
    def completion(**kw):
        raise sys.modules["litellm"].RateLimitError("429")
    _install_fake_litellm(monkeypatch, completion)
    from curator.providers import litellm_model
    monkeypatch.setattr(litellm_model, "_sleep", lambda s: None)
    with pytest.raises(ModelError):
        _model().analyze([], "p", SCHEMA)

def test_repair_then_invalid(monkeypatch):
    def completion(**kw):
        return FakeUsageResp('{"ok": "MAYBE"}')
    _install_fake_litellm(monkeypatch, completion)
    with pytest.raises(InvalidOutput):
        _model().analyze([], "p", SCHEMA)

def test_provider_detection():
    from curator.providers.litellm_model import LiteLLMModel
    ks = FakeKeystore()
    assert LiteLLMModel("gpt-4o-mini", ks).provider() == "openai"
    assert LiteLLMModel("gemini/gemini-2.0-flash", ks).provider() == "gemini"
    assert LiteLLMModel("openrouter/google/gemma-3-27b-it", ks).provider() == "openrouter"
    assert LiteLLMModel("anthropic/claude-sonnet", ks).provider() == "anthropic"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_litellm_model.py -q`
Expected: FAIL — no module `curator.providers.litellm_model`

- [ ] **Step 3: Implement**

```python
# curator/providers/litellm_model.py
from __future__ import annotations
import json, time
from pathlib import Path
from curator.model import JSON_REPAIR_V1, InvalidOutput, ModelError, _encode, _validate

_KNOWN_PREFIXES = ("openrouter", "gemini", "anthropic", "ollama", "deepseek",
                   "minimax", "openai", "azure", "groq", "together_ai")


def _sleep(s: float) -> None:      # patchable in tests
    time.sleep(s)


class LiteLLMModel:
    """VisionModel over LiteLLM: one adapter for every provider (spec §5.1).
    Keeps the OllamaModel reliability loop: transport retries + backoff,
    then schema-repair cycles, then InvalidOutput."""

    def __init__(self, model: str, keystore, timeout_s: int = 120,
                 seed: int = 42, edge_px: int = 1024):
        self.model, self.keystore = model, keystore
        self.timeout_s, self.seed, self.edge_px = timeout_s, seed, edge_px
        self.cost_usd = 0.0
        self._schema_native = True     # flips off if provider rejects response_format

    def name(self) -> str:
        return f"litellm/{self.model}"

    def provider(self) -> str:
        head = self.model.split("/", 1)[0]
        if head in _KNOWN_PREFIXES:
            return head
        if self.model.startswith(("gpt-", "o1", "o3", "o4")):
            return "openai"
        if "claude" in self.model:
            return "anthropic"
        return "openai"

    def _messages(self, prompt: str, images: list[str]) -> list[dict]:
        if not images:
            return [{"role": "user", "content": prompt}]
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in images]
        return [{"role": "user", "content": content}]

    def _call(self, prompt: str, images: list[str], schema: dict) -> str:
        import litellm
        api_key = None if self.provider() == "ollama" else self.keystore.get(self.provider())
        last = None
        for attempt in range(5):
            kwargs = dict(model=self.model,
                          messages=self._messages(self._maybe_embed(prompt, schema), images),
                          temperature=0, seed=self.seed,
                          timeout=self.timeout_s, api_key=api_key)
            if self._schema_native:
                kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "curator_output", "schema": schema, "strict": True}}
            try:
                resp = litellm.completion(**kwargs)
                try:
                    self.cost_usd += litellm.completion_cost(resp) or 0.0
                except Exception:
                    pass
                return resp.choices[0].message.content
            except Exception as exc:
                if self._schema_native and "response_format" in str(exc):
                    self._schema_native = False       # embed schema in prompt instead
                    continue
                last = exc
                _sleep(min(2 ** attempt, 30))
        raise ModelError(f"provider unreachable or rate-limited: {last!r}")

    def _maybe_embed(self, prompt: str, schema: dict) -> str:
        if self._schema_native:
            return prompt
        return (prompt + "\n\nReply with ONLY a single valid JSON object matching "
                "this JSON schema (no prose, no fences):\n" + json.dumps(schema))

    def analyze(self, image_paths: list[Path], prompt: str, json_schema: dict) -> dict:
        images = [_encode(p, self.edge_px) for p in image_paths]
        raw = self._call(prompt, images, json_schema)
        for _ in range(3):
            try:
                return _validate(raw, json_schema)
            except Exception:
                raw = self._call(prompt + JSON_REPAIR_V1 + (raw or ""), images, json_schema)
        raise InvalidOutput(f"model {self.name()} produced invalid output after repairs")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_litellm_model.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add curator/providers/litellm_model.py tests/test_litellm_model.py
git commit -m "feat: LiteLLMModel - every provider behind the VisionModel protocol"
```

---

### Task 7: Intent engine (free text -> deltas)

**Files:**
- Create: `curator/prompts/intent.md`, `curator/schemas/intent.schema.json`, `curator/chat/intent.py`
- Test: `tests/test_intent.py`

**Interfaces:**
- Consumes: `prompts.render/load_schema`, `validate_deltas`, `VisionModel.analyze([], ...)`.
- Produces: `parse_intent(model, cfg, text: str, run_state: dict|None = None) -> {"deltas": list[dict], "reply": str}`. Invalid deltas from the model → one corrective retry → conversational fallback with empty deltas (spec §11 last row).

- [ ] **Step 1: Prompt + schema**

```markdown
<!-- version: 1 -->
You translate a photo owner's request into configuration changes for a photo
curation pipeline. You may ONLY change these paths:

- triage.blur_sharp_min (number, default 60; higher = stricter about blur)
- triage.blur_extreme_max, triage.black_extreme, triage.white_extreme,
  triage.exposure_poor (numbers)
- top_picks.target (number or "auto"), top_picks.cap, top_picks.max_per_event
- rubric.emotional, rubric.people_engagement, rubric.event_significance,
  rubric.composition_light, rubric.uniqueness, rubric.scene_appeal
  (weights 0-1, keep the sum near 1)
- buckets.disable (append a bucket key to hide it)
- buckets.custom (append {"key","description"})
- prompt_suffix (append a plain-English preference the analyst must honor)
- skip_globs (append a relative-path glob to exclude files)

Rules:
- Requests about subjects, people, tastes, moods -> append ONE clear sentence
  to prompt_suffix. Do not invent thresholds for subjective wishes.
- "stricter/looser about blur" -> adjust triage.blur_sharp_min by 20 in the
  right direction from its current value.
- A request you cannot express with these paths (changing the model, the
  source folder, deleting photos) -> return an empty deltas list and explain
  in reply what you can and cannot do.
- A pure question (no change requested) -> empty deltas; answer it in reply
  using RUN STATE if present.
- reply is always 1-2 friendly sentences summarizing what you did or know.

RUN STATE (may be empty): <<RUN_STATE>>

USER REQUEST: <<USER_TEXT>>
```

Save as `curator/prompts/intent.md`.

```json
{
  "type": "object",
  "properties": {
    "deltas": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "op": {"type": "string", "enum": ["set", "append"]},
          "value": {},
          "why": {"type": "string"}
        },
        "required": ["path", "value", "why"],
        "additionalProperties": false
      }
    },
    "reply": {"type": "string"}
  },
  "required": ["deltas", "reply"],
  "additionalProperties": false
}
```

Save as `curator/schemas/intent.schema.json`.

- [ ] **Step 2: Write the failing test — 50-phrasing golden suite (spec §12.3)**

```python
# tests/test_intent.py
from curator.chat.intent import parse_intent
from curator.config import load_config
from curator.model import MockModel

PS = "prompt_suffix"
# (user text, canned model deltas). The MockModel returns them; the test proves
# the plumbing accepts every whitelisted shape and the whitelist blocks the rest.
GOLDEN = [
    ("be stricter about blur", [{"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"}]),
    ("be more forgiving about blurry shots", [{"path": "triage.blur_sharp_min", "value": 40, "why": "looser"}]),
    ("really crack down on soft photos", [{"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"}]),
    ("don't be so picky about focus", [{"path": "triage.blur_sharp_min", "value": 40, "why": "looser"}]),
    ("tighten up on dark photos", [{"path": "triage.black_extreme", "value": 70, "why": "stricter dark"}]),
    ("allow darker photos through", [{"path": "triage.black_extreme", "value": 95, "why": "looser dark"}]),
    ("be strict about overexposed shots", [{"path": "triage.white_extreme", "value": 70, "why": "stricter"}]),
    ("I hate blurry pictures", [{"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"}]),
    ("keep even slightly soft photos", [{"path": "triage.blur_sharp_min", "value": 40, "why": "looser"}]),
    ("quality bar should be high", [{"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"}]),
    ("I don't care about food photos", [{"path": "buckets.disable", "op": "append", "value": "food-drink", "why": "hide food"}]),
    ("skip food pictures", [{"path": "buckets.disable", "op": "append", "value": "food-drink", "why": "hide food"}]),
    ("no screenshots please", [{"path": "buckets.disable", "op": "append", "value": "screenshots", "why": "hide"}]),
    ("hide the vehicles category", [{"path": "buckets.disable", "op": "append", "value": "vehicles", "why": "hide"}]),
    ("I never want to see receipts", [{"path": "buckets.disable", "op": "append", "value": "documents-receipts", "why": "hide"}]),
    ("drop urban architecture", [{"path": "buckets.disable", "op": "append", "value": "urban-architecture", "why": "hide"}]),
    ("remove the pets bucket", [{"path": "buckets.disable", "op": "append", "value": "pets-animals", "why": "hide"}]),
    ("no whiteboard photos", [{"path": "buckets.disable", "op": "append", "value": "whiteboards-notes", "why": "hide"}]),
    ("hide products and shopping", [{"path": "buckets.disable", "op": "append", "value": "products-shopping", "why": "hide"}]),
    ("I don't need the hobbies bucket", [{"path": "buckets.disable", "op": "append", "value": "hobbies-activities", "why": "hide"}]),
    ("add a bucket for my paintings", [{"path": "buckets.custom", "op": "append", "value": {"key": "my-artwork", "description": "Paintings and drawings made by me"}, "why": "custom"}]),
    ("make a category for latte art", [{"path": "buckets.custom", "op": "append", "value": {"key": "latte-art", "description": "Latte art and coffee presentation shots"}, "why": "custom"}]),
    ("focus on my daughter", [{"path": PS, "op": "append", "value": "The owner especially treasures photos of their daughter; weight her photos highly.", "why": "focus"}]),
    ("my kids matter most", [{"path": PS, "op": "append", "value": "Photos of the owner's children matter most; weight them highly.", "why": "focus"}]),
    ("prioritize photos with grandparents", [{"path": PS, "op": "append", "value": "Weight photos including grandparents highly.", "why": "focus"}]),
    ("I love golden hour shots", [{"path": PS, "op": "append", "value": "The owner loves golden-hour light; score such photos generously.", "why": "taste"}]),
    ("candid moments over posed ones", [{"path": PS, "op": "append", "value": "Prefer candid moments over posed shots.", "why": "taste"}]),
    ("I prefer landscapes to portraits", [{"path": PS, "op": "append", "value": "The owner prefers landscapes over portraits.", "why": "taste"}]),
    ("weight emotional moments heavily", [{"path": "rubric.emotional", "value": 0.4, "why": "user emphasis"}]),
    ("composition matters more to me", [{"path": "rubric.composition_light", "value": 0.25, "why": "user emphasis"}]),
    ("surprise me - value unusual shots", [{"path": "rubric.uniqueness", "value": 0.2, "why": "user emphasis"}]),
    ("scenery is what I care about", [{"path": "rubric.scene_appeal", "value": 0.2, "why": "user emphasis"}]),
    ("skip the WhatsApp folder", [{"path": "skip_globs", "op": "append", "value": "WhatsApp/*", "why": "skip"}]),
    ("ignore anything under Downloads", [{"path": "skip_globs", "op": "append", "value": "Downloads/*", "why": "skip"}]),
    ("don't touch the 2019 subfolder", [{"path": "skip_globs", "op": "append", "value": "2019/*", "why": "skip"}]),
    ("exclude edited copies", [{"path": "skip_globs", "op": "append", "value": "*edited*", "why": "skip"}]),
    ("skip screenshots folder", [{"path": "skip_globs", "op": "append", "value": "Screenshots/*", "why": "skip"}]),
    ("only 50 top picks", [{"path": "top_picks.target", "value": 50, "why": "user cap"}]),
    ("give me a tight best-of, 20 photos", [{"path": "top_picks.target", "value": 20, "why": "user cap"}]),
    ("I want a big highlights set", [{"path": "top_picks.target", "value": 200, "why": "user size"}]),
    ("no more than 5 per event", [{"path": "top_picks.max_per_event", "value": 5, "why": "user cap"}]),
    ("cap highlights at 100", [{"path": "top_picks.cap", "value": 100, "why": "user cap"}]),
    ("more variety per trip", [{"path": "top_picks.max_per_event", "value": 25, "why": "variety"}]),
    ("both stricter blur and no food", [{"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"},
                                        {"path": "buckets.disable", "op": "append", "value": "food-drink", "why": "hide"}]),
    ("focus on family and skip receipts", [{"path": PS, "op": "append", "value": "Weight family photos highly.", "why": "focus"},
                                           {"path": "buckets.disable", "op": "append", "value": "documents-receipts", "why": "hide"}]),
    ("kids first, strict quality", [{"path": PS, "op": "append", "value": "Photos of children matter most.", "why": "focus"},
                                    {"path": "triage.blur_sharp_min", "value": 80, "why": "stricter"}]),
    ("hide food, hide pets", [{"path": "buckets.disable", "op": "append", "value": "food-drink", "why": "hide"},
                              {"path": "buckets.disable", "op": "append", "value": "pets-animals", "why": "hide"}]),
    ("value real laughter", [{"path": PS, "op": "append", "value": "Genuine laughter is the owner's favorite thing; weight it highly.", "why": "taste"}]),
    ("beach days are special to us", [{"path": PS, "op": "append", "value": "Beach outings are special to this family; weight them highly.", "why": "taste"}]),
    ("treat concerts as keepers even in low light", [{"path": PS, "op": "append", "value": "Concert photos in low light are keepers, not exposure rejects.", "why": "taste"}]),
]

def _mock_for(canned):
    return MockModel(lambda paths, prompt, schema: canned)

def test_golden_suite_all_50_accepted():
    cfg = load_config(None)
    assert len(GOLDEN) == 50
    for text, deltas in GOLDEN:
        out = parse_intent(_mock_for({"deltas": deltas, "reply": "done"}), cfg, text)
        assert out["deltas"] == deltas, text
        assert out["reply"] == "done"

def test_model_offers_bad_path_gets_retry_then_fallback():
    calls = {"n": 0}
    def handler(paths, prompt, schema):
        calls["n"] += 1
        return {"deltas": [{"path": "llm.seed", "value": 7, "why": "nope"}],
                "reply": "tried"}
    out = parse_intent(MockModel(handler), load_config(None), "change the seed")
    assert calls["n"] == 2                       # one corrective retry
    assert out["deltas"] == []
    assert "couldn't turn that into a safe change" in out["reply"]

def test_retry_recovers():
    replies = iter([
        {"deltas": [{"path": "model", "value": "x", "why": ""}], "reply": "bad"},
        {"deltas": [{"path": "triage.blur_sharp_min", "value": 80, "why": "ok"}], "reply": "fixed"},
    ])
    out = parse_intent(MockModel(lambda *a: next(replies)),
                       load_config(None), "stricter blur")
    assert out["deltas"][0]["path"] == "triage.blur_sharp_min"

def test_question_passes_run_state():
    seen = {}
    def handler(paths, prompt, schema):
        seen["prompt"] = prompt
        return {"deltas": [], "reply": "3 rejected so far"}
    out = parse_intent(MockModel(handler), load_config(None),
                       "how is it going?", run_state={"rejected": 3})
    assert out["deltas"] == [] and "rejected" in out["reply"]
    assert '"rejected": 3' in seen["prompt"]
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_intent.py -q`
Expected: FAIL — no module `curator.chat.intent`

- [ ] **Step 4: Implement**

```python
# curator/chat/intent.py
from __future__ import annotations
import json
from .. import prompts
from .deltas import DeltaError, validate_deltas


def parse_intent(model, cfg: dict, text: str, run_state: dict | None = None) -> dict:
    """Free text -> {"deltas": [...], "reply": str}. Deltas are whitelist-
    validated; a model that proposes an out-of-bounds path gets ONE corrective
    retry, then we answer conversationally with no changes (R4: nothing
    unvetted ever reaches the config)."""
    prompt = prompts.render("intent", cfg, USER_TEXT=text,
                            RUN_STATE=json.dumps(run_state or {}, sort_keys=True))
    schema = prompts.load_schema("intent")
    out = model.analyze([], prompt, schema)
    try:
        deltas = validate_deltas(out)
    except DeltaError as exc:
        retry = model.analyze(
            [], prompt + f"\n\nYour previous deltas were rejected ({exc}). "
            "Use only the allowed paths, or return an empty deltas list.", schema)
        try:
            deltas = validate_deltas(retry)
            out = retry
        except DeltaError:
            return {"deltas": [],
                    "reply": "I couldn't turn that into a safe change - "
                             + str(out.get("reply", ""))}
    return {"deltas": deltas, "reply": out["reply"]}
```

- [ ] **Step 5: Run tests, commit**

Run: `python -m pytest tests/test_intent.py tests/test_prompts.py -q`
Expected: all pass (test_prompts's `versions()` test still passes — it asserts specific keys, new files don't break it)

```bash
git add curator/prompts/intent.md curator/schemas/intent.schema.json curator/chat/intent.py tests/test_intent.py
git commit -m "feat: intent engine - plain English to whitelisted config deltas"
```

---

### Task 8: Post-run Q&A

**Files:**
- Create: `curator/prompts/qa.md`, `curator/schemas/qa.schema.json`, `curator/chat/qa.py`
- Test: `tests/test_qa.py`

**Interfaces:**
- Consumes: `Store.photos()` rows (`rel_path`, `verdict`, `verdict_info`, `stage3`, `stage2`), `prompts.render/load_schema`.
- Produces: `build_context(store, question: str, limit=8) -> dict` (summary + photos matched by filename mention); `answer(model, store, cfg, question: str) -> str`.

- [ ] **Step 1: Prompt + schema**

```markdown
<!-- version: 1 -->
You are the curator explaining a finished photo-curation run to its owner.
Answer from the CONTEXT only - it contains the run summary and the full
decision evidence for any photos the owner mentioned. Quote the recorded
evidence (blur scores, what both analysis passes said, the verdict tier).
If the context does not contain the answer, say so honestly. Warm, 1-4
sentences.

CONTEXT: <<CONTEXT>>

QUESTION: <<QUESTION>>
```

Save as `curator/prompts/qa.md`. Schema `curator/schemas/qa.schema.json`:

```json
{"type": "object", "properties": {"reply": {"type": "string"}},
 "required": ["reply"], "additionalProperties": false}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_qa.py
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
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_qa.py -q`
Expected: FAIL — no module `curator.chat.qa`

- [ ] **Step 4: Implement**

```python
# curator/chat/qa.py
from __future__ import annotations
import json, re
from collections import Counter
from pathlib import Path
from .. import prompts

_FILENAME_RE = re.compile(
    r"[\w\-()]+\.(?:jpe?g|png|heic|heif|webp|tiff?|bmp|gif)", re.IGNORECASE)


def build_context(store, question: str, limit: int = 8) -> dict:
    names = {m.group(0).lower() for m in _FILENAME_RE.finditer(question)}
    all_photos = store.photos()
    verdicts = Counter(p["verdict"] for p in all_photos if p.get("verdict"))
    matched = []
    for p in all_photos:
        if Path(p["rel_path"]).name.lower() in names:
            matched.append({k: p.get(k) for k in
                            ("rel_path", "verdict", "verdict_info", "stage3", "stage2")
                            if p.get(k) is not None})
    return {"summary": {"total": len(all_photos), "verdicts": dict(verdicts)},
            "photos": matched[:limit]}


def answer(model, store, cfg: dict, question: str) -> str:
    ctx = build_context(store, question)
    prompt = prompts.render("qa", cfg, QUESTION=question,
                            CONTEXT=json.dumps(ctx, default=str, sort_keys=True))
    return model.analyze([], prompt, prompts.load_schema("qa"))["reply"]
```

- [ ] **Step 5: Run tests, commit**

Run: `python -m pytest tests/test_qa.py -q` — Expected: 3 passed

```bash
git add curator/prompts/qa.md curator/schemas/qa.schema.json curator/chat/qa.py tests/test_qa.py
git commit -m "feat: post-run Q&A - answers grounded in the decision log"
```

---

### Task 9: TUI skeleton — detect, state, app, Welcome screen

**Files:**
- Create: `curator/tui/__init__.py` (empty), `curator/tui/detect.py`, `curator/tui/state.py`, `curator/tui/app.py`, `curator/tui/screens.py` (Welcome only; later tasks extend this file)
- Test: `tests/test_tui_welcome.py`

**Interfaces:**
- Consumes: `ollama_vision_models`, `ENV_MAP`, `KeyStore`, `load_config`.
- Produces: `Detection(ollama_up, local_models, env_keys, prior)`; `detect(cfg, home, timeout=2.0) -> Detection`; `AppState(cfg, keystore, home, detection=None, model_entry=None, folder=None, deltas=[], cost_cap=None)` with `consented(provider) -> bool` / `record_consent(provider)`; `CuratorApp(cfg=None, home=None, keystore=None, detection=None, model_factory=None, catalog_fn=None)` — every dependency injectable for headless tests. `model_factory(cfg) -> VisionModel` overrides model construction everywhere in the TUI (tests pass MockModel factories).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tui_welcome.py
from pathlib import Path
from curator.config import load_config
from curator.providers.catalog import ModelEntry
from curator.providers.keystore import KeyStore
from curator.tui.app import CuratorApp
from curator.tui.detect import Detection

def _detection():
    return Detection(ollama_up=True,
                     local_models=[ModelEntry("ollama/qwen2.5vl:7b", "ollama",
                                              "ollama", True, 0.0, 0.0)],
                     env_keys=["openai"], prior=None)

def _app(tmp_path):
    return CuratorApp(cfg=load_config(None), home=tmp_path,
                      keystore=KeyStore(home=tmp_path, backend="file"),
                      detection=_detection(),
                      catalog_fn=lambda cfg: _detection().local_models)

async def test_welcome_shows_detection(tmp_path):
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        text = str(app.screen.query_one("#status").render())
        assert "Ollama: running" in text
        assert "qwen2.5vl:7b" in text
        assert "openai" in text                       # env key found

async def test_enter_advances_to_model_picker(tmp_path):
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert app.screen.__class__.__name__ == "ModelPickerScreen"

def test_detect_offline(tmp_path, monkeypatch):
    import requests
    from curator.tui import detect as d
    monkeypatch.setattr(d, "ollama_vision_models", lambda url, timeout=2.0: [])
    def boom(*a, **k): raise requests.ConnectionError()
    monkeypatch.setattr(d.requests, "get", boom)
    det = d.detect(load_config(None), home=tmp_path)
    assert det.ollama_up is False and det.local_models == []

def test_consent_persists(tmp_path):
    from curator.tui.state import AppState
    st = AppState(cfg=load_config(None),
                  keystore=KeyStore(home=tmp_path, backend="file"), home=tmp_path)
    assert not st.consented("openai")
    st.record_consent("openai")
    st2 = AppState(cfg=load_config(None),
                   keystore=KeyStore(home=tmp_path, backend="file"), home=tmp_path)
    assert st2.consented("openai")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_tui_welcome.py -q`
Expected: FAIL — no module `curator.tui`

- [ ] **Step 3: Implement**

```python
# curator/tui/detect.py
from __future__ import annotations
import json, os
from dataclasses import dataclass, field
from pathlib import Path
import requests
from ..providers.catalog import ModelEntry, ollama_vision_models
from ..providers.keystore import ENV_MAP


@dataclass
class Detection:
    ollama_up: bool
    local_models: list[ModelEntry]
    env_keys: list[str]
    prior: dict | None


def detect(cfg: dict, home: Path | None = None, timeout: float = 2.0) -> Detection:
    local = ollama_vision_models(cfg["ollama_url"], timeout)
    up = bool(local)
    if not up:
        try:
            requests.get(cfg["ollama_url"].rstrip("/") + "/api/version", timeout=timeout)
            up = True
        except requests.RequestException:
            up = False
    env_keys = [p for p, var in ENV_MAP.items() if os.environ.get(var)]
    home = Path(home) if home else Path.home() / ".photo-curator"
    prior_f = home / "last_run.json"
    prior = json.loads(prior_f.read_text()) if prior_f.exists() else None
    return Detection(up, local, env_keys, prior)
```

```python
# curator/tui/state.py
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from ..providers.catalog import ModelEntry
from .detect import Detection


@dataclass
class AppState:
    cfg: dict
    keystore: object
    home: Path
    detection: Detection | None = None
    model_entry: ModelEntry | None = None
    folder: Path | None = None
    deltas: list = field(default_factory=list)
    cost_cap: float | None = None

    def _consent_file(self) -> Path:
        return Path(self.home) / "consent.json"

    def consented(self, provider: str) -> bool:
        f = self._consent_file()
        return f.exists() and provider in json.loads(f.read_text())

    def record_consent(self, provider: str) -> None:
        f = self._consent_file()
        data = json.loads(f.read_text()) if f.exists() else []
        if provider not in data:
            data.append(provider)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data))
```

```python
# curator/tui/app.py
from __future__ import annotations
from pathlib import Path
from textual.app import App
from ..config import load_config
from ..providers.catalog import all_vision_models
from ..providers.keystore import KeyStore
from .state import AppState


class CuratorApp(App):
    TITLE = "Photo Curator"

    def __init__(self, cfg=None, home=None, keystore=None, detection=None,
                 model_factory=None, catalog_fn=None):
        super().__init__()
        home = Path(home) if home else Path.home() / ".photo-curator"
        self.state = AppState(cfg=cfg or load_config(None),
                              keystore=keystore or KeyStore(home=home),
                              home=home, detection=detection)
        self.model_factory = model_factory       # None -> real factories (runner)
        self.catalog_fn = catalog_fn or all_vision_models

    def on_mount(self) -> None:
        from .screens import WelcomeScreen
        self.push_screen(WelcomeScreen())
```

```python
# curator/tui/screens.py
from __future__ import annotations
from textual.screen import Screen
from textual.widgets import Footer, Header, Static
from .detect import detect


class WelcomeScreen(Screen):
    BINDINGS = [("enter", "continue", "Continue")]

    def compose(self):
        yield Header()
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        st = self.app.state
        if st.detection is None:
            st.detection = detect(st.cfg, st.home)
        d = st.detection
        lines = ["Welcome to Photo Curator.", "",
                 f"Ollama: {'running' if d.ollama_up else 'not running'}",
                 "Local vision models: "
                 + (", ".join(e.id.removeprefix("ollama/") for e in d.local_models)
                    or "none"),
                 "API keys found: " + (", ".join(d.env_keys) or "none"), "",
                 "Press Enter to choose a model."]
        if d.prior:
            lines.insert(-1, f"Last run: {d.prior.get('model_id')} on {d.prior.get('folder')}")
        self.query_one("#status", Static).update("\n".join(lines))

    def action_continue(self) -> None:
        from .screens_model import ModelPickerScreen
        self.app.push_screen(ModelPickerScreen())
```

Create `ModelPickerScreen` as a stub in a NEW file `curator/tui/screens_model.py` so this task's test passes (Task 10 fills it in):

```python
# curator/tui/screens_model.py
from __future__ import annotations
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList


class ModelPickerScreen(Screen):
    def compose(self):
        yield Header()
        yield OptionList(id="models")
        yield Footer()
```

Also create empty `curator/tui/__init__.py`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_tui_welcome.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add curator/tui tests/test_tui_welcome.py
git commit -m "feat: TUI skeleton - detection, app state, welcome screen"
```

---

### Task 10: Model picker screen (tiers, key entry, consent, pull)

**Files:**
- Modify: `curator/tui/screens_model.py`, `curator/providers/litellm_model.py` (extract `provider_of`)
- Test: `tests/test_tui_model_picker.py`

**Interfaces:**
- Consumes: `tiered`, `load_registry`, `est_cost_per_1000`, `KeyStore`, `AppState.consented/record_consent`.
- Produces: `provider_of(model_id: str) -> str` module function in `litellm_model.py` (the class method delegates to it); `ModelPickerScreen` that sets `app.state.model_entry` and pushes `FolderScreen`; `KeyModal(provider) -> str|None`; `ConsentModal(provider) -> bool`; `PullModal(entry)` streams `POST /api/pull`.

- [ ] **Step 1: Refactor `provider_of` out of the class**

In `curator/providers/litellm_model.py`, move the body of `LiteLLMModel.provider` into a module function and delegate:

```python
def provider_of(model: str) -> str:
    head = model.split("/", 1)[0]
    if head in _KNOWN_PREFIXES:
        return head
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if "claude" in model:
        return "anthropic"
    return "openai"
```

and inside the class: `def provider(self) -> str: return provider_of(self.model)`.

Run: `python -m pytest tests/test_litellm_model.py -q` — Expected: still 7 passed.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_tui_model_picker.py
from curator.config import load_config
from curator.providers.catalog import ModelEntry
from curator.providers.keystore import KeyStore
from curator.tui.app import CuratorApp
from curator.tui.detect import Detection

LOCAL = ModelEntry("ollama/qwen2.5vl:7b", "ollama", "ollama", True, 0.0, 0.0)
CLOUD = ModelEntry("gpt-4o-mini", "openai", "litellm", False, 1.5e-07, 6e-07)

def _app(tmp_path, catalog):
    det = Detection(True, [e for e in catalog if e.local], [], None)
    return CuratorApp(cfg=load_config(None), home=tmp_path,
                      keystore=KeyStore(home=tmp_path, backend="file"),
                      detection=det, catalog_fn=lambda cfg: catalog)

async def test_tiers_and_badges(tmp_path):
    app = _app(tmp_path, [LOCAL, CLOUD])
    async with app.run_test() as pilot:
        await pilot.press("enter")                       # welcome -> picker
        screen = app.screen
        labels = [str(o.prompt) for o in screen.query_one("#models")._options]
        joined = "\n".join(labels)
        assert "RECOMMENDED" in joined and "ALL VISION MODELS" in joined
        assert "local · free" in joined and "api · ~$" in joined
        assert "not pulled" in joined                    # registry gemma not installed

async def test_local_select_advances(tmp_path):
    app = _app(tmp_path, [LOCAL, CLOUD])
    async with app.run_test() as pilot:
        await pilot.press("enter")
        app.screen.select_model(LOCAL)                   # direct call = the handler body
        await pilot.pause()
        assert app.state.model_entry.id == LOCAL.id
        assert app.screen.__class__.__name__ == "FolderScreen"

async def test_cloud_needs_consent_then_key(tmp_path):
    app = _app(tmp_path, [LOCAL, CLOUD])
    async with app.run_test() as pilot:
        await pilot.press("enter")
        app.screen.select_model(CLOUD)
        await pilot.pause()
        assert app.screen.__class__.__name__ == "ConsentModal"
        await pilot.press("y")                           # consent
        await pilot.pause()
        assert app.screen.__class__.__name__ == "KeyModal"
        for ch in "sk-test-1":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.keystore.get("openai") == "sk-test-1"
        assert app.state.consented("openai")
        assert app.screen.__class__.__name__ == "FolderScreen"

async def test_cloud_with_existing_key_skips_modal(tmp_path):
    app = _app(tmp_path, [LOCAL, CLOUD])
    app.state.keystore.set("openai", "sk-already")
    app.state.record_consent("openai")
    async with app.run_test() as pilot:
        await pilot.press("enter")
        app.screen.select_model(CLOUD)
        await pilot.pause()
        assert app.screen.__class__.__name__ == "FolderScreen"
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_tui_model_picker.py -q`
Expected: FAIL — picker has no options / no `select_model`

- [ ] **Step 4: Implement**

Replace `curator/tui/screens_model.py` with:

```python
# curator/tui/screens_model.py
from __future__ import annotations
import json
import requests
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, Input, OptionList, ProgressBar, Static
from textual.widgets.option_list import Option
from ..providers.catalog import ModelEntry
from ..providers.litellm_model import provider_of
from ..providers.registry import est_cost_per_1000, load_registry, tiered


class ModelPickerScreen(Screen):
    def compose(self):
        yield Header()
        yield Static("Choose your vision model (Enter to select)")
        yield OptionList(id="models")
        yield Footer()

    def on_mount(self) -> None:
        catalog = self.app.catalog_fn(self.app.state.cfg)
        rec, rest = tiered(catalog, load_registry())
        ol = self.query_one("#models", OptionList)
        self._entries: dict[str, ModelEntry] = {}
        ol.add_option(Option("── RECOMMENDED ──", disabled=True))
        for e in rec:
            self._entries[e.id] = e
            ol.add_option(Option(self._label(e), id=e.id))
        ol.add_option(Option("── ALL VISION MODELS ──", disabled=True))
        for e in rest:
            if e.id not in self._entries:
                self._entries[e.id] = e
                ol.add_option(Option(self._label(e), id=e.id))

    @staticmethod
    def _label(e: ModelEntry) -> str:
        if e.local:
            badge = "local · free"
        else:
            cost = est_cost_per_1000(e)
            badge = f"api · ~${cost} per 1,000 photos" if cost else "api"
        pull = "" if e.installed else "  [not pulled — Enter to pull]"
        return f"{e.id}  ({badge}){pull}"

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected) -> None:
        self.select_model(self._entries[ev.option.id])

    def select_model(self, entry: ModelEntry) -> None:
        self.app.state.model_entry = entry
        if entry.local:
            if not entry.installed:
                self.app.push_screen(PullModal(entry), self._after_pull)
                return
            self._advance()
            return
        provider = provider_of(entry.id)
        if not self.app.state.consented(provider):
            self.app.push_screen(ConsentModal(provider), self._after_consent)
        else:
            self._maybe_key(provider)

    def _after_consent(self, agreed: bool | None) -> None:
        provider = provider_of(self.app.state.model_entry.id)
        if not agreed:
            self.app.state.model_entry = None
            return
        self.app.state.record_consent(provider)
        self._maybe_key(provider)

    def _maybe_key(self, provider: str) -> None:
        if self.app.state.keystore.get(provider) is None:
            self.app.push_screen(KeyModal(provider), self._after_key)
        else:
            self._advance()

    def _after_key(self, key: str | None) -> None:
        if not key:
            self.app.state.model_entry = None
            return
        provider = provider_of(self.app.state.model_entry.id)
        self.app.state.keystore.set(provider, key)
        self._advance()

    def _after_pull(self, ok: bool | None) -> None:
        if ok:
            self.app.state.model_entry.installed = True
            self._advance()

    def _advance(self) -> None:
        from .screens_folder import FolderScreen
        self.app.push_screen(FolderScreen())


class ConsentModal(ModalScreen[bool]):
    """R7: one-time per-provider cloud consent."""
    BINDINGS = [("y", "yes", "Yes"), ("n", "no", "No"), ("escape", "no", "No")]

    def __init__(self, provider: str):
        super().__init__()
        self.provider = provider

    def compose(self):
        yield Vertical(
            Static(f"Using this model sends your photos to {self.provider} "
                   "for analysis.\nLocal models keep photos on this machine.\n\n"
                   "Continue?  [y]es / [n]o", id="consent-text"))

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class KeyModal(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, provider: str):
        super().__init__()
        self.provider = provider

    def compose(self):
        yield Vertical(
            Static(f"Paste your {self.provider} API key "
                   "(stored in your OS keychain, never in files):"),
            Input(password=True, id="key"))

    def on_mount(self) -> None:
        self.query_one("#key", Input).focus()

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        self.dismiss(ev.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PullModal(ModalScreen[bool]):
    def __init__(self, entry: ModelEntry):
        super().__init__()
        self.entry = entry

    def compose(self):
        name = self.entry.id.removeprefix("ollama/")
        yield Vertical(Static(f"Pulling {name}…"), ProgressBar(id="pull"))

    def on_mount(self) -> None:
        self.run_worker(self._pull, thread=True)

    def _pull(self) -> None:
        name = self.entry.id.removeprefix("ollama/")
        url = self.app.state.cfg["ollama_url"].rstrip("/") + "/api/pull"
        bar = self.query_one("#pull", ProgressBar)
        try:
            with requests.post(url, json={"model": name}, stream=True,
                               timeout=3600) as resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("total") and d.get("completed"):
                        self.app.call_from_thread(
                            bar.update, total=d["total"], progress=d["completed"])
            self.app.call_from_thread(self.dismiss, True)
        except requests.RequestException:
            self.app.call_from_thread(self.dismiss, False)
```

Also create a stub `curator/tui/screens_folder.py` (Task 11 fills it in):

```python
# curator/tui/screens_folder.py
from __future__ import annotations
from textual.screen import Screen
from textual.widgets import Footer, Header


class FolderScreen(Screen):
    def compose(self):
        yield Header()
        yield Footer()
```

- [ ] **Step 5: Run tests, commit**

Run: `python -m pytest tests/test_tui_model_picker.py tests/test_litellm_model.py -q`
Expected: all pass

```bash
git add curator/tui/screens_model.py curator/tui/screens_folder.py curator/providers/litellm_model.py tests/test_tui_model_picker.py
git commit -m "feat: model picker - tiers, consent, keychain entry, ollama pull"
```

---

### Task 11: Folder, Intent, and Confirm screens

**Files:**
- Modify: `curator/tui/screens_folder.py`
- Create: `curator/tui/screens_setup.py` (IntentScreen, ConfirmScreen)
- Test: `tests/test_tui_setup_flow.py`

**Interfaces:**
- Consumes: `PHOTO_EXTS` (inventory), `parse_intent`, `describe`, `AVG cost helpers`, `AppState`.
- Produces: `FolderScreen` (DirectoryTree + path Input; sets `state.folder`, pushes IntentScreen); `IntentScreen` (empty submit skips; otherwise parse → show `describe()` lines → `a` accepts into `state.deltas`); `ConfirmScreen` (summary; for cloud models an optional cost-cap Input → `state.cost_cap`; writes `home/last_run.json`; Enter pushes RunScreen). `count_photos(folder) -> int` helper in `screens_folder.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tui_setup_flow.py
from curator.config import load_config
from curator.model import MockModel
from curator.providers.catalog import ModelEntry
from curator.providers.keystore import KeyStore
from curator.tui.app import CuratorApp
from curator.tui.detect import Detection
from curator.tui.screens_folder import count_photos

LOCAL = ModelEntry("ollama/qwen2.5vl:7b", "ollama", "ollama", True, 0.0, 0.0)

def _app(tmp_path, model_factory=None):
    det = Detection(True, [LOCAL], [], None)
    return CuratorApp(cfg=load_config(None), home=tmp_path / "home",
                      keystore=KeyStore(home=tmp_path / "home", backend="file"),
                      detection=det, catalog_fn=lambda cfg: [LOCAL],
                      model_factory=model_factory)

def _photos(tmp_path, img_factory, n=2):
    src = tmp_path / "src"
    for i in range(n):
        img_factory(src / f"p{i}.jpg", "scene", seed=i,
                    exif_dt=f"2026:05:12 10:0{i}:00")
    return src

def test_count_photos(tmp_path, img_factory):
    src = _photos(tmp_path, img_factory, 3)
    (src / "note.txt").write_text("x")
    assert count_photos(src) == 3

async def test_folder_to_intent_skip_to_confirm(tmp_path, img_factory):
    src = _photos(tmp_path, img_factory)
    app = _app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.press("enter")                      # welcome -> picker
        app.screen.select_model(LOCAL)                  # picker -> folder
        await pilot.pause()
        folder_screen = app.screen
        folder_screen.set_folder(src)                   # same as tree/path selection
        await pilot.pause()
        assert app.state.folder == src
        assert app.screen.__class__.__name__ == "IntentScreen"
        await pilot.press("enter")                      # empty input = skip
        await pilot.pause()
        assert app.screen.__class__.__name__ == "ConfirmScreen"
        text = str(app.screen.query_one("#summary").render())
        assert "2 photos" in text and "qwen2.5vl:7b" in text
        assert (tmp_path / "home" / "last_run.json").exists()

async def test_intent_parses_and_accept(tmp_path, img_factory):
    src = _photos(tmp_path, img_factory)
    canned = {"deltas": [{"path": "triage.blur_sharp_min", "op": "set",
                          "value": 80, "why": "stricter"}], "reply": "Done."}
    app = _app(tmp_path, model_factory=lambda cfg: MockModel(lambda *a: canned))
    async with app.run_test() as pilot:
        await pilot.press("enter")
        app.screen.select_model(LOCAL)
        await pilot.pause()
        app.screen.set_folder(src)
        await pilot.pause()
        intent = app.screen
        intent.query_one("#wish").value = "be stricter about blur"
        await pilot.press("enter")
        await pilot.pause(delay=0.5)                    # worker parses
        assert "blur_sharp_min" in str(intent.query_one("#parsed").render())
        await pilot.press("a")                          # accept
        await pilot.pause()
        assert app.state.deltas == canned["deltas"]
        assert app.screen.__class__.__name__ == "ConfirmScreen"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_tui_setup_flow.py -q`
Expected: FAIL — `count_photos` missing / stub screens

- [ ] **Step 3: Implement**

Replace `curator/tui/screens_folder.py`:

```python
# curator/tui/screens_folder.py
from __future__ import annotations
from pathlib import Path
from textual.screen import Screen
from textual.widgets import DirectoryTree, Footer, Header, Input, Static
from ..inventory import PHOTO_EXTS


def count_photos(folder: Path) -> int:
    return sum(1 for p in Path(folder).rglob("*")
               if p.is_file() and p.suffix.lower() in PHOTO_EXTS)


class FolderScreen(Screen):
    def compose(self):
        yield Header()
        yield Static("Pick your photo folder (browse, or paste a path and press Enter)")
        yield Input(placeholder="/path/to/photos", id="path")
        yield DirectoryTree(str(Path.home()), id="tree")
        yield Static("", id="count")
        yield Footer()

    def on_directory_tree_directory_selected(
            self, ev: DirectoryTree.DirectorySelected) -> None:
        self.set_folder(Path(ev.path))

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        p = Path(ev.value).expanduser()
        if p.is_dir():
            self.set_folder(p)
        else:
            self.query_one("#count", Static).update(f"not a folder: {p}")

    def set_folder(self, folder: Path) -> None:
        n = count_photos(folder)
        self.query_one("#count", Static).update(f"{n} photos found")
        if n == 0:
            return
        self.app.state.folder = Path(folder)
        from .screens_setup import IntentScreen
        self.app.push_screen(IntentScreen())
```

Create `curator/tui/screens_setup.py`:

```python
# curator/tui/screens_setup.py
from __future__ import annotations
import json
from datetime import date
from pathlib import Path
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static
from ..chat.deltas import describe
from ..chat.intent import parse_intent
from ..providers.registry import est_cost_per_1000
from .screens_folder import count_photos


class IntentScreen(Screen):
    BINDINGS = [("a", "accept", "Accept changes")]

    def compose(self):
        yield Header()
        yield Static("Anything special you want? (Enter to just curate)")
        yield Input(placeholder="e.g. focus on my kids, skip food photos", id="wish")
        yield Static("", id="parsed")
        yield Footer()

    def on_mount(self) -> None:
        self._pending = None
        self.query_one("#wish", Input).focus()

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        text = ev.value.strip()
        if not text:
            self._advance()
            return
        self.run_worker(lambda: self._parse(text), thread=True)

    def _parse(self, text: str) -> None:
        factory = self.app.model_factory
        if factory is None:
            from .runner import factory_for
            factory = factory_for(self.app.state.model_entry, self.app.state.keystore)
        model = factory(self.app.state.cfg)
        out = parse_intent(model, self.app.state.cfg, text)
        self._pending = out["deltas"]
        lines = describe(out["deltas"]) or ["(no changes)"]
        self.app.call_from_thread(
            self.query_one("#parsed", Static).update,
            out["reply"] + "\n" + "\n".join(f"  {ln}" for ln in lines)
            + "\n\nPress [a] to accept, or type again.")

    def action_accept(self) -> None:
        if self._pending:
            self.app.state.deltas = self._pending
        self._advance()

    def _advance(self) -> None:
        self.app.push_screen(ConfirmScreen())


class ConfirmScreen(Screen):
    BINDINGS = [("enter", "start", "Start curating")]

    def compose(self):
        yield Header()
        yield Static(id="summary")
        yield Input(placeholder="optional $ cost cap (cloud only) - Enter to start",
                    id="cap")
        yield Footer()

    def on_mount(self) -> None:
        st = self.app.state
        n = count_photos(st.folder)
        self._n = n
        lines = [f"Model:   {st.model_entry.id}",
                 f"Folder:  {st.folder}  ({n} photos)",
                 f"Est. time: ~{n * 8 / 60:.0f} min at 8 s/photo"]
        if not st.model_entry.local:
            cost = est_cost_per_1000(st.model_entry)
            if cost:
                lines.append(f"Est. cost: ~${cost * n / 1000:.2f}")
        for d in st.deltas:
            lines.append(f"Adjustment: {d['path']} -> {d['value']}")
        lines.append("")
        lines.append("Press Enter to start.")
        self.query_one("#summary", Static).update("\n".join(lines))
        (Path(st.home)).mkdir(parents=True, exist_ok=True)
        (Path(st.home) / "last_run.json").write_text(json.dumps(
            {"model_id": st.model_entry.id, "folder": str(st.folder)}))
        if st.model_entry.local:
            self.query_one("#cap", Input).display = False

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        val = ev.value.strip()
        if val:
            try:
                self.app.state.cost_cap = float(val.lstrip("$"))
            except ValueError:
                pass
        self.action_start()

    def action_start(self) -> None:
        from .screens_run import RunScreen
        self.app.push_screen(RunScreen())
```

Create a stub `curator/tui/screens_run.py` (Task 12 fills it in):

```python
# curator/tui/screens_run.py
from __future__ import annotations
from textual.screen import Screen
from textual.widgets import Footer, Header


class RunScreen(Screen):
    def compose(self):
        yield Header()
        yield Footer()
```

- [ ] **Step 4: Run tests, commit**

Run: `python -m pytest tests/test_tui_setup_flow.py -q` — Expected: 3 passed

```bash
git add curator/tui/screens_folder.py curator/tui/screens_setup.py curator/tui/screens_run.py tests/test_tui_setup_flow.py
git commit -m "feat: folder picker, intent chat, confirm screens"
```

---

### Task 12: PipelineRunner + Run and Results screens

**Files:**
- Create: `curator/tui/runner.py`
- Modify: `curator/tui/screens_run.py`, `curator/cli.py` (steer store wiring)
- Test: `tests/test_runner.py`, `tests/test_tui_journey.py`

**Interfaces:**
- Consumes: `run_pipeline(args, model_factory, steer, notify)` (Task 3), `SteeringQueue` (Task 3b), `OllamaModel`, `LiteLLMModel`, `parse_intent`, `qa.answer`.
- Produces: `factory_for(entry: ModelEntry, keystore) -> Callable[[dict], VisionModel]`; `PipelineRunner(source, out, model_entry, keystore, cfg_deltas, cost_cap=None, model_factory=None, resume=False, skip_qualification=False)` with `.start()`, `.push(deltas)`, `.state` (`.log: list[str]`, `.done: bool`, `.exit_code: int|None`, `.error: str|None`), `.model` (set once factory runs), `.cost_usd`, `.snapshot() -> dict`, `.out: Path`. Cost cap enforced inside the steer callback → raises `ModelError` → pipeline exits 4 (resumable) — no new pause machinery.

- [ ] **Step 1: cli.py steer wiring** — in `run_pipeline`, right after `store.set_meta("source_hash", shash)` add:

```python
    if steer is not None and hasattr(steer, "attach_store"):
        steer.attach_store(store)
        if args.resume:
            cfg = steer.load_applied(cfg)
```

and add to `SteeringQueue` (curator/chat/steering.py):

```python
    def attach_store(self, store) -> None:
        self._store = store
```

- [ ] **Step 2: Write the failing runner test**

```python
# tests/test_runner.py
import json, time
from curator.config import load_config
from curator.db import Store
from curator.model import MockModel
from curator.providers.catalog import ModelEntry
from curator.tui.runner import PipelineRunner, factory_for

LOCAL = ModelEntry("ollama/qwen2.5vl:7b", "ollama", "ollama", True, 0.0, 0.0)

def _handler(paths, prompt, schema):
    if "required schema" in prompt or "single valid JSON" in prompt:
        pass
    props = schema.get("properties", {})
    if "keep_worthy" in props:
        return {"keep_worthy": "yes", "real_camera_photo": "yes",
                "intentional_shot": "yes", "note": "x"}
    if "best_index" in props:
        return {"best_index": 0, "reason": "x", "unsure": "no"}
    if "flags" in props:
        return {"flags": []}
    return {"bucket": {"primary": "everyday-misc", "confidence": 0.9, "alternates": []},
            "tags": [], "description": "x",
            "people": {"count": 0, "eyes_closed": "n/a", "expression_quality": "n/a"},
            "utility": {"is_screenshot": "no", "is_document": "no", "is_accidental": "no"},
            "quality_judgment": {"fatal": "no", "note": "x"},
            "rubric": {"emotional": 1, "people_engagement": 0, "composition_light": 1,
                       "scene_appeal": 1, "novelty": 0, "justifications": {}}}

def _wait(runner, timeout=60):
    t0 = time.time()
    while not runner.state.done:
        assert time.time() - t0 < timeout, "runner hung"
        time.sleep(0.05)

def test_runner_completes_and_applies_early_steer(tmp_path, img_factory):
    src = tmp_path / "src"
    for i in range(2):
        img_factory(src / f"p{i}.jpg", "scene", seed=i,
                    exif_dt=f"2026:05:12 10:0{i}:00")
    out = tmp_path / "out"
    r = PipelineRunner(source=src, out=out, model_entry=LOCAL, keystore=None,
                       cfg_deltas=[], skip_qualification=True,
                       model_factory=lambda cfg: MockModel(_handler))
    r.push([{"path": "prompt_suffix", "op": "append", "value": "KIDS FIRST", "why": ""}])
    r.start()
    _wait(r)
    assert r.state.exit_code == 0 and r.state.error is None
    assert (out / "REPORT.md").exists()
    store = Store(out / "curation.db")
    applied = json.loads(store.get_meta("user_deltas"))
    assert applied[0]["deltas"][0]["value"] == "KIDS FIRST"

def test_factory_for_local_builds_ollama():
    from curator.model import OllamaModel
    m = factory_for(LOCAL, None)(load_config(None))
    assert isinstance(m, OllamaModel)

def test_factory_for_cloud_builds_litellm(tmp_path):
    from curator.providers.keystore import KeyStore
    from curator.providers.litellm_model import LiteLLMModel
    cloud = ModelEntry("gpt-4o-mini", "openai", "litellm", False)
    ks = KeyStore(home=tmp_path, backend="file")
    m = factory_for(cloud, ks)(load_config(None))
    assert isinstance(m, LiteLLMModel)
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_runner.py -q`
Expected: FAIL — no module `curator.tui.runner`

- [ ] **Step 4: Implement the runner**

```python
# curator/tui/runner.py
from __future__ import annotations
import argparse, threading
from dataclasses import dataclass, field
from pathlib import Path
from ..chat.deltas import apply_deltas
from ..chat.steering import SteeringQueue
from ..cli import run_pipeline
from ..model import ModelError, OllamaModel
from ..providers.catalog import ModelEntry


def factory_for(entry: ModelEntry, keystore):
    def make(cfg):
        if entry.source == "ollama" or entry.id.startswith("ollama/"):
            return OllamaModel(entry.id.removeprefix("ollama/"), cfg["ollama_url"],
                               cfg["llm"]["timeout_s"], cfg["llm"]["seed"],
                               cfg["llm"]["analyze_edge_px"])
        from ..providers.litellm_model import LiteLLMModel
        return LiteLLMModel(entry.id, keystore, cfg["llm"]["timeout_s"],
                            cfg["llm"]["seed"], cfg["llm"]["analyze_edge_px"])
    return make


@dataclass
class RunnerState:
    log: list[str] = field(default_factory=list)
    done: bool = False
    exit_code: int | None = None
    error: str | None = None


class PipelineRunner:
    def __init__(self, source: Path, out: Path, model_entry: ModelEntry, keystore,
                 cfg_deltas: list[dict], cost_cap: float | None = None,
                 model_factory=None, resume: bool = False,
                 skip_qualification: bool = False, fast: bool = False):
        self.out = Path(out)
        self.steering = SteeringQueue()
        self.state = RunnerState()
        self.model = None
        self.cost_cap = cost_cap
        self._deltas = cfg_deltas
        self._factory = model_factory or factory_for(model_entry, keystore)
        self._args = argparse.Namespace(
            source=str(source), out=str(out), config=None, model=None,
            fast=fast, resume=resume, dry_run=False,
            skip_qualification=skip_qualification)

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def push(self, deltas: list[dict]) -> None:
        self.steering.push(deltas)

    @property
    def cost_usd(self) -> float:
        return getattr(self.model, "cost_usd", 0.0)

    def snapshot(self) -> dict:
        return {"log_tail": self.state.log[-8:], "cost_usd": round(self.cost_usd, 4),
                "done": self.state.done}

    # ---- internal ----
    def _notify(self, msg) -> None:
        self.state.log.append(str(msg))

    def _wrapped_factory(self, cfg):
        # pre-run intent deltas fold into cfg BEFORE anything runs (R4: they
        # were confirmed on the Confirm screen)
        self.model = self._factory(cfg)
        return self.model

    def _steer(self, cfg, idx):
        if self.cost_cap is not None and self.cost_usd >= self.cost_cap:
            raise ModelError(f"cost cap ${self.cost_cap} reached at photo {idx} - "
                             "resume to continue")
        return self.steering(cfg, idx)

    def _run(self) -> None:
        try:
            if self._deltas:
                self.steering.push(self._deltas)   # effective from photo 0, recorded
            code = run_pipeline(self._args, model_factory=self._wrapped_factory,
                                steer=self._steer, notify=self._notify)
            self.state.exit_code = code
        except Exception as exc:                    # never kill the UI thread
            self.state.error = str(exc)
        finally:
            self.state.done = True
```

Wait — pre-run deltas pushed through steering apply from photo 0 of STAGE 3, but `skip_globs`/`triage` deltas must act in stages 1-2. Fold them directly instead: change `_run` to apply `self._deltas` via a config overlay file. Since `run_pipeline` loads config internally, write the merged config to `<out>/.tui-config.yaml` and set `self._args.config` to it:

```python
    def _run(self) -> None:
        try:
            if self._deltas:
                from ..config import load_config
                import yaml
                merged = apply_deltas(load_config(None), self._deltas)
                self.out.mkdir(parents=True, exist_ok=True)
                cfg_f = self.out / ".tui-config.yaml"
                cfg_f.write_text(yaml.safe_dump(merged))
                self._args.config = str(cfg_f)
            code = run_pipeline(self._args, model_factory=self._wrapped_factory,
                                steer=self._steer, notify=self._notify)
            self.state.exit_code = code
        except Exception as exc:
            self.state.error = str(exc)
        finally:
            self.state.done = True
```

(Use this version; drop the `steering.push(self._deltas)` line. Mid-run pushes still go through `_steer`. The runner test pushes BEFORE start — that is fine: the queue drains at photo 0 and records `effective_from: 0`.)

- [ ] **Step 5: Run runner tests**

Run: `python -m pytest tests/test_runner.py -q`
Expected: 3 passed

- [ ] **Step 6: Implement Run + Results screens** — replace `curator/tui/screens_run.py`:

```python
# curator/tui/screens_run.py
from __future__ import annotations
from datetime import date
from pathlib import Path
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Log, Static
from ..chat.deltas import describe
from ..chat.intent import parse_intent
from ..config import load_config
from ..db import Store
from .runner import PipelineRunner, factory_for


class RunScreen(Screen):
    BINDINGS = [("c", "cancel", "Cancel (resumable)")]

    def compose(self):
        yield Header()
        yield Static("Starting…", id="status")
        yield Log(id="runlog")
        yield Input(placeholder="talk to the curator while it works…", id="chat")
        yield Footer()

    def on_mount(self) -> None:
        st = self.app.state
        out = st.folder.parent / f"curated-{date.today().isoformat()}"
        self.runner = PipelineRunner(
            source=st.folder, out=out, model_entry=st.model_entry,
            keystore=st.keystore, cfg_deltas=st.deltas, cost_cap=st.cost_cap,
            model_factory=self.app.model_factory)
        self._shown = 0
        self.runner.start()
        self.set_interval(0.3, self._refresh)

    def _refresh(self) -> None:
        log = self.query_one("#runlog", Log)
        while self._shown < len(self.runner.state.log):
            log.write_line(self.runner.state.log[self._shown])
            self._shown += 1
        s = self.runner.state
        cost = f" · ${self.runner.cost_usd:.2f}" if self.runner.cost_usd else ""
        self.query_one("#status", Static).update(
            ("done" if s.done else "curating…") + cost)
        if s.done:
            self.app.push_screen(ResultsScreen(self.runner))

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        text = ev.value.strip()
        ev.input.value = ""
        if text:
            self.run_worker(lambda: self._chat(text), thread=True)

    def _chat(self, text: str) -> None:
        factory = self.app.model_factory or factory_for(
            self.app.state.model_entry, self.app.state.keystore)
        model = factory(self.app.state.cfg)
        out = parse_intent(model, self.app.state.cfg, text,
                           run_state=self.runner.snapshot())
        log = self.query_one("#runlog", Log)
        if out["deltas"] and not self.runner.state.done:
            self.runner.push(out["deltas"])
            for line in describe(out["deltas"]):
                self.app.call_from_thread(
                    log.write_line, f"↪ applied from next photo: {line}")
        self.app.call_from_thread(log.write_line, f"curator: {out['reply']}")

    def action_cancel(self) -> None:
        self.app.exit(message=f"Cancelled - resume anytime: photo-curator run "
                              f"{self.app.state.folder} --out {self.runner.out} --resume")


class ResultsScreen(Screen):
    BINDINGS = [("o", "open_folder", "Open output")]

    def __init__(self, runner: PipelineRunner):
        super().__init__()
        self.runner = runner

    def compose(self):
        yield Header()
        yield Static(id="summary")
        yield Log(id="qalog")
        yield Input(placeholder="ask me anything about this run…", id="qa")
        yield Footer()

    def on_mount(self) -> None:
        s = self.runner.state
        tail = "\n".join(s.log[-6:])
        head = ("Curation complete." if s.exit_code == 0
                else f"Run stopped (code {s.exit_code}): {s.error or ''}")
        self.query_one("#summary", Static).update(
            f"{head}\n\n{tail}\n\nOutput: {self.runner.out}")

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        q = ev.value.strip()
        ev.input.value = ""
        if q:
            self.run_worker(lambda: self._answer(q), thread=True)

    def _answer(self, q: str) -> None:
        from ..chat.qa import answer
        factory = self.app.model_factory or factory_for(
            self.app.state.model_entry, self.app.state.keystore)
        model = factory(self.app.state.cfg)
        store = Store(self.runner.out / "curation.db")
        try:
            reply = answer(model, store, self.app.state.cfg, q)
        finally:
            store.close()
        log = self.query_one("#qalog", Log)
        self.app.call_from_thread(log.write_line, f"you: {q}")
        self.app.call_from_thread(log.write_line, f"curator: {reply}")

    def action_open_folder(self) -> None:
        import webbrowser
        webbrowser.open(self.runner.out.as_uri())
```

- [ ] **Step 7: Write the full-journey test (R9: three interactions + chat)**

```python
# tests/test_tui_journey.py
from curator.config import load_config
from curator.model import MockModel
from curator.providers.catalog import ModelEntry
from curator.providers.keystore import KeyStore
from curator.tui.app import CuratorApp
from curator.tui.detect import Detection
from tests.test_runner import _handler

LOCAL = ModelEntry("ollama/qwen2.5vl:7b", "ollama", "ollama", True, 0.0, 0.0)

async def test_first_run_journey_to_results(tmp_path, img_factory):
    src = tmp_path / "src"
    for i in range(2):
        img_factory(src / f"p{i}.jpg", "scene", seed=i,
                    exif_dt=f"2026:05:12 10:0{i}:00")
    def factory(cfg):
        return MockModel(_handler)
    app = CuratorApp(cfg=load_config(None), home=tmp_path / "home",
                     keystore=KeyStore(home=tmp_path / "home", backend="file"),
                     detection=Detection(True, [LOCAL], [], None),
                     catalog_fn=lambda cfg: [LOCAL], model_factory=factory)
    async with app.run_test() as pilot:
        await pilot.press("enter")                 # 1: welcome -> picker
        app.screen.select_model(LOCAL)             # 2: model
        await pilot.pause()
        app.screen.set_folder(src)                 # 3: folder
        await pilot.pause()
        await pilot.press("enter")                 # skip intent
        await pilot.pause()
        await pilot.press("enter")                 # confirm -> run
        for _ in range(200):                       # wait for pipeline thread
            await pilot.pause(delay=0.1)
            if app.screen.__class__.__name__ == "ResultsScreen":
                break
        assert app.screen.__class__.__name__ == "ResultsScreen"
        out = src.parent.glob("curated-*")
        assert any((d / "REPORT.md").exists() for d in out)
```

Note: MockModel has no `cost_usd`; `PipelineRunner.cost_usd` uses `getattr(..., 0.0)` so this is safe. The pipeline's qualification gate runs against MockModel and passes only if `_handler` answers the calibration checks — it does not (generic answers). So `RunScreen.on_mount` must pass `skip_qualification` for factories that are mocks? No — keep it honest: the journey test's `_handler` from `tests/test_runner.py` answers `fatal: no` for everything, which FAILS the gate (exit 2) and Results shows "Run stopped". Fix the test setup instead: reuse the qualification-aware handler. Change `factory` in the journey test to wrap `tests/test_qualification._smart_handler` for calibration images (they are PNGs named blur_*/black/shot_*/receipt/scene_*) and `_handler` otherwise:

```python
from tests.test_qualification import _smart_handler

def _journey_handler(paths, prompt, schema):
    name = paths[0].name if paths else ""
    if name.startswith(("blur", "black", "shot", "receipt", "scene_")) and name.endswith(".png"):
        return _smart_handler(paths, prompt, schema)
    return _handler(paths, prompt, schema)

    def factory(cfg):
        return MockModel(_journey_handler)
```

Use `_journey_handler` in the journey test (replace the plain `factory` above).

- [ ] **Step 8: Run everything, commit**

Run: `python -m pytest tests/test_runner.py tests/test_tui_journey.py -q`
Expected: 4 passed
Run: `python -m pytest -q`
Expected: full suite green

```bash
git add curator/tui/runner.py curator/tui/screens_run.py curator/chat/steering.py curator/cli.py tests/test_runner.py tests/test_tui_journey.py
git commit -m "feat: pipeline runner thread, live run screen with steering chat, results Q&A"
```

---

### Task 13: CLI entry (no-args TUI, --version) + steering determinism property

**Files:**
- Modify: `curator/cli.py`
- Test: `tests/test_cli_entry.py`, `tests/test_steering_determinism.py`

**Interfaces:**
- Produces: `photo-curator` with no args (or `photo-curator tui`) launches `CuratorApp().run()`; missing extras → friendly stderr + exit 1; `--version` prints `photo-curator <__version__>`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_entry.py
import pytest
from curator import __version__
from curator.cli import main

def test_version_flag(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out

def test_no_args_launches_tui(monkeypatch):
    launched = {}
    class FakeApp:
        def run(self): launched["yes"] = True
    monkeypatch.setattr("curator.tui.app.CuratorApp", lambda: FakeApp())
    assert main([]) == 0
    assert launched.get("yes")

def test_missing_extras_message(monkeypatch, capsys):
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name.startswith("curator.tui"):
            raise ModuleNotFoundError("textual")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert main([]) == 1
    assert "photo-curator[app]" in capsys.readouterr().err
```

```python
# tests/test_steering_determinism.py
"""Spec §12.4: a run steered at photo k equals a fresh run whose config
changes at photo k. With k=0 that means: steered run == config-from-start."""
import argparse, json
from curator.cli import run_pipeline
from curator.chat.steering import SteeringQueue
from curator.config import load_config
from curator.model import MockModel
from tests.test_runner import _handler
from tests.test_qualification import _smart_handler

def _h(paths, prompt, schema):
    name = paths[0].name if paths else ""
    if name.endswith(".png") and name.split("_")[0] in (
            "blur", "black", "shot", "receipt", "scene"):
        return _smart_handler(paths, prompt, schema)
    return _handler(paths, prompt, schema)

def _args(src, out):
    return argparse.Namespace(source=str(src), out=str(out), config=None,
                              model=None, fast=False, resume=False,
                              dry_run=False, skip_qualification=True)

def _manifest(out):
    m = json.loads((out / "manifest.json").read_text())
    m.pop("timings", None)
    return m

def test_steer_at_zero_equals_config_from_start(tmp_path, img_factory):
    src = tmp_path / "src"
    for i in range(3):
        img_factory(src / f"p{i}.jpg", "scene", seed=i,
                    exif_dt=f"2026:05:12 10:0{i}:00")
    delta = [{"path": "prompt_suffix", "op": "append",
              "value": "KIDS FIRST", "why": ""}]
    # Run A: steered from photo 0
    steer = SteeringQueue()
    steer.push(delta)
    a_out = tmp_path / "a"
    assert run_pipeline(_args(src, a_out), model_factory=lambda c: MockModel(_h),
                        steer=steer) == 0
    # Run B: same delta baked into the config file from the start
    import yaml
    from curator.chat.deltas import apply_deltas
    cfg_f = tmp_path / "cfg.yaml"
    cfg_f.write_text(yaml.safe_dump(apply_deltas(load_config(None), delta)))
    b_out = tmp_path / "b"
    b_args = _args(src, b_out)
    b_args.config = str(cfg_f)
    assert run_pipeline(b_args, model_factory=lambda c: MockModel(_h)) == 0
    ma, mb = _manifest(a_out), _manifest(b_out)
    # config hashes legitimately differ (steering is not in the file config);
    # every DECISION must be identical
    ma.pop("config_hash", None); mb.pop("config_hash", None)
    ma.pop("config", None); mb.pop("config", None)
    assert ma == mb
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_cli_entry.py tests/test_steering_determinism.py -q`
Expected: FAIL — `--version` unknown, no-args exits with argparse error

- [ ] **Step 3: Implement in `curator/cli.py`** — add `from . import __version__` to the imports, and replace the head of `main`:

```python
def main(argv=None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if argv in ([], ["tui"]):
        try:
            from curator.tui.app import CuratorApp
        except ModuleNotFoundError:
            print("The interactive app needs extras. Install with:\n"
                  "  pip install 'photo-curator[app]'", file=sys.stderr)
            return 1
        CuratorApp().run()
        return 0
    ap = argparse.ArgumentParser(prog="photo-curator")
    ap.add_argument("--version", action="version",
                    version=f"photo-curator {__version__}")
    ...  # existing subparsers unchanged
```

- [ ] **Step 4: Run tests, commit**

Run: `python -m pytest tests/test_cli_entry.py tests/test_steering_determinism.py -q`
Expected: 4 passed

```bash
git add curator/cli.py tests/test_cli_entry.py tests/test_steering_determinism.py
git commit -m "feat: no-args TUI launch, --version; prove steering determinism"
```

---

### Task 14: Packaging — PyInstaller spec, release CI, installers

**Files:**
- Create: `packaging/photo-curator.spec`, `.github/workflows/release.yml`, `scripts/install.sh`, `scripts/install.ps1`
- Test: manual/CI only (no pytest for packaging)

- [ ] **Step 1: PyInstaller spec**

```python
# packaging/photo-curator.spec
# Build: pyinstaller packaging/photo-curator.spec
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("../curator/data", "curator/data"),
    ("../curator/prompts", "curator/prompts"),
    ("../curator/schemas", "curator/schemas"),
    ("../curator/providers/registry.yaml", "curator/providers"),
]
datas += collect_data_files("litellm")          # model_prices json
datas += collect_data_files("textual")

hiddenimports = (collect_submodules("keyring.backends")
                 + ["PIL._tkinter_finder"])

a = Analysis(["../curator/__main__.py"], pathex=[".."], datas=datas,
             hiddenimports=hiddenimports, excludes=["tkinter", "matplotlib"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="photo-curator",
          console=True, onefile=True, strip=False, upx=False)
```

Also create `curator/__main__.py`:

```python
import sys
from curator.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Release workflow**

```yaml
# .github/workflows/release.yml
name: release
on:
  push:
    tags: ["v*"]
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - {os: macos-14,        target: macos-arm64}
          - {os: macos-13,        target: macos-x86_64}
          - {os: ubuntu-22.04,     target: linux-x86_64}
          - {os: ubuntu-22.04-arm, target: linux-arm64}
          - {os: windows-2022,     target: windows-x86_64}
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install ".[app]" pyinstaller
      - run: pyinstaller packaging/photo-curator.spec
      - name: smoke test
        shell: bash
        run: ./dist/photo-curator* --version
      - name: ad-hoc sign (macOS)
        if: startsWith(matrix.os, 'macos')
        run: codesign --force -s - dist/photo-curator
      - name: rename
        shell: bash
        run: |
          ext=""
          [[ "${{ matrix.target }}" == windows-* ]] && ext=".exe"
          mv dist/photo-curator$ext dist/photo-curator-${{ matrix.target }}$ext
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/photo-curator-*
  test:
    strategy:
      matrix: {os: [macos-14, ubuntu-22.04, windows-2022]}
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -e ".[dev]"
      - run: python -m pytest -q
```

- [ ] **Step 3: Installers**

```bash
#!/bin/sh
# scripts/install.sh — curl -fsSL <raw-url>/scripts/install.sh | sh
set -e
REPO="cindulasai/photo-curator"
case "$(uname -s)" in
  Darwin) os="macos" ;;
  Linux)  os="linux" ;;
  *) echo "Use install.ps1 on Windows"; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) arch="arm64" ;;
  x86_64)        arch="x86_64" ;;
  *) echo "unsupported arch: $(uname -m)"; exit 1 ;;
esac
asset="photo-curator-${os}-${arch}"
url=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" |
      grep browser_download_url | grep "$asset" | cut -d'"' -f4)
[ -n "$url" ] || { echo "no binary for $asset"; exit 1; }
dest="${HOME}/.local/bin"
mkdir -p "$dest"
curl -fsSL "$url" -o "$dest/photo-curator"
chmod +x "$dest/photo-curator"
echo "Installed to $dest/photo-curator"
case ":$PATH:" in *":$dest:"*) ;; *) echo "Add $dest to your PATH." ;; esac
```

```powershell
# scripts/install.ps1 — irm <raw-url>/scripts/install.ps1 | iex
$repo = "cindulasai/photo-curator"
$asset = "photo-curator-windows-x86_64.exe"
$rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
$url = ($rel.assets | Where-Object name -eq $asset).browser_download_url
if (-not $url) { throw "no binary $asset in latest release" }
$dest = "$env:LOCALAPPDATA\photo-curator"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Invoke-WebRequest $url -OutFile "$dest\photo-curator.exe"
Write-Host "Installed to $dest\photo-curator.exe - add $dest to your PATH."
```

- [ ] **Step 4: Local verification**

Run: `pip install pyinstaller && pyinstaller packaging/photo-curator.spec && ./dist/photo-curator --version`
Expected: `photo-curator 0.1.0`

- [ ] **Step 5: Commit**

```bash
git add packaging curator/__main__.py .github/workflows/release.yml scripts/install.sh scripts/install.ps1
git commit -m "build: one-file binaries for 5 targets, release CI, installers"
```

---

### Task 15: Docs + finish

**Files:**
- Modify: `README.md` (add TUI quick start + install one-liners), `SKILL.md` (mention `photo-curator` no-args TUI)

- [ ] **Step 1: README** — insert after the "Quick start" heading's intro, replacing the pip-only block with:

```markdown
**Easiest:** download one file from [Releases](https://github.com/cindulasai/photo-curator/releases)
and run it — the app walks you through everything.

    # macOS / Linux
    curl -fsSL https://raw.githubusercontent.com/cindulasai/photo-curator/main/scripts/install.sh | sh
    photo-curator

    # Windows (PowerShell)
    irm https://raw.githubusercontent.com/cindulasai/photo-curator/main/scripts/install.ps1 | iex

**Python users:**

    pip install -e ".[app]"
    photo-curator            # opens the app; CLI subcommands still work
```

- [ ] **Step 2: SKILL.md** — in "Quick start", add one line above the existing block:

```markdown
Interactive app: run `photo-curator` with no arguments - pick a model
(local Ollama or any API vision model), pick a folder, chat your wishes.
```

- [ ] **Step 3: Full verification**

Run: `python -m pytest -q`
Expected: every test green (63 baseline + ~40 new)

- [ ] **Step 4: Commit, then finish the branch**

```bash
git add README.md SKILL.md
git commit -m "docs: TUI quick start and installers"
```

Then: **REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch (merge `tui-phase1` to `main`, rerun suite, push).

---

## Self-review notes

- **Spec coverage:** R1 (Python only) ✓ all tasks; R2 (vision-only, mechanical) ✓ Task 4; R3 untouched ✓; R4 (auditable deltas, confirm before apply) ✓ Tasks 2/7/11; R5 (boundary steering + resume re-apply) ✓ Tasks 3/3b/12/13; R6 keystore ✓ Task 1; R7 consent ✓ Task 10; R8 gate for every model ✓ existing `run_pipeline` gate runs for LiteLLM models unchanged; R9 three interactions ✓ journey test in Task 12; R10 ✓ no image protocols anywhere. Spec §11 rows: rate-limit backoff (Task 6), invalid key re-prompt (KeyModal reappears because `keystore.get` returns the bad key — qualification failure exits with message; acceptable for Phase 1, noted), cost cap (Tasks 11/12), invalid chat delta fallback (Task 7).
- **Type consistency check:** `ModelEntry` fields consistent across Tasks 4/5/9-12; `parse_intent` signature identical in Tasks 7/11/12; `SteeringQueue.attach_store` added in Task 12 Step 1 and used by `run_pipeline`; `factory_for(entry, keystore)` consistent in Tasks 11/12.
- **Known deviations (documented on purpose):** mid-run pause key (`p`) from spec §4.1 is deferred — cancel-and-resume covers the need in Phase 1; `--fast` toggle not exposed in TUI Confirm screen (CLI flag still available).


