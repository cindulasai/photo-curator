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
