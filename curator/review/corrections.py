from __future__ import annotations

import json
from pathlib import Path

CORRECTIONS_HOME = Path.home() / ".photo-curator"
_FILE_NAME = "corrections.jsonl"


def _path() -> Path:
    """Return the path to the corrections file, creating directory if needed."""
    CORRECTIONS_HOME.mkdir(parents=True, exist_ok=True)
    return CORRECTIONS_HOME / _FILE_NAME


def append_correction(event: dict) -> None:
    """Append a correction event as a JSON line to the corrections file."""
    with _path().open("a") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def load_corrections(run_id: str | None = None) -> list[dict]:
    """Load all corrections, optionally filtered by run_id.

    Silently skips malformed JSON lines.
    """
    p = _path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if run_id is None or ev.get("run") == run_id:
            out.append(ev)
    return out


def was_declined(key: str) -> bool:
    """Check if a feature key has been declined."""
    return any(
        e.get("kind") == "declined" and e.get("key") == key
        for e in load_corrections()
    )
