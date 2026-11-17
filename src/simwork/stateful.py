"""Stateful stub layer for API mocks (Phase 2, task 2).

Prism alone is stateless: a POST it answers is forgotten by the next GET.
This module adds the state layer the spec requires — a small stdlib HTTP
proxy that sits in front of the upstream mock (Prism) and remembers what
was written, so create-then-read returns the created record.

Rules (deliberately generic, no per-API config):

- ``POST <collection>`` with a JSON-object body stores the record and
  answers ``201`` with it. A missing ``id`` is assigned deterministically
  (``"1"``, ``"2"``, ... per collection, in write order).
- ``GET <collection>`` answers with the stored list once anything was
  written there; otherwise the request forwards to the upstream mock.
- ``GET <collection>/<id>`` answers from the store once the collection
  has stored records (unknown id -> ``404``); otherwise it forwards.
- ``PUT`` replaces / ``PATCH`` merges a stored record; ``DELETE`` removes
  it (``204``). Unknown ids in a stored collection are ``404``.
- Anything else — non-JSON bodies, paths with no stored records, query
  strings, other methods — forwards to the upstream mock unchanged, so
  Prism's example/schema behaviour is preserved.

The store is in-memory and per-process: restarting the mock resets the
world, which is the right default for a deterministic simulation (same
seed + same request sequence = same ids). Nothing here ever contacts a
real API; the proxy only talks to the upstream mock on localhost.
"""

from __future__ import annotations

import http.client
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


class StatefulStore:
    """In-memory record store, keyed by collection path then record id."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, dict]] = {}
        self._counters: dict[str, int] = {}
        # Collections ever written to, even if later emptied by DELETEs:
        # reads on them stay in the store (empty list / 404), never fall
        # through to the upstream mock's example data.
        self._seen: set[str] = set()

    def create(self, collection: str, body: dict) -> dict:
        """Store a copy of ``body``; assign a sequential id if it has none."""
        record = dict(body)
        if "id" not in record:
            self._counters[collection] = self._counters.get(collection, 0) + 1
            record["id"] = str(self._counters[collection])
        self._seen.add(collection)
        self._records.setdefault(collection, {})[str(record["id"])] = record
        return dict(record)

    def list(self, collection: str) -> list[dict]:
        return [dict(r) for r in self._records.get(collection, {}).values()]

    def get(self, collection: str, record_id: str) -> dict | None:
        record = self._records.get(collection, {}).get(record_id)
        return dict(record) if record is not None else None

    def update(self, collection: str, record_id: str, body: dict, *, partial: bool) -> dict | None:
        """Replace (PUT) or merge (PATCH) a stored record; None if unknown."""
        records = self._records.get(collection, {})
        if record_id not in records:
            return None
        record = dict(records[record_id]) if partial else {"id": record_id}
        record.update(body)
        record["id"] = record_id
        records[record_id] = record
        return dict(record)

    def delete(self, collection: str, record_id: str) -> bool:
        records = self._records.get(collection, {})
        return records.pop(record_id, None) is not None

    def has_collection(self, collection: str) -> bool:
        return collection in self._seen


def _split_item(path: str) -> tuple[str, str] | None:
    """Split ``/collection/<id>`` into ``(collection, id)``; None if no id."""
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return None
    return "/" + "/".join(parts[:-1]), parts[-1]


def _make_handler(store: StatefulStore, upstream: urllib.parse.ParseResult):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            pass

        # -- helpers ------------------------------------------------------
        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length else b""

        def _send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _forward(self, body: bytes) -> None:
            conn = http.client.HTTPConnection(upstream.hostname, upstream.port)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP_BY_HOP}
            conn.request(self.command, self.path, body=body or None, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status)
            for key, value in resp.getheaders():
                if key.lower() not in _HOP_BY_HOP:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            conn.close()

        def _handle(self) -> None:
            body = self._read_body()
            path = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
            method = self.command

            if method == "POST":
                record = self._try_store(path, body)
                if record is not None:
                    self._send_json(201, record)
                    return
                self._forward(body)
                return

            if method == "GET":
                if store.has_collection(path):
                    self._send_json(200, store.list(path))
                    return
                item = _split_item(path)
                if item is not None and store.has_collection(item[0]):
                    record = store.get(item[0], item[1])
                    if record is None:
                        self._send_json(404, {"error": "not found"})
                    else:
                        self._send_json(200, record)
                    return
                self._forward(body)
                return

            if method in ("PUT", "PATCH"):
                item = _split_item(path)
                if item is not None and store.has_collection(item[0]):
                    if store.get(item[0], item[1]) is None:
                        self._send_json(404, {"error": "not found"})
                    else:
                        record = self._try_update(item, body, partial=method == "PATCH")
                        if record is None:
                            # Non-JSON body on a known record: let the
                            # upstream mock decide instead of guessing.
                            self._forward(body)
                        else:
                            self._send_json(200, record)
                    return
                self._forward(body)
                return

            if method == "DELETE":
                item = _split_item(path)
                if item is not None and store.has_collection(item[0]):
                    if store.delete(item[0], item[1]):
                        self.send_response(204)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    else:
                        self._send_json(404, {"error": "not found"})
                    return
                self._forward(body)
                return

            self._forward(body)

        def _try_store(self, path: str, body: bytes) -> dict | None:
            """Store a JSON-object POST body; None means "not interceptable"."""
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                return None
            try:
                parsed = json.loads(body or b"null")
            except ValueError:
                return None
            if not isinstance(parsed, dict):
                return None
            return store.create(path, parsed)

        def _try_update(self, item: tuple[str, str], body: bytes, *, partial: bool) -> dict | None:
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                return None
            try:
                parsed = json.loads(body or b"null")
            except ValueError:
                return None
            if not isinstance(parsed, dict):
                return None
            return store.update(item[0], item[1], parsed, partial=partial)

        do_GET = _handle
        do_POST = _handle
        do_PUT = _handle
        do_PATCH = _handle
        do_DELETE = _handle

    return Handler


class StatefulStubServer:
    """HTTP proxy in front of an upstream mock, adding create-then-read state.

    ``upstream_base_url`` is the mock to forward to (e.g. a
    `PrismMockServer`'s ``base_url``). The proxy binds its own port; point
    the harness at the proxy's ``base_url``.
    """

    def __init__(
        self,
        upstream_base_url: str,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        store: StatefulStore | None = None,
    ):
        self.upstream = urllib.parse.urlsplit(upstream_base_url)
        self.host = host
        self.port = port
        self.store = store or StatefulStore()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> "StatefulStubServer":
        if self._server is not None:
            return self
        handler = _make_handler(self.store, self.upstream)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None

    def __enter__(self) -> "StatefulStubServer":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
