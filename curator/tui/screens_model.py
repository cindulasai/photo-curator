# curator/tui/screens_model.py
from __future__ import annotations
import json
import requests
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, Input, OptionList, ProgressBar, Static
from textual.widgets.option_list import Option
from ..providers.catalog import ModelEntry
from ..providers.litellm_model import provider_of
from ..providers.registry import est_cost_per_1000, load_registry, tiered


class ModelPickerScreen(Screen):
    def compose(self):
        yield Header()
        yield Static("Choose your vision model (Enter to select)")
        yield OptionList(id="models")
        yield Footer()

    def on_mount(self) -> None:
        catalog = self.app.catalog_fn(self.app.state.cfg)
        rec, rest = tiered(catalog, load_registry())
        ol = self.query_one("#models", OptionList)
        self._entries: dict[str, ModelEntry] = {}
        ol.add_option(Option("── RECOMMENDED ──", disabled=True))
        for e in rec:
            self._entries[e.id] = e
            ol.add_option(Option(self._label(e), id=e.id))
        ol.add_option(Option("── ALL VISION MODELS ──", disabled=True))
        for e in rest:
            if e.id not in self._entries:
                self._entries[e.id] = e
                ol.add_option(Option(self._label(e), id=e.id))

    @staticmethod
    def _label(e: ModelEntry) -> str:
        if e.local:
            badge = "local · free"
        else:
            cost = est_cost_per_1000(e)
            badge = f"api · ~${cost} per 1,000 photos" if cost else "api"
        pull = "" if e.installed else "  [not pulled — Enter to pull]"
        return f"{e.id}  ({badge}){pull}"

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected) -> None:
        self.select_model(self._entries[ev.option.id])

    def select_model(self, entry: ModelEntry) -> None:
        # Use cached entry (may have installed flag updated by tiered())
        entry = self._entries.get(entry.id, entry)
        self.app.state.model_entry = entry
        if entry.local:
            if not entry.installed:
                self.app.push_screen(PullModal(entry), self._after_pull)
                return
            self._advance()
            return
        provider = provider_of(entry.id)
        if not self.app.state.consented(provider):
            self.app.push_screen(ConsentModal(provider), self._after_consent)
        else:
            self._maybe_key(provider)

    def _after_consent(self, agreed: bool | None) -> None:
        provider = provider_of(self.app.state.model_entry.id)
        if not agreed:
            self.app.state.model_entry = None
            return
        self.app.state.record_consent(provider)
        self._maybe_key(provider)

    def _maybe_key(self, provider: str) -> None:
        if self.app.state.keystore.get(provider) is None:
            self.app.push_screen(KeyModal(provider), self._after_key)
        else:
            self._advance()

    def _after_key(self, key: str | None) -> None:
        if not key:
            self.app.state.model_entry = None
            return
        provider = provider_of(self.app.state.model_entry.id)
        self.app.state.keystore.set(provider, key)
        self._advance()

    def _after_pull(self, ok: bool | None) -> None:
        if ok:
            self.app.state.model_entry.installed = True
            self._advance()

    def _advance(self) -> None:
        from .screens_folder import FolderScreen
        self.app.push_screen(FolderScreen())


class ConsentModal(ModalScreen[bool]):
    """R7: one-time per-provider cloud consent."""
    BINDINGS = [("y", "yes", "Yes"), ("n", "no", "No"), ("escape", "no", "No")]

    def __init__(self, provider: str):
        super().__init__()
        self.provider = provider

    def compose(self):
        yield Vertical(
            Static(f"Using this model sends your photos to {self.provider} "
                   "for analysis.\nLocal models keep photos on this machine.\n\n"
                   "Continue?  [y]es / [n]o", id="consent-text"))

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class KeyModal(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, provider: str):
        super().__init__()
        self.provider = provider

    def compose(self):
        yield Vertical(
            Static(f"Paste your {self.provider} API key "
                   "(stored in your OS keychain, never in files):"),
            Input(password=True, id="key"))

    def on_mount(self) -> None:
        self.query_one("#key", Input).focus()

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        self.dismiss(ev.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PullModal(ModalScreen[bool]):
    def __init__(self, entry: ModelEntry):
        super().__init__()
        self.entry = entry

    def compose(self):
        name = self.entry.id.removeprefix("ollama/")
        yield Vertical(Static(f"Pulling {name}…"), ProgressBar(id="pull"))

    def on_mount(self) -> None:
        self.run_worker(self._pull, thread=True)

    def _pull(self) -> None:
        name = self.entry.id.removeprefix("ollama/")
        url = self.app.state.cfg["ollama_url"].rstrip("/") + "/api/pull"
        bar = self.query_one("#pull", ProgressBar)
        try:
            with requests.post(url, json={"model": name}, stream=True,
                               timeout=3600) as resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("total") and d.get("completed"):
                        self.app.call_from_thread(
                            bar.update, total=d["total"], progress=d["completed"])
            self.app.call_from_thread(self.dismiss, True)
        except requests.RequestException:
            self.app.call_from_thread(self.dismiss, False)
