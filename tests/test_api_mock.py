"""Tests for the API mock layer (Phase 2, task 1): APIs.guru fetch + Prism serve.

All tests are hermetic: network and the `prism` subprocess are faked.
The live end-to-end check (real APIs.guru + real Prism) is done manually
per run, not in CI, so the suite stays green offline.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error

import pytest

from simwork.api_mock import (
    ApiMockError,
    ApiMockStack,
    PrismMockServer,
    fetch_api_spec,
    resolve_api_spec_url,
)
from simwork.cli import main
from simwork.stateful import StatefulStubServer

LIST_FIXTURE = {
    "example.com": {
        "preferred": "1.0.0",
        "versions": {
            "1.0.0": {
                "swaggerUrl": "https://api.apis.guru/v2/specs/example.com/1.0.0/openapi.json",
                "info": {"title": "Example API", "version": "1.0.0"},
            },
            "0.9.0": {
                "swaggerUrl": "https://api.apis.guru/v2/specs/example.com/0.9.0/openapi.json",
                "info": {"title": "Example API", "version": "0.9.0"},
            },
        },
    },
    "other.com": {
        "preferred": "2.0.0",
        "versions": {
            "2.0.0": {
                "swaggerUrl": "https://api.apis.guru/v2/specs/other.com/2.0.0/openapi.json",
                "info": {"title": "Other API", "version": "2.0.0"},
            },
        },
    },
}

SPEC_FIXTURE = {
    "openapi": "3.0.0",
    "info": {"title": "Example API", "version": "1.0.0"},
    "paths": {
        "/widgets": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {"id": {"type": "integer"}},
                                    },
                                }
                            }
                        },
                    }
                }
            }
        }
    },
}


class _FakeResponse:
    """Minimal urlopen stand-in returning pre-encoded JSON bytes."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _fake_urlopen_factory(calls: list, responses: dict):
    def fake_urlopen(url, timeout=None):
        url = url.full_url if isinstance(url, urllib.request.Request) else url
        calls.append(url)
        if url in responses:
            return _FakeResponse(responses[url])
        raise urllib.error.HTTPError(url, 404, "not found", None, None)

    return fake_urlopen


# --- spec resolution -------------------------------------------------------


def test_resolve_known_api_returns_preferred_spec_url():
    url, title, version = resolve_api_spec_url("example.com", LIST_FIXTURE)
    assert url == "https://api.apis.guru/v2/specs/example.com/1.0.0/openapi.json"
    assert title == "Example API"
    assert version == "1.0.0"


def test_resolve_unknown_api_fails_closed_with_name():
    with pytest.raises(ApiMockError, match="nope.example"):
        resolve_api_spec_url("nope.example", LIST_FIXTURE)


def test_resolve_entry_without_preferred_version_fails_closed():
    broken = {"broken.com": {"versions": {}}}
    with pytest.raises(ApiMockError, match="broken.com"):
        resolve_api_spec_url("broken.com", broken)


# --- spec fetching + caching -----------------------------------------------


def test_fetch_api_spec_downloads_list_then_spec_and_caches(tmp_path):
    calls: list[str] = []
    fake = _fake_urlopen_factory(
        calls,
        {
            "https://api.apis.guru/v2/list.json": LIST_FIXTURE,
            "https://api.apis.guru/v2/specs/example.com/1.0.0/openapi.json": SPEC_FIXTURE,
        },
    )
    path = fetch_api_spec("example.com", tmp_path, urlopen=fake)
    assert path.exists()
    assert json.loads(path.read_text()) == SPEC_FIXTURE
    assert calls[0] == "https://api.apis.guru/v2/list.json"
    assert calls[1] == "https://api.apis.guru/v2/specs/example.com/1.0.0/openapi.json"


def test_fetch_api_spec_second_call_uses_cache_only(tmp_path):
    calls: list[str] = []
    fake = _fake_urlopen_factory(
        calls,
        {
            "https://api.apis.guru/v2/list.json": LIST_FIXTURE,
            "https://api.apis.guru/v2/specs/example.com/1.0.0/openapi.json": SPEC_FIXTURE,
        },
    )
    fetch_api_spec("example.com", tmp_path, urlopen=fake)
    calls.clear()
    path = fetch_api_spec("example.com", tmp_path, urlopen=fake)
    assert calls == []  # list + spec both served from cache
    assert json.loads(path.read_text()) == SPEC_FIXTURE


