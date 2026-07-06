from __future__ import annotations
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList


class ModelPickerScreen(Screen):
    def compose(self):
        yield Header()
        yield OptionList(id="models")
        yield Footer()
