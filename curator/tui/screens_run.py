# curator/tui/screens_run.py
from __future__ import annotations
from textual.screen import Screen
from textual.widgets import Footer, Header


class RunScreen(Screen):
    def compose(self):
        yield Header()
        yield Footer()
