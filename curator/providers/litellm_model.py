from __future__ import annotations
import json, time
from pathlib import Path
from curator.model import JSON_REPAIR_V1, InvalidOutput, ModelError, _encode, _validate

_KNOWN_PREFIXES = ("openrouter", "gemini", "anthropic", "ollama", "deepseek",
                   "minimax", "openai", "azure", "groq", "together_ai")


def _sleep(s: float) -> None:      # patchable in tests
    time.sleep(s)


def provider_of(model: str) -> str:
    head = model.split("/", 1)[0]
    if head in _KNOWN_PREFIXES:
        return head
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if "claude" in model:
        return "anthropic"
    return "openai"


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
        return provider_of(self.model)

    def _messages(self, prompt: str, images: list[str]) -> list[dict]:
        if not images:
            return [{"role": "user", "content": prompt}]
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in images]
        return [{"role": "user", "content": content}]

    def _call(self, prompt: str, images: list[str], schema: dict) -> str:
        import litellm
        provider = self.provider()
        if provider != "ollama":
            key = self.keystore.get(provider)
            if key:
                setattr(litellm, f"{provider}_key", key)
        last = None
        for attempt in range(5):
            kwargs = dict(model=self.model,
                          messages=self._messages(self._maybe_embed(prompt, schema), images),
                          temperature=0, seed=self.seed,
                          timeout=self.timeout_s)
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
