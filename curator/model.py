from __future__ import annotations
import base64, io, json
from pathlib import Path
from typing import Callable, Protocol
import jsonschema
import requests
from PIL import Image, ImageOps

JSON_REPAIR_V1 = (
    "\n\nYour previous reply was not valid JSON matching the required schema. "
    "Reply again with ONLY a single valid JSON object matching the schema. "
    "No prose, no markdown fences. Your previous reply was:\n")


class ModelError(Exception):
    pass


class InvalidOutput(ModelError):
    pass


class VisionModel(Protocol):
    def analyze(self, image_paths: list[Path], prompt: str, json_schema: dict) -> dict: ...
    def name(self) -> str: ...


def _encode(path: Path, edge_px: int) -> str:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((edge_px, edge_px))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def _validate(raw: str, schema: dict) -> dict:
    data = json.loads(raw)
    jsonschema.validate(data, schema)
    return data


class OllamaModel:
    def __init__(self, model: str, url: str, timeout_s: int = 120,
                 seed: int = 42, edge_px: int = 1024):
        self.model, self.url = model, url.rstrip("/")
        self.timeout_s, self.seed, self.edge_px = timeout_s, seed, edge_px

    def name(self) -> str:
        return f"ollama/{self.model}"

    def _call(self, prompt: str, images: list[str], schema: dict) -> str:
        last = None
        for _ in range(3):                                  # 2 transport retries
            try:
                resp = requests.post(f"{self.url}/api/chat", json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt, "images": images}],
                    "stream": False, "format": schema,
                    "options": {"temperature": 0, "seed": self.seed}},
                    timeout=self.timeout_s)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
            except (requests.RequestException, KeyError) as exc:
                last = exc
        raise ModelError(f"Ollama unreachable or malformed response: {last!r}")

    def analyze(self, image_paths: list[Path], prompt: str, json_schema: dict) -> dict:
        images = [_encode(p, self.edge_px) for p in image_paths]
        raw = self._call(prompt, images, json_schema)
        for _ in range(3):                                  # initial + 2 repairs
            try:
                return _validate(raw, json_schema)
            except (json.JSONDecodeError, jsonschema.ValidationError):
                raw = self._call(prompt + JSON_REPAIR_V1 + raw, images, json_schema)
        raise InvalidOutput(f"model {self.name()} produced invalid output after repairs")


class MockModel:
    def __init__(self, handler: Callable[[list[Path], str, dict], dict],
                 name: str = "mock"):
        self.handler, self._name, self.calls = handler, name, []

    def name(self) -> str:
        return self._name

    def analyze(self, image_paths: list[Path], prompt: str, json_schema: dict) -> dict:
        self.calls.append((list(image_paths), prompt))
        out = self.handler(image_paths, prompt, json_schema)
        try:
            jsonschema.validate(out, json_schema)
        except jsonschema.ValidationError as exc:
            raise InvalidOutput(str(exc))
        return out
