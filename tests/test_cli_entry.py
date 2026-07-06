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
