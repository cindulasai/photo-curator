import json, socket, time, threading
import urllib.request
from pathlib import Path
from curator.review.server import ReviewServer, find_free_port, make_token


def _server(tmp_path):
    port = find_free_port()
    token = make_token()
    srv = ReviewServer(tmp_path, port, token)
    srv.start(open_browser=False)
    time.sleep(0.05)
    return srv, port, token


def test_token_required(tmp_path):
    srv, port, token = _server(tmp_path)
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            assert False, "should 403 without token"
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        srv.stop()


def test_index_with_token(tmp_path):
    # Create minimal static dir
    static = Path(__file__).parent.parent / "curator" / "review" / "static"
    srv, port, token = _server(tmp_path)
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/?token={token}")
        assert resp.status == 200
    finally:
        srv.stop()


def test_find_free_port():
    port = find_free_port()
    assert 1024 < port < 65536
    # verify it's actually free
    s = socket.socket()
    s.bind(("127.0.0.1", port))
    s.close()


def test_make_token_unique():
    assert make_token() != make_token()
    assert len(make_token()) == 32


import json as _json


def _api_server(tmp_path, img_factory):
    """Build a minimal curated dir with curation.db, run server."""
    from curator.db import Store
    src = tmp_path / "src"
    img_factory(src / "a.jpg", "scene", seed=1, exif_dt="2026:05:12 10:00:00")
    (tmp_path / "out").mkdir(parents=True, exist_ok=True)
    store = Store(tmp_path / "out" / "curation.db")
    store.upsert_photo("a.jpg", kind="photo", status="ok", stage_done=4,
                       sha256="abcd1234" * 8, size=100,
                       verdict="keep",
                       verdict_info={"bucket": "people"})
    store.close()
    port = find_free_port()
    token = make_token()
    srv = ReviewServer(tmp_path / "out", port, token)
    srv.start(open_browser=False)
    time.sleep(0.1)
    return srv, port, token, tmp_path / "out"


def _get(port, token, path):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"X-Review-Token": token})
    return urllib.request.urlopen(req)


def _post(port, token, path, body):
    data = _json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        headers={"X-Review-Token": token, "Content-Type": "application/json"},
        method="POST")
    return urllib.request.urlopen(req)


def test_api_state(tmp_path, img_factory):
    srv, port, token, out = _api_server(tmp_path, img_factory)
    try:
        resp = _get(port, token, "/api/state")
        state = _json.loads(resp.read())
        buckets = {b["key"]: b for b in state["buckets"]}
        assert "people" in buckets
        assert buckets["people"]["count"] == 1
    finally:
        srv.stop()


def test_api_action_moves_verdict(tmp_path, img_factory):
    srv, port, token, out = _api_server(tmp_path, img_factory)
    try:
        _post(port, token, "/api/action",
              {"photo": "a.jpg", "to": "top-pick"})
        from curator.db import Store
        store = Store(out / "curation.db")
        p = store.photo("a.jpg")
        store.close()
        assert p["verdict"] == "top-pick"
    finally:
        srv.stop()


def test_api_undo(tmp_path, img_factory):
    srv, port, token, out = _api_server(tmp_path, img_factory)
    try:
        _post(port, token, "/api/action", {"photo": "a.jpg", "to": "top-pick"})
        _post(port, token, "/api/undo", {})
        from curator.db import Store
        store = Store(out / "curation.db")
        p = store.photo("a.jpg")
        store.close()
        assert p["verdict"] == "keep"
    finally:
        srv.stop()
