from __future__ import annotations
import json
from pathlib import Path
from ..db import Store
from .corrections import append_correction

_BUCKET_LABELS = {
    "top-picks": "Top Picks", "needs-review": "Needs Review",
    "people": "People", "celebrations": "Celebrations",
    "kids-family": "Kids & Family", "travel": "Travel",
    "nature-outdoors": "Nature & Outdoors", "urban-architecture": "Urban",
    "events-performances": "Events", "food-drink": "Food & Drink",
    "pets-animals": "Pets & Animals", "hobbies-activities": "Hobbies",
    "vehicles": "Vehicles", "screenshots": "Screenshots",
    "documents-receipts": "Documents", "whiteboards-notes": "Notes",
    "products-shopping": "Products", "everyday-misc": "Misc",
    "blurry": "Rejected: Blurry", "accidental": "Rejected: Accidental",
    "corrupt": "Rejected: Corrupt",
}


class ApiHandler:
    def __init__(self, out_dir: Path, token: str, model_factory=None):
        self._out = Path(out_dir)
        self._token = token
        self._model_factory = model_factory
        self._undo_stack: list[dict] = []  # [{photo, from_verdict, from_vi}]

    def _store(self) -> Store:
        return Store(self._out / "curation.db")

    def _read_body(self, handler) -> dict:
        length = int(handler.headers.get("Content-Length", 0))
        body = handler.rfile.read(length) if length else b"{}"
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    def _send_json(self, handler, data: dict, code: int = 200):
        body = json.dumps(data).encode()
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", len(body))
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        handler.wfile.write(body)

    def handle_get(self, handler, path: str):
        if path == "/api/state":
            self._send_json(handler, self._state())
        else:
            handler.send_error(404)

    def handle_post(self, handler, path: str):
        body = self._read_body(handler)
        if path == "/api/action":
            self._send_json(handler, self._action(body))
        elif path == "/api/undo":
            self._send_json(handler, self._undo())
        elif path == "/api/chat":
            self._send_json(handler, self._chat(body))
        else:
            handler.send_error(404)

    def _state(self) -> dict:
        store = self._store()
        try:
            photos = store.photos()
            run_id = store.get_meta("run_id") or ""
        finally:
            store.close()
        buckets: dict[str, list] = {}
        needs_review_count = 0
        for p in photos:
            vi = p.get("verdict_info") or {}
            verdict = p.get("verdict") or "unknown"
            if verdict == "top-pick":
                key = "top-picks"
            elif verdict == "keep":
                key = vi.get("bucket", "everyday-misc")
            elif verdict == "needs-review":
                key = "needs-review"
                needs_review_count += 1
            elif verdict == "reject":
                key = "blurry"
            elif verdict == "duplicate-inferior":
                key = "duplicates"
            else:
                key = "unknown"
            sha = p.get("sha256") or ""
            entry = {
                "rel_path": p["rel_path"], "sha256": sha, "verdict": verdict,
                "bucket": key,
                "thumb": f"/report-assets/thumbs/{sha[:2]}/{sha}.jpg" if sha else "",
                "placed": "",
            }
            buckets.setdefault(key, []).append(entry)
        out = []
        for key, photos_list in sorted(buckets.items()):
            out.append({"key": key,
                        "label": _BUCKET_LABELS.get(key, key.replace("-", " ").title()),
                        "count": len(photos_list),
                        "photos": photos_list})
        return {"buckets": out, "needs_review_count": needs_review_count,
                "run_id": run_id}

    def _action(self, body: dict) -> dict:
        photo = body.get("photo", "")
        to = body.get("to", "")
        if not photo or not to:
            return {"ok": False, "error": "missing photo or to"}
        store = self._store()
        try:
            p = store.photo(photo)
            if not p:
                return {"ok": False, "error": "photo not found"}
            old_verdict = p.get("verdict")
            old_vi = p.get("verdict_info") or {}
            # Map 'to' to verdict + verdict_info
            if to == "top-pick":
                new_verdict = "top-pick"
                new_vi = dict(old_vi) | {"user_override": True}
            elif to == "reject":
                new_verdict = "reject"
                new_vi = {"reason": "user-rejected", "user_override": True}
            elif to.startswith("bucket/"):
                new_verdict = "keep"
                new_vi = dict(old_vi) | {"bucket": to[len("bucket/"):], "user_override": True}
            else:
                return {"ok": False, "error": f"unknown destination: {to}"}
            store.update(photo, verdict=new_verdict, verdict_info=new_vi)
            self._undo_stack.append({"photo": photo, "from_verdict": old_verdict,
                                     "from_vi": old_vi})
            if len(self._undo_stack) > 50:
                self._undo_stack.pop(0)
        finally:
            store.close()
        append_correction({
            "kind": "action", "photo": photo,
            "pipeline_said": {"verdict": old_verdict},
            "user_said": {"verdict": new_verdict},
        })
        return {"ok": True}

    def _undo(self) -> dict:
        if not self._undo_stack:
            return {"ok": False, "error": "nothing to undo"}
        last = self._undo_stack.pop()
        store = self._store()
        try:
            store.update(last["photo"], verdict=last["from_verdict"],
                         verdict_info=last["from_vi"])
        finally:
            store.close()
        return {"ok": True}

    def _chat(self, body: dict) -> dict:
        message = body.get("message", "").strip()
        if not message:
            return {"reply": ""}
        if self._model_factory is None:
            return {"reply": "Chat requires a configured model. Start the review from inside the app to enable chat."}
        try:
            from ..chat.qa import answer
            from ..config import load_config
            model = self._model_factory()
            cfg = load_config(None)
            store = self._store()
            try:
                reply = answer(model, store, cfg, message)
            finally:
                store.close()
            return {"reply": reply}
        except Exception as e:
            return {"reply": f"Sorry, I couldn't answer that: {e}"}
