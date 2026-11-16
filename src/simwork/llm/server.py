"""Minimal OpenAI-compatible fake server (stdlib only, no new dependency).

Exposes ``POST /v1/chat/completions`` backed by a `ScriptedLLM`, so an
unmodified harness can route to the mock with a base-URL swap
(``base_url=server.base_url``) — no harness code changes, per the spec.
Anything else returns 404; an exhausted script returns a visible 500
instead of falling back to a real provider.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from simwork.llm.scripted import ScriptedLLM, ScriptExhaustedError


class FakeOpenAIServer:
    """Serves a scripted LLM at ``{base_url}/v1/chat/completions``."""

    def __init__(
        self,
        script: list[dict],
        *,
        seed: int = 0,
        model: str = "simwork-mock",
        host: str = "127.0.0.1",
        port: int = 0,
    ):
        self.llm = ScriptedLLM(script, seed=seed, model=model)
        self.host = host
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"

    def start(self) -> "FakeOpenAIServer":
        if self._httpd is not None:
            return self
        handler = _make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._httpd.llm = self.llm  # type: ignore[attr-defined]
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> "FakeOpenAIServer":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def _make_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self._send_json(404, {"error": {"message": f"unknown path: {self.path}"}})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                completion = self.server.llm.complete(payload.get("messages", []))  # type: ignore[attr-defined]
            except ScriptExhaustedError as e:
                self._send_json(500, {"error": {"message": str(e)}})
                return
            except (ValueError, KeyError) as e:
                self._send_json(400, {"error": {"message": f"invalid request: {e}"}})
                return
            self._send_json(200, completion)

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    return Handler
