"""API mock layer: fetch an OpenAPI spec from APIs.guru and serve it with Prism.

Phase 2, task 1 — ``simwork mock --api <name>`` only: resolve the API's
preferred version in the APIs.guru catalog, download its OpenAPI spec
(cached under ``~/.cache/simwork``), and run it as a mock with Prism
(``@stoplight/prism-cli``) as a sidecar subprocess. The stateful stub
layer is a later Phase 2 task.

Fail-closed, per the spec: an unknown API name, a download failure, a
missing ``prism`` binary, or a Prism process that exits early all raise
`ApiMockError` instead of silently falling back to a real API.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

LIST_URL = "https://api.apis.guru/v2/list.json"
LIST_TTL_SECONDS = 24 * 3600  # re-fetch the catalog at most once a day
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "simwork"
_PRISM_INSTALL_HINT = "npm i -g @stoplight/prism-cli (requires Node 18+)"


class ApiMockError(Exception):
    """Raised when the API mock cannot be fetched or served. Fail closed."""


def resolve_api_spec_url(api_name: str, list_data: dict) -> tuple[str, str, str]:
    """Resolve an APIs.guru name to its preferred spec URL.

    Returns ``(swagger_url, title, version)``. Raises `ApiMockError` for an
    unknown name or a catalog entry without a preferred version.
    """
    entry = list_data.get(api_name)
    if entry is None:
        raise ApiMockError(
            f"unknown API {api_name!r} in the APIs.guru catalog "
            f"({len(list_data)} APIs listed) — check the name at https://apis.guru"
        )
    version = entry.get("preferred")
    versions = entry.get("versions", {})
    spec = versions.get(version or "", {})
    url = spec.get("swaggerUrl")
    if not url:
        raise ApiMockError(
            f"APIs.guru entry for {api_name!r} has no spec URL for its preferred "
            f"version {version!r}"
        )
    info = spec.get("info", {})
    return url, info.get("title", api_name), version


def _download_json(url: str, urlopen: Callable) -> dict:
    # APIs.guru (Cloudflare) rejects the default Python-urllib User-Agent
    # with 403, so identify as SimWork.
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SimWork/0.1.0 (+https://github.com/SRogDev/SimWork)"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ApiMockError(f"could not download {url}: {e}") from None
    if not isinstance(data, dict):
        raise ApiMockError(f"expected a JSON object from {url}, got {type(data).__name__}")
    return data


def _read_cached_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def fetch_api_spec(
    api_name: str,
    cache_dir: str | Path | None = None,
    *,
    urlopen: Callable | None = None,
) -> Path:
    """Download (or reuse from cache) the OpenAPI spec for ``api_name``.

    Returns the path of the cached spec file. The catalog list is cached
    for 24h; a spec already cached for the resolved version is reused
    without re-downloading. Any failure raises `ApiMockError` and leaves
    no half-written file behind.
    """
    if urlopen is None:
        urlopen = urllib.request.urlopen
    cache = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    list_path = cache / "apis-guru-list.json"

    list_data: dict | None = None
    if list_path.exists() and time.time() - list_path.stat().st_mtime < LIST_TTL_SECONDS:
        list_data = _read_cached_json(list_path)
    if list_data is None:
        list_data = _download_json(LIST_URL, urlopen)
        tmp = list_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(list_data), encoding="utf-8")
        tmp.replace(list_path)

    spec_url, _title, version = resolve_api_spec_url(api_name, list_data)
    safe_name = api_name.replace("/", "_")
    spec_path = cache / "specs" / f"{safe_name}-{version}.json"
    if spec_path.exists() and _read_cached_json(spec_path) is not None:
        return spec_path
    spec = _download_json(spec_url, urlopen)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = spec_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(spec), encoding="utf-8")
    tmp.replace(spec_path)
    return spec_path


def _free_port(host: str) -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


class PrismMockServer:
    """Runs one OpenAPI spec as a mock via the `prism` CLI (sidecar process).

    Prism serves dynamic mocks from the spec's examples/schemas. Any HTTP
    response (even a 404 for an unknown path) counts as "ready"; the
    server is only a mock — it never forwards to a real API.
    """

    def __init__(
        self,
        spec_path: str | Path,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        prism_bin: str | None = None,
        timeout: float = 30.0,
    ):
        self.spec_path = Path(spec_path)
        self.host = host
        self.port = port
        self.prism_bin = prism_bin
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> "PrismMockServer":
        if self._proc is not None:
            return self
        if not self.spec_path.exists():
            raise ApiMockError(f"spec file not found: {self.spec_path}")
        spec = _read_cached_json(self.spec_path)
        if spec is None or ("openapi" not in spec and "swagger" not in spec):
            raise ApiMockError(
                f"{self.spec_path} is not a valid OpenAPI spec "
                "(expected an 'openapi' or 'swagger' key)"
            )
        binary = self.prism_bin or shutil.which("prism")
        if binary is None:
            raise ApiMockError(
                "the `prism` binary was not found on PATH — install it with "
                f"{_PRISM_INSTALL_HINT}"
            )
        if self.port == 0:
            self.port = _free_port(self.host)
        argv = [
            binary,
            "mock",
            str(self.spec_path),
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]
        self._proc = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._wait_ready()
        return self

    def _wait_ready(self) -> None:
        assert self._proc is not None
        deadline = time.monotonic() + self.timeout
        while True:
            if self._proc.poll() is not None:
                err = ""
                if self._proc.stderr is not None:
                    err = self._proc.stderr.read()[-500:]
                self._proc = None
                raise ApiMockError(f"prism exited before becoming ready: {err.strip()}")
            try:
                with urllib.request.urlopen(self.base_url, timeout=1):
                    return
            except urllib.error.HTTPError:
                # Any HTTP response (even Prism's 404 for the unknown root
                # path) means the mock is up and serving.
                return
            except Exception:
                pass
            if time.monotonic() >= deadline:
                self.stop()
                raise ApiMockError(
                    f"prism did not become ready at {self.base_url} within {self.timeout}s"
                )
            time.sleep(0.2)

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def __enter__(self) -> "PrismMockServer":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
