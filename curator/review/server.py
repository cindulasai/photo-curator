from __future__ import annotations
import os, secrets, socket, threading, webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_STATIC = Path(__file__).parent / "static"


def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_token() -> str:
    return secrets.token_hex(16)


class _Handler(SimpleHTTPRequestHandler):
    _token: str
    _out_dir: Path
    _api_handler = None  # set after import to avoid circular
    _model_factory: object = None

    def log_message(self, *_):  # silence access log
        pass

    def _check_token(self) -> bool:
        qs = parse_qs(urlparse(self.path).query)
        cookie = self.headers.get("X-Review-Token", "")
        return self._token in (qs.get("token", [""])[0], cookie)

    def do_GET(self):
        if not self._check_token():
            self.send_error(403, "Missing or invalid token")
            return
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            if self._api_handler:
                self._api_handler.handle_get(self, path)
            else:
                self.send_error(501, "API not available")
            return
        if path == "/":
            path = "/index.html"
        # serve from static dir, then thumbs/photos from out_dir
        static_file = _STATIC / path.lstrip("/")
        if static_file.exists():
            self.path = path
            self.directory = str(_STATIC)
            return super().do_GET()
        # serve report-assets (thumbs) and library photos from out_dir
        out_file = self._out_dir / path.lstrip("/")
        if out_file.exists():
            self.path = path
            self.directory = str(self._out_dir)
            return super().do_GET()
        self.send_error(404)

    def do_POST(self):
        if not self._check_token():
            self.send_error(403, "Missing or invalid token")
            return
        path = urlparse(self.path).path
        if path.startswith("/api/") and self._api_handler:
            self._api_handler.handle_post(self, path)
        else:
            self.send_error(501, "API not available")


class ReviewServer:
    def __init__(self, out_dir: Path, port: int, token: str, model_factory=None):
        self.out_dir = Path(out_dir)
        self.port = port
        self.token = token
        self._model_factory = model_factory
        self._thread: threading.Thread | None = None
        self._httpd: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    def start(self, open_browser: bool = True) -> None:
        token, out_dir = self.token, self.out_dir
        model_factory = self._model_factory

        class H(_Handler):
            _token = token
            _out_dir = out_dir
            _model_factory = model_factory

        try:
            from .api import ApiHandler
            H._api_handler = ApiHandler(out_dir, token, model_factory=model_factory)
        except Exception:
            pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        if open_browser:
            webbrowser.open(self.url)

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
