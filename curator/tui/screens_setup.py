# curator/tui/screens_setup.py
from __future__ import annotations
import json
from pathlib import Path
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static
from ..chat.deltas import describe
from ..chat.intent import parse_intent
from ..providers.registry import est_cost_per_1000
from .screens_folder import count_photos


class IntentScreen(Screen):
    BINDINGS = [("a", "accept", "Accept changes")]

    def compose(self):
        yield Header()
        yield Static("Anything special you want? (Enter to just curate)")
        yield Input(placeholder="e.g. focus on my kids, skip food photos", id="wish")
        yield Static("", id="parsed")
        yield Footer()

    def on_mount(self) -> None:
        self._pending = None
        self.query_one("#wish", Input).focus()

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        text = ev.value.strip()
        if not text:
            self._advance()
            return
        self.set_focus(None)   # blur so screen-level 'a' binding fires
        self.run_worker(lambda: self._parse(text), thread=True)

    def _parse(self, text: str) -> None:
        try:
            factory = self.app.model_factory
            if factory is None:
                from .runner import factory_for
                factory = factory_for(self.app.state.model_entry, self.app.state.keystore)
            model = factory(self.app.state.cfg)
            out = parse_intent(model, self.app.state.cfg, text)
            self._pending = out["deltas"]
            lines = describe(out["deltas"]) or ["(no changes)"]
            self.app.call_from_thread(
                self.query_one("#parsed", Static).update,
                out["reply"] + "\n" + "\n".join(f"  {ln}" for ln in lines)
                + "\n\nPress [a] to accept, or type again.")
        except Exception as e:
            self.app.call_from_thread(
                self.query_one("#parsed", Static).update,
                f"curator: something went wrong — {e}")

    def action_accept(self) -> None:
        if self._pending:
            self.app.state.deltas = self._pending
        self._advance()

    def _advance(self) -> None:
        self.app.push_screen(ConfirmScreen())


class ConfirmScreen(Screen):
    BINDINGS = [("enter", "start", "Start curating")]

    def compose(self):
        yield Header()
        yield Static(id="summary")
        yield Input(placeholder="optional $ cost cap (cloud only) - Enter to start",
                    id="cap")
        yield Footer()

    def on_mount(self) -> None:
        st = self.app.state
        n = count_photos(st.folder)
        self._n = n
        lines = [f"Model:   {st.model_entry.id}",
                 f"Folder:  {st.folder}  ({n} photos)",
                 f"Est. time: ~{n * 8 / 60:.0f} min at 8 s/photo"]
        if not st.model_entry.local:
            cost = est_cost_per_1000(st.model_entry)
            if cost:
                lines.append(f"Est. cost: ~${cost * n / 1000:.2f}")
        for d in st.deltas:
            lines.append(f"Adjustment: {d['path']} -> {d['value']}")
        lines.append("")
        lines.append("Press Enter to start.")
        self.query_one("#summary", Static).update("\n".join(lines))
        (Path(st.home)).mkdir(parents=True, exist_ok=True)
        (Path(st.home) / "last_run.json").write_text(json.dumps(
            {"model_id": st.model_entry.id, "folder": str(st.folder)}))
        if st.model_entry.local:
            self.query_one("#cap", Input).display = False

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        val = ev.value.strip()
        if val:
            try:
                self.app.state.cost_cap = float(val.lstrip("$"))
            except ValueError:
                pass
        self.action_start()

    def action_start(self) -> None:
        from .screens_run import RunScreen
        self.app.push_screen(RunScreen())
