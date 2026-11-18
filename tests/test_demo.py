"""Tests for the LangGraph demo end-to-end (Phase 4, task 3).

The demo is a small LangGraph agent app that calls one LLM (the fake
OpenAI server, scripted) and one world API (a Prism mock of a bundled
ticket API spec), records the run as a trace, and gates it with the $0
eval. The end-to-end tests need the `demo` dependency group
(`uv sync --group demo`) and the `prism` binary, so they skip when
either is missing and CI stays green offline; the fail-closed tests
run everywhere.
"""

from __future__ import annotations

import json
import shutil
import socket
import sys

import pytest

from simwork.cli import main
from simwork.demo import DemoError, messages_to_trace, run_demo
from simwork.eval import evaluate_run
from simwork.trace import final_answer, tool_calls, trace_hash

RUN_ID = "langgraph-demo-1"


@pytest.fixture
def demo_deps():
    """Skip the live end-to-end tests when the demo deps are missing."""
    pytest.importorskip("langgraph")
    pytest.importorskip("langchain_openai")
    if shutil.which("prism") is None:
        pytest.skip("prism not installed (npm i -g @stoplight/prism-cli)")


def test_demo_runs_end_to_end_and_passes_gate(demo_deps):
    trace, report = run_demo()
    assert report.passed, report.to_text()
    assert trace["run_id"] == RUN_ID
    assert trace["seed"] == 7
    assert tool_calls(trace) == [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}]
    assert "shipped" in final_answer(trace)
    # The tool result came from the world-API mock, not from the LLM.
    results = [s for s in trace["steps"] if s["type"] == "tool_result"]
    assert results == [
        {
            "type": "tool_result",
            "name": "lookup_ticket",
            "result": {"ticket_id": "T-123", "status": "shipped"},
        }
    ]


def test_demo_is_deterministic(demo_deps):
    trace1, _ = run_demo()
    trace2, _ = run_demo()
    assert trace_hash(trace1) == trace_hash(trace2)


def test_demo_makes_no_real_network_calls(demo_deps, monkeypatch):
    """The demo talks only to localhost mocks — any other host fails.

    Guards `socket.connect`: the fake LLM server, the Prism mock and
    the demo's HTTP tool all bind 127.0.0.1, so a connection anywhere
    else would be a real-world call and must surface here, not slip
    through silently.
    """
    orig_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"demo tried a non-local connection to {address!r}")
        return orig_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    trace, report = run_demo()
    assert report.passed, report.to_text()


def test_demo_messages_to_trace(demo_deps):
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    messages = [
        HumanMessage(content="What's the status of ticket T-123?"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "lookup_ticket",
                    "args": {"ticket_id": "T-123"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"ticket_id": "T-123", "status": "shipped"}',
            name="lookup_ticket",
            tool_call_id="call-1",
        ),
        AIMessage(content="Your replacement has shipped."),
    ]
    trace = messages_to_trace(
        messages,
        run_id=RUN_ID,
        seed=7,
        expected={
            "tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}],
            "final_answer_contains": ["shipped"],
        },
    )
    assert trace["steps"] == [
        {
            "type": "assistant",
            "tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}],
        },
        {
            "type": "tool_result",
            "name": "lookup_ticket",
            "result": {"ticket_id": "T-123", "status": "shipped"},
        },
        {"type": "assistant", "content": "Your replacement has shipped."},
    ]
    assert evaluate_run(trace).passed


def test_demo_missing_prism_fails_closed(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(DemoError, match="prism"):
        run_demo()


def test_demo_missing_langgraph_fails_closed(monkeypatch):
    # Block the lazy langgraph import: None in sys.modules makes the
    # import raise ImportError, which run_demo turns into a DemoError
    # with the install hint.
    monkeypatch.setitem(sys.modules, "langgraph", None)
    monkeypatch.setitem(sys.modules, "langgraph.graph", None)
    with pytest.raises(DemoError, match=r"uv sync --group demo"):
        run_demo()


def test_cli_demo_without_langgraph_reports_install_hint(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "langgraph", None)
    monkeypatch.setitem(sys.modules, "langgraph.graph", None)
    assert main(["demo"]) == 1
    assert "uv sync --group demo" in capsys.readouterr().err


def test_cli_demo_passes_gate_and_writes_files(demo_deps, tmp_path, capsys):
    trace_path = tmp_path / "demo-trace.json"
    report_path = tmp_path / "demo-report.json"
    assert main(["demo", "--trace", str(trace_path), "--report", str(report_path)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "Trace hash:" in out
    saved = json.loads(trace_path.read_text(encoding="utf-8"))
    assert saved["run_id"] == RUN_ID
    assert evaluate_run(saved).passed
    assert json.loads(report_path.read_text(encoding="utf-8"))["passed"] is True
