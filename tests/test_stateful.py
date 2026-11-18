"""Tests for the stateful stub layer (Phase 2, task 2).

Prism alone is stateless, so SimWork adds a state layer: a small proxy in
front of the upstream mock that remembers what was written so a later
read returns it (create-then-read). All tests are hermetic: the upstream
is a fake stdlib HTTP server, never Prism or a real API.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from simwork.stateful import StatefulStore, StatefulStubServer


# --- StatefulStore (pure, no HTTP) -----------------------------------------


def test_create_assigns_sequential_id_when_missing() -> None:
    store = StatefulStore()
    first = store.create("/widgets", {"name": "a"})
    second = store.create("/widgets", {"name": "b"})
    assert first["id"] == "1"
    assert second["id"] == "2"
    assert first["name"] == "a"


def test_create_keeps_a_client_supplied_id() -> None:
    store = StatefulStore()
    record = store.create("/widgets", {"id": "w-9", "name": "a"})
    assert record["id"] == "w-9"
    assert store.get("/widgets", "w-9") == record


def test_create_does_not_mutate_the_caller_body() -> None:
    store = StatefulStore()
    body = {"name": "a"}
    store.create("/widgets", body)
    assert body == {"name": "a"}


def test_list_returns_created_records_in_order() -> None:
    store = StatefulStore()
    store.create("/widgets", {"name": "a"})
    store.create("/widgets", {"name": "b"})
    assert [r["name"] for r in store.list("/widgets")] == ["a", "b"]


def test_collections_are_isolated() -> None:
    store = StatefulStore()
    store.create("/widgets", {"name": "a"})
    assert store.list("/gadgets") == []
    assert store.get("/gadgets", "1") is None


def test_get_unknown_id_returns_none() -> None:
    store = StatefulStore()
    store.create("/widgets", {"name": "a"})
    assert store.get("/widgets", "99") is None


def test_update_replaces_and_patch_merges() -> None:
    store = StatefulStore()
    store.create("/widgets", {"name": "a", "size": 1})
    replaced = store.update("/widgets", "1", {"name": "b"}, partial=False)
    assert replaced == {"id": "1", "name": "b"}
    patched = store.update("/widgets", "1", {"size": 2}, partial=True)
    assert patched == {"id": "1", "name": "b", "size": 2}
    assert store.update("/widgets", "99", {"name": "x"}, partial=True) is None


def test_delete_removes_and_reports() -> None:
    store = StatefulStore()
    store.create("/widgets", {"name": "a"})
    assert store.delete("/widgets", "1") is True
    assert store.delete("/widgets", "1") is False
    assert store.list("/widgets") == []


def test_has_collection_only_after_a_write() -> None:
    store = StatefulStore()
    assert store.has_collection("/widgets") is False
    store.create("/widgets", {"name": "a"})
    assert store.has_collection("/widgets") is True


# --- StatefulStubServer (HTTP proxy over a fake upstream) -------------------


class _UpstreamHandler(BaseHTTPRequestHandler):
    """Fake upstream mock: records requests, answers with canned JSON."""

    seen: list[dict] = []

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        _UpstreamHandler.seen.append({"method": self.command, "path": self.path, "body": body})
        payload = json.dumps({"upstream": True, "method": self.command, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle

    def log_message(self, *args: object) -> None:
        pass


def _start_upstream() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture()
def proxy():
    _UpstreamHandler.seen = []
    upstream, upstream_url = _start_upstream()
    server = StatefulStubServer(upstream_url, host="127.0.0.1", port=0)
    server.start()
    yield server
    server.stop()
    upstream.shutdown()
    upstream.server_close()


def _request(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def test_create_then_read_list_returns_the_created_record(proxy) -> None:
    status, created = _request(proxy.base_url, "POST", "/widgets", {"name": "a"})
    assert status == 201
    assert created["name"] == "a" and created["id"] == "1"
    status, listed = _request(proxy.base_url, "GET", "/widgets")
    assert status == 200
    assert listed == [created]


def test_create_then_read_by_id(proxy) -> None:
    _request(proxy.base_url, "POST", "/widgets", {"name": "a"})
    status, record = _request(proxy.base_url, "GET", "/widgets/1")
    assert status == 200
    assert record == {"id": "1", "name": "a"}


def test_get_unknown_id_in_a_stored_collection_is_404(proxy) -> None:
    _request(proxy.base_url, "POST", "/widgets", {"name": "a"})
    status, body = _request(proxy.base_url, "GET", "/widgets/99")
    assert status == 404
    assert body["error"] == "not found"


def test_reads_with_no_stored_records_forward_to_upstream(proxy) -> None:
    status, body = _request(proxy.base_url, "GET", "/widgets")
    assert status == 200
    assert body["upstream"] is True
    assert _UpstreamHandler.seen[0]["path"] == "/widgets"


def test_put_and_patch_update_the_stored_record(proxy) -> None:
    _request(proxy.base_url, "POST", "/widgets", {"name": "a", "size": 1})
    status, record = _request(proxy.base_url, "PUT", "/widgets/1", {"name": "b"})
    assert status == 200
    assert record == {"id": "1", "name": "b"}
    status, record = _request(proxy.base_url, "PATCH", "/widgets/1", {"size": 2})
    assert status == 200
    assert record == {"id": "1", "name": "b", "size": 2}


def test_delete_removes_the_record_then_read_is_404(proxy) -> None:
    _request(proxy.base_url, "POST", "/widgets", {"name": "a"})
    status, _ = _request(proxy.base_url, "DELETE", "/widgets/1")
    assert status == 204
    status, _ = _request(proxy.base_url, "GET", "/widgets/1")
    assert status == 404
    status, listed = _request(proxy.base_url, "GET", "/widgets")
    assert listed == []


def test_non_json_post_forwards_to_upstream(proxy) -> None:
    req = urllib.request.Request(
        proxy.base_url + "/widgets",
        data=b"not json",
        method="POST",
        headers={"Content-Type": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        assert json.loads(resp.read())["upstream"] is True
    assert _UpstreamHandler.seen[0]["body"] == b"not json"


def test_upstream_status_and_body_pass_through(proxy) -> None:
    # A path the stub layer never intercepts is served by the upstream as-is.
    status, body = _request(proxy.base_url, "GET", "/status/201")
    assert status == 200
    assert body["upstream"] is True
    assert body["path"] == "/status/201"


# --- CLI wiring: `simwork mock --stateful` ----------------------------------


class _FakePrism:
    instances: list["_FakePrism"] = []

    def __init__(self, spec_path, *, host="127.0.0.1", port=0):
        self.spec_path = spec_path
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port or 9999}"
        self.started = False
        self.stopped = False
        _FakePrism.instances.append(self)

    def start(self):
        self.started = True
        return self

    def stop(self):
        self.stopped = True


class _FakeProxy:
    instances: list["_FakeProxy"] = []

    def __init__(self, upstream_base_url, *, host="127.0.0.1", port=0):
        self.upstream_base_url = upstream_base_url
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port or 8888}"
        self.started = False
        self.stopped = False
        _FakeProxy.instances.append(self)

    def start(self):
        self.started = True
        return self

    def stop(self):
        self.stopped = True


class _ImmediateCtrlC:
    def wait(self):
        raise KeyboardInterrupt


@pytest.fixture()
def _mocked_servers(monkeypatch):
    _FakePrism.instances = []
    _FakeProxy.instances = []
    # The stack assembles these in simwork.api_mock now (candidate 3),
    # so the patch points live there, not in simwork.cli.
    monkeypatch.setattr(
        "simwork.api_mock.fetch_api_spec", lambda api, cache_dir: "/cache/spec.json"
    )
    monkeypatch.setattr("simwork.api_mock.PrismMockServer", _FakePrism)
    monkeypatch.setattr("simwork.api_mock.StatefulStubServer", _FakeProxy)
    monkeypatch.setattr("simwork.serving.threading.Event", lambda: _ImmediateCtrlC())
    return _FakePrism, _FakeProxy


def test_mock_stateful_flag_parses() -> None:
    from simwork.cli import build_parser

    args = build_parser().parse_args(["mock", "--api", "example.com", "--stateful"])
    assert args.stateful is True
    args = build_parser().parse_args(["mock", "--api", "example.com"])
    assert args.stateful is False


def test_mock_stateful_wires_proxy_in_front_of_prism(_mocked_servers, tmp_path, capsys) -> None:
    from simwork.cli import main

    rc = main(
        [
            "mock",
            "--api",
            "example.com",
            "--stateful",
            "--port",
            "8124",
            "--cache-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    prism, proxy = _FakePrism.instances[0], _FakeProxy.instances[0]
    assert prism.port == 0  # Prism takes an ephemeral port behind the proxy
    assert proxy.upstream_base_url == prism.base_url
    assert proxy.port == 8124
    assert prism.started and proxy.started
    assert prism.stopped and proxy.stopped
    out = capsys.readouterr().out
    assert "Stateful stubs on" in out
    assert "API_BASE_URL=http://127.0.0.1:8124" in out


def test_mock_without_stateful_starts_prism_only(_mocked_servers, tmp_path) -> None:
    from simwork.cli import main

    rc = main(["mock", "--api", "example.com", "--port", "8124", "--cache-dir", str(tmp_path)])
    assert rc == 0
    assert len(_FakePrism.instances) == 1
    assert _FakePrism.instances[0].port == 8124
    assert _FakeProxy.instances == []
