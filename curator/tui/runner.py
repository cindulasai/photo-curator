# curator/tui/runner.py
from __future__ import annotations
import argparse, threading
from dataclasses import dataclass, field
from pathlib import Path
from ..chat.deltas import apply_deltas
from ..chat.steering import SteeringQueue
from ..cli import run_pipeline
from ..model import ModelError, OllamaModel
from ..providers.catalog import ModelEntry


def factory_for(entry: ModelEntry, keystore):
    def make(cfg):
        if entry.source == "ollama" or entry.id.startswith("ollama/"):
            return OllamaModel(entry.id.removeprefix("ollama/"), cfg["ollama_url"],
                               cfg["llm"]["timeout_s"], cfg["llm"]["seed"],
                               cfg["llm"]["analyze_edge_px"])
        from ..providers.litellm_model import LiteLLMModel
        return LiteLLMModel(entry.id, keystore, cfg["llm"]["timeout_s"],
                            cfg["llm"]["seed"], cfg["llm"]["analyze_edge_px"])
    return make


@dataclass
class RunnerState:
    log: list[str] = field(default_factory=list)
    done: bool = False
    exit_code: int | None = None
    error: str | None = None


class _SteerProxy:
    """Callable passed to run_pipeline as `steer`. Exposes `attach_store` so
    cli.py can wire the DB store for delta persistence (spec §6.2). Also injects
    the cost-cap check before delegating to the underlying SteeringQueue."""

    def __init__(self, runner: "PipelineRunner"):
        self._runner = runner

    def attach_store(self, store) -> None:
        self._runner.steering.attach_store(store)

    def load_applied(self, cfg: dict) -> dict:
        return self._runner.steering.load_applied(cfg)

    def __call__(self, cfg: dict, idx: int) -> dict | None:
        r = self._runner
        if r.cost_cap is not None and r.cost_usd >= r.cost_cap:
            raise ModelError(f"cost cap ${r.cost_cap} reached at photo {idx} - "
                             "resume to continue")
        return r.steering(cfg, idx)


class PipelineRunner:
    def __init__(self, source: Path, out: Path, model_entry: ModelEntry, keystore,
                 cfg_deltas: list[dict], cost_cap: float | None = None,
                 model_factory=None, resume: bool = False,
                 skip_qualification: bool = False, fast: bool = False):
        self.out = Path(out)
        self.steering = SteeringQueue()
        self.state = RunnerState()
        self.model = None
        self.cost_cap = cost_cap
        self._deltas = cfg_deltas
        self._factory = model_factory or factory_for(model_entry, keystore)
        self._steer_proxy = _SteerProxy(self)
        self._args = argparse.Namespace(
            source=str(source), out=str(out), config=None, model=None,
            fast=fast, resume=resume, dry_run=False,
            skip_qualification=skip_qualification)

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def push(self, deltas: list[dict]) -> None:
        self.steering.push(deltas)

    @property
    def cost_usd(self) -> float:
        return getattr(self.model, "cost_usd", 0.0)

    def snapshot(self) -> dict:
        return {"log_tail": self.state.log[-8:], "cost_usd": round(self.cost_usd, 4),
                "done": self.state.done}

    # ---- internal ----
    def _notify(self, msg) -> None:
        self.state.log.append(str(msg))

    def _wrapped_factory(self, cfg):
        self.model = self._factory(cfg)
        return self.model

    def _run(self) -> None:
        try:
            if self._deltas:
                from ..config import load_config
                import yaml
                merged = apply_deltas(load_config(None), self._deltas)
                self.out.mkdir(parents=True, exist_ok=True)
                cfg_f = self.out / ".tui-config.yaml"
                cfg_f.write_text(yaml.safe_dump(merged))
                self._args.config = str(cfg_f)
            code = run_pipeline(self._args, model_factory=self._wrapped_factory,
                                steer=self._steer_proxy, notify=self._notify)
            self.state.exit_code = code
        except Exception as exc:                    # never kill the UI thread
            self.state.error = str(exc)
        finally:
            self.state.done = True
