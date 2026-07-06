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