def test_fetch_api_spec_http_error_fails_closed(tmp_path):
    def boom(url, timeout=None):
        raise urllib.error.URLError("network down")
    with pytest.raises(ApiMockError, match="could not download"):
        fetch_api_spec("example.com", tmp_path, urlopen=boom)
    # Nothing half-written left behind.
    assert not list(tmp_path.rglob("*.json"))


def test_fetch_unknown_api_fails_closed_without_downloading_spec(tmp_path):
    calls: list[str] = []
    fake = _fake_urlopen_factory(calls, {"https://api.apis.guru/v2/list.json": LIST_FIXTURE})
    with pytest.raises(ApiMockError, match="nope.example"):
        fetch_api_spec("nope.example", tmp_path, urlopen=fake)
    assert calls == ["https://api.apis.guru/v2/list.json"]


# --- Prism server wrapper --------------------------------------------------


class _FakePopen:
    """Stand-in for subprocess.Popen capturing argv; stays 'running'."""

    instances: list["_FakePopen"] = []

    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.terminated = False
        _FakePopen.instances.append(self)

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    @property
    def stderr(self):
        return None


class _FakeHTTPResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"{}"


@pytest.fixture(autouse=True)
def _reset_fake_popen():
    _FakePopen.instances.clear()
    yield
    _FakePopen.instances.clear()


def _write_spec(tmp_path) -> str:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(SPEC_FIXTURE), encoding="utf-8")
    return str(path)


def test_prism_server_spawns_prism_mock_with_spec_and_port(tmp_path, monkeypatch):
    monkeypatch.setattr("simwork.api_mock.shutil.which", lambda name: "/usr/bin/prism")
    monkeypatch.setattr("simwork.api_mock.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(
        "simwork.api_mock.urllib.request.urlopen",
        lambda *a, **k: _FakeHTTPResponse(),
    )
    spec = _write_spec(tmp_path)
    server = PrismMockServer(spec, port=18771)
    with server:
        assert server.base_url == "http://127.0.0.1:18771"
        assert len(_FakePopen.instances) == 1
        argv = _FakePopen.instances[0].argv
        assert argv[0] == "/usr/bin/prism"
        assert argv[1] == "mock"
        assert argv[2] == spec
        assert "--host" in argv and "127.0.0.1" in argv
        assert "--port" in argv and "18771" in argv
    assert _FakePopen.instances[0].terminated


def test_prism_server_missing_binary_fails_closed_with_install_hint(tmp_path, monkeypatch):
    monkeypatch.setattr("simwork.api_mock.shutil.which", lambda name: None)
    server = PrismMockServer(_write_spec(tmp_path))
    with pytest.raises(ApiMockError, match="prism"):
        server.start()


def test_prism_server_missing_binary_message_names_install(tmp_path, monkeypatch):
    monkeypatch.setattr("simwork.api_mock.shutil.which", lambda name: None)
    with pytest.raises(ApiMockError) as excinfo:
        PrismMockServer(_write_spec(tmp_path)).start()
    assert "npm i -g @stoplight/prism-cli" in str(excinfo.value)


def test_prism_server_invalid_spec_fails_closed_before_spawn(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"info": {"title": "no openapi key"}}), encoding="utf-8")
    monkeypatch.setattr("simwork.api_mock.shutil.which", lambda name: "/usr/bin/prism")
    monkeypatch.setattr("simwork.api_mock.subprocess.Popen", _FakePopen)
    with pytest.raises(ApiMockError, match="not a valid OpenAPI"):
        PrismMockServer(str(bad)).start()
    assert _FakePopen.instances == []


def test_prism_server_http_error_counts_as_ready(tmp_path, monkeypatch):
    """Prism 404s the unknown root path — an HTTP response still means ready."""
    monkeypatch.setattr("simwork.api_mock.shutil.which", lambda name: "/usr/bin/prism")
    monkeypatch.setattr("simwork.api_mock.subprocess.Popen", _FakePopen)

    def _raise_404(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "not found", None, None)

    monkeypatch.setattr("simwork.api_mock.urllib.request.urlopen", _raise_404)
    server = PrismMockServer(_write_spec(tmp_path), port=18773)
    with server:
        assert server.base_url == "http://127.0.0.1:18773"
        assert len(_FakePopen.instances) == 1


def test_prism_server_exits_early_fails_closed(tmp_path, monkeypatch):
    class _DyingPopen(_FakePopen):
        def poll(self):
            return 1

    monkeypatch.setattr("simwork.api_mock.shutil.which", lambda name: "/usr/bin/prism")
    monkeypatch.setattr("simwork.api_mock.subprocess.Popen", _DyingPopen)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(ApiMockError, match="exited"):
        PrismMockServer(_write_spec(tmp_path), port=18772, timeout=5).start()


