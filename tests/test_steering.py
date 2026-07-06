import json, pytest
from curator.chat.deltas import DeltaError
from curator.chat.steering import SteeringQueue
from curator.config import load_config
from curator.db import Store


def test_drain_at_boundary(tmp_path):
    store = Store(tmp_path / "c.db")
    q = SteeringQueue(store)
    cfg = load_config(None)
    assert q(cfg, 0) is None                                  # empty -> None
    q.push([{"path": "triage.blur_sharp_min", "value": 80}])
    out = q(cfg, 3)
    assert out["triage"]["blur_sharp_min"] == 80
    assert q(out, 4) is None                                  # drained
    assert q.applied == [{"deltas": [{"path": "triage.blur_sharp_min", "op": "set",
                                      "value": 80, "why": ""}], "effective_from": 3}]
    assert json.loads(store.get_meta("user_deltas"))[0]["effective_from"] == 3


def test_push_validates():
    with pytest.raises(DeltaError):
        SteeringQueue().push([{"path": "llm.seed", "value": 1}])


def test_resume_reapplies(tmp_path):
    store = Store(tmp_path / "c.db")
    q1 = SteeringQueue(store)
    cfg = load_config(None)
    q1.push([{"path": "prompt_suffix", "value": "keep kids"}])
    cfg = q1(cfg, 5)
    q2 = SteeringQueue(store)                                 # fresh process
    resumed = q2.load_applied(load_config(None))
    assert resumed["prompt_suffix"] == ["keep kids"]
    assert q2.applied and q2.applied[0]["effective_from"] == 5
