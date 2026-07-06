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
