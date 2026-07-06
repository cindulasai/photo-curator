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
