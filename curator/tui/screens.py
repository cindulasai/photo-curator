from __future__ import annotations
from textual import work
from textual.screen import Screen
from textual.widgets import Footer, Header, Static
from .detect import detect


class WelcomeScreen(Screen):
    BINDINGS = [("enter", "continue", "Continue")]

    def compose(self):
        yield Header()
        yield Static("Scanning…", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._scan()

    @work(thread=True)
    def _scan(self) -> None:
        st = self.app.state
        if st.detection is None:
            st.detection = detect(st.cfg, st.home)
        d = st.detection
        lines = ["Welcome to Photo Curator.", "",
                 f"Ollama: {'running' if d.ollama_up else 'not running'}",
                 "Local vision models: "
                 + (", ".join(e.id.removeprefix("ollama/") for e in d.local_models)
                    or "none"),
                 "API keys found: " + (", ".join(d.env_keys) or "none"), "",
                 "Press Enter to choose a model."]
        if d.prior:
            lines.insert(-1, f"Last run: {d.prior.get('model_id')} on {d.prior.get('folder')}")
        self.app.call_from_thread(
            self.query_one("#status", Static).update, "\n".join(lines))

    def action_continue(self) -> None:
        from .screens_model import ModelPickerScreen
        self.app.push_screen(ModelPickerScreen())
