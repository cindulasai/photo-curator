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
