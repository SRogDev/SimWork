"""Tests for the thousand-run scale smoke test (§7 check-off).

`simwork scale` repeats the LangGraph demo N times against the same
already-running mocks (one fake OpenAI server + one Prism mock, the
scripted LLM reset between runs) and reports one deterministic
per-run result each: same seed + same scenario must give the same
trace hash on every run, and every run must pass the $0 gate. The
live tests need the `demo` dependency group (`uv sync --group demo`)
and the `prism` binary, so they skip when either is missing and CI
stays green offline; the input-validation tests run everywhere.
"""

from __future__ import annotations

import json
import shutil
import socket

import pytest

from simwork.cli import main
from simwork.demo import run_demo
from simwork.scale import ScaleError, run_scale
from simwork.trace import trace_hash


@pytest.fixture
def scale_deps():
    """Skip the live scale tests when the demo deps are missing."""
    pytest.importorskip("langgraph")
    pytest.importorskip("langchain_openai")
    if shutil.which("prism") is None:
        pytest.skip("prism not installed (npm i -g @stoplight/prism-cli)")


def test_scale_small_batch_passes_with_one_hash(scale_deps):
    report = run_scale(runs=3)
    assert report.passed
    assert report.runs == 3
    assert report.passed_runs == 3
    assert report.failed_runs == 0
    assert len(report.distinct_hashes) == 1
    assert report.runs_per_second > 0
    # Every run is the identical demo run: same hash as a single demo.
    trace, _ = run_demo()
    assert report.distinct_hashes[0] == trace_hash(trace)


def test_scale_report_round_trips(scale_deps):
    report = run_scale(runs=2)
    data = json.loads(report.to_json())
    assert data["runs"] == 2
    assert data["passed"] is True
    assert data["passed_runs"] == 2
    assert data["failed_runs"] == 0
    assert len(data["distinct_hashes"]) == 1
    assert len(data["results"]) == 2
    assert all(r["passed"] for r in data["results"])
    assert all(r["error"] is None for r in data["results"])
    assert data["elapsed_seconds"] > 0
    assert data["runs_per_second"] > 0
    text = report.to_text()
    assert "2 runs" in text
    assert "PASS" in text
    assert "distinct trace hash" in text


def test_scale_rejects_non_positive_runs():
    with pytest.raises(ScaleError, match="runs must be a positive integer"):
        run_scale(runs=0)
    with pytest.raises(ScaleError, match="runs must be a positive integer"):
        run_scale(runs=-5)


def test_scale_missing_prism_fails_closed(monkeypatch):
    # Isolate the prism path: pretend the demo deps are installed, so
    # this test fails on the missing prism even in environments (like
    # CI) where both are missing — the deps error wins there by design.
    monkeypatch.setattr("simwork.demo._check_demo_deps", lambda: None)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ScaleError, match="prism"):
        run_scale(runs=2)


def test_scale_makes_no_real_network_calls(scale_deps, monkeypatch):
    """The batch talks only to localhost mocks — any other host fails.

    Same guard as the single demo run, applied to the whole batch.
    """
    orig_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"scale run tried a non-local connection to {address!r}")
        return orig_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    assert run_scale(runs=2).passed


def test_cli_scale_passes_and_writes_report(scale_deps, tmp_path, capsys):
    report_path = tmp_path / "scale-report.json"
    assert main(["scale", "--runs", "2", "--report", str(report_path)]) == 0
    out = capsys.readouterr().out
    assert "2 runs" in out
    assert "PASS" in out
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["passed"] is True
    assert saved["runs"] == 2


def test_cli_scale_rejects_zero_runs(capsys):
    assert main(["scale", "--runs", "0"]) == 1
    assert "runs must be a positive integer" in capsys.readouterr().err
