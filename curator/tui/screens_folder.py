# curator/tui/screens_folder.py
from __future__ import annotations
from textual.screen import Screen
from textual.widgets import Footer, Header


class FolderScreen(Screen):
    def compose(self):
        yield Header()
        yield Footer()
