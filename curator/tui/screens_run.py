# curator/tui/screens_run.py
from __future__ import annotations
from datetime import date
from pathlib import Path
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Log, Static
from ..chat.deltas import describe
from ..chat.intent import parse_intent
from ..config import load_config
from ..db import Store
from .runner import PipelineRunner, factory_for

try:
    from ..review.server import ReviewServer, find_free_port, make_token
except ImportError:  # pragma: no cover
    ReviewServer = None  # type: ignore[assignment,misc]
    find_free_port = None  # type: ignore[assignment]
    make_token = None  # type: ignore[assignment]


class RunScreen(Screen):
    BINDINGS = [("c", "cancel", "Cancel (resumable)")]

    def compose(self):
        yield Header()
        yield Static("Starting…", id="status")
        yield Log(id="runlog")
        yield Input(placeholder="talk to the curator while it works…", id="chat")
        yield Footer()

    def on_mount(self) -> None:
        st = self.app.state
        out = st.folder.parent / f"curated-{date.today().isoformat()}"
        self.runner = PipelineRunner(
            source=st.folder, out=out, model_entry=st.model_entry,
            keystore=st.keystore, cfg_deltas=st.deltas, cost_cap=st.cost_cap,
            model_factory=self.app.model_factory)
        self._shown = 0
        self._pushed = False
        self.runner.start()
        self.set_interval(0.3, self._refresh)

    def _refresh(self) -> None:
        log = self.query_one("#runlog", Log)
        while self._shown < len(self.runner.state.log):
            log.write_line(self.runner.state.log[self._shown])
            self._shown += 1
        s = self.runner.state
        cost = f" · ${self.runner.cost_usd:.2f}" if self.runner.cost_usd else ""
        self.query_one("#status", Static).update(
            ("done" if s.done else "curating…") + cost)
        if s.done and not self._pushed:
            self._pushed = True
            self.app.push_screen(ResultsScreen(self.runner))

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        text = ev.value.strip()
        ev.input.value = ""
        if text:
            self.run_worker(lambda: self._chat(text), thread=True)

    def _chat(self, text: str) -> None:
        try:
            factory = self.app.model_factory or factory_for(
                self.app.state.model_entry, self.app.state.keystore)
            model = factory(self.app.state.cfg)
            out = parse_intent(model, self.app.state.cfg, text,
                               run_state=self.runner.snapshot())
            log = self.query_one("#runlog", Log)
            if out["deltas"] and not self.runner.state.done:
                self.runner.push(out["deltas"])
                for line in describe(out["deltas"]):
                    self.app.call_from_thread(
                        log.write_line, f"↪ applied from next photo: {line}")
            self.app.call_from_thread(log.write_line, f"curator: {out['reply']}")
        except Exception as e:
            log = self.query_one("#runlog", Log)
            self.app.call_from_thread(log.write_line,
                                      f"curator: something went wrong — {e}")

    def action_cancel(self) -> None:
        self.runner.stop()
        self.app.pop_screen()


class ResultsScreen(Screen):
    BINDINGS = [("o", "open_folder", "Open output"),
                ("r", "review", "Review in browser")]

    def __init__(self, runner: PipelineRunner):
        super().__init__()
        self.runner = runner

    def compose(self):
        yield Header()
        yield Static(id="summary")
        yield Log(id="qalog")
        yield Input(placeholder="ask me anything about this run…", id="qa")
        yield Footer()

    def on_mount(self) -> None:
        s = self.runner.state
        tail = "\n".join(s.log[-6:])
        head = ("Curation complete." if s.exit_code == 0
                else f"Run stopped (code {s.exit_code}): {s.error or ''}")
        self.query_one("#summary", Static).update(
            f"{head}\n\n{tail}\n\nOutput: {self.runner.out}")

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        q = ev.value.strip()
        ev.input.value = ""
        if q:
            self.run_worker(lambda: self._answer(q), thread=True)

    def _answer(self, q: str) -> None:
        try:
            from ..chat.qa import answer
            factory = self.app.model_factory or factory_for(
                self.app.state.model_entry, self.app.state.keystore)
            model = factory(self.app.state.cfg)
            store = Store(self.runner.out / "curation.db")
            try:
                reply = answer(model, store, self.app.state.cfg, q)
            finally:
                store.close()
            log = self.query_one("#qalog", Log)
            self.app.call_from_thread(log.write_line, f"you: {q}")
            self.app.call_from_thread(log.write_line, f"curator: {reply}")
        except Exception as e:
            log = self.query_one("#qalog", Log)
            self.app.call_from_thread(log.write_line,
                                      f"curator: something went wrong — {e}")

    def action_open_folder(self) -> None:
        import webbrowser
        webbrowser.open(self.runner.out.as_uri())

    def action_review(self) -> None:
        if ReviewServer is None:
            self.notify("Install photo-curator[app] for review gallery")
            return
        port = find_free_port()
        token = make_token()
        _factory = self.app.model_factory
        _cfg = self.app.state.cfg if self.app.state else {}
        model_factory = (lambda: _factory(_cfg)) if _factory else None
        srv = ReviewServer(self.runner.out, port, token, model_factory=model_factory)
        srv.start(open_browser=True)
        self.notify(f"Review gallery: {srv.url}")
        self.run_worker(lambda: self._memory_session(srv), thread=True)

    def _memory_session(self, srv) -> None:
        try:
            srv._thread.join(timeout=3600)
        except Exception:
            pass
        finally:
            srv.stop()
        try:
            from ..review.corrections import load_corrections
            from ..chat.memory import propose_memories
            corrections = load_corrections()
            if not corrections or not self.app.model_factory:
                return
            cfg = self.app.state.cfg if self.app.state else {}
            factory = self.app.model_factory
            model = factory(cfg)
            proposals = propose_memories(corrections, model, cfg)
            if proposals:
                self.app.call_from_thread(self._show_proposals, proposals)
        except Exception:
            pass

    def _show_proposals(self, proposals: list) -> None:
        from ..chat.memory import confirm_proposal
        for p in proposals:
            self.notify(f"Memory: {p['statement'][:80]}… (auto-confirmed)", timeout=8)
            confirm_proposal(p)
