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