# --- ApiMockStack ----------------------------------------------------------


def _stack_urlopen(calls: list):
    """Fake urlopen serving the catalog + spec; Prism's readiness probe
    gets a 404, which Prism counts as ready."""
    return _fake_urlopen_factory(
        calls,
        {
            "https://api.apis.guru/v2/list.json": LIST_FIXTURE,
            "https://api.apis.guru/v2/specs/example.com/1.0.0/openapi.json": SPEC_FIXTURE,
        },
    )


def test_stack_without_stateful_serves_prism_on_requested_port(tmp_path, monkeypatch):
    monkeypatch.setattr("simwork.api_mock.shutil.which", lambda name: "/usr/bin/prism")
    monkeypatch.setattr("simwork.api_mock.subprocess.Popen", _FakePopen)
    monkeypatch.setattr("simwork.api_mock.urllib.request.urlopen", _stack_urlopen([]))
    stack = ApiMockStack("example.com", port=18781, cache_dir=tmp_path)
    with stack:
        assert stack.base_url == "http://127.0.0.1:18781"
        assert stack.spec_path is not None and stack.spec_path.exists()
        assert len(_FakePopen.instances) == 1
        argv = _FakePopen.instances[0].argv
        assert "--port" in argv and "18781" in argv
    assert _FakePopen.instances[0].terminated


def test_stack_with_stateful_layers_proxy_on_requested_port(tmp_path, monkeypatch):
    monkeypatch.setattr("simwork.api_mock.shutil.which", lambda name: "/usr/bin/prism")
    monkeypatch.setattr("simwork.api_mock.subprocess.Popen", _FakePopen)
    monkeypatch.setattr("simwork.api_mock.urllib.request.urlopen", _stack_urlopen([]))
    stops: list[str] = []
    orig_proxy_stop = StatefulStubServer.stop
    orig_prism_stop = PrismMockServer.stop
    monkeypatch.setattr(
        StatefulStubServer,
        "stop",
        lambda self: (stops.append("proxy"), orig_proxy_stop(self)),
    )
    monkeypatch.setattr(
        PrismMockServer,
        "stop",
        lambda self: (stops.append("prism"), orig_prism_stop(self)),
    )
    stack = ApiMockStack("example.com", port=18782, cache_dir=tmp_path, stateful=True)
    with stack:
        assert stack.base_url == "http://127.0.0.1:18782"  # the proxy's port
        argv = _FakePopen.instances[0].argv
        prism_port = argv[argv.index("--port") + 1]
        assert prism_port != "18782"  # Prism took an ephemeral port
    assert stops == ["proxy", "prism"]  # proxy stops before Prism
    assert _FakePopen.instances[0].terminated


def test_stack_unknown_api_fails_closed_without_spawning_prism(tmp_path, monkeypatch):
    monkeypatch.setattr("simwork.api_mock.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(
        "simwork.api_mock.urllib.request.urlopen",
        _fake_urlopen_factory([], {"https://api.apis.guru/v2/list.json": LIST_FIXTURE}),
    )
    with pytest.raises(ApiMockError, match="nope.example"):
        ApiMockStack("nope.example", cache_dir=tmp_path).start()
    assert _FakePopen.instances == []


def test_stack_missing_prism_binary_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr("simwork.api_mock.shutil.which", lambda name: None)
    monkeypatch.setattr("simwork.api_mock.urllib.request.urlopen", _stack_urlopen([]))
    with pytest.raises(ApiMockError, match="prism"):
        ApiMockStack("example.com", cache_dir=tmp_path).start()


# --- CLI -------------------------------------------------------------------


def test_mock_help_names_api_flag():
    result = subprocess.run(
        [sys.executable, "-m", "simwork.cli", "mock", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--api" in result.stdout


def test_mock_without_api_flag_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["mock"])
    assert excinfo.value.code == 2  # argparse: required --api missing


def test_mock_unknown_api_fails_closed(tmp_path, monkeypatch, capsys):
    fake = _fake_urlopen_factory(
        [], {"https://api.apis.guru/v2/list.json": LIST_FIXTURE}
    )
    monkeypatch.setattr("simwork.api_mock.urllib.request.urlopen", fake)
    rc = main(["mock", "--api", "nope.example", "--cache-dir", str(tmp_path)])
    assert rc == 1
    assert "nope.example" in capsys.readouterr().err
