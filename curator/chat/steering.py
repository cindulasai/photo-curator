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

    def attach_store(self, store) -> None:
        self._store = store

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
