"""Tests for the Polygrow pilot (adoption readiness criterion 3, slice 1).

The pilot simulates one real Polygrow flow end-to-end: a Mind chat turn
for a general-chat message, mirroring the real `ai_mind` graph's node
sequence and routing rules. The end-to-end tests need the `demo`
dependency group (`uv sync --group demo`) and the `prism` binary, so
they skip when either is missing and CI stays green offline; the
fail-closed and pure-rules tests run everywhere.
"""

from __future__ import annotations

import json
import shutil
import socket
import sys
from pathlib import Path

import pytest
import yaml

from simwork.cli import main
from simwork.eval import evaluate_run
from simwork.pilot import (
    EXPECTED,
    RUN_ID,
    PilotError,
    classify_deterministic,
    intent_prompt,
    is_bi_request,
    route_after_intent,
    run_pilot,
)
from simwork.trace import final_answer, trace_hash

CALIBRATION_PATH = Path(__file__).parent.parent / "examples" / "polygrow-pilot" / "calibration.yaml"


@pytest.fixture
def pilot_deps():
    """Skip the live end-to-end tests when the demo deps are missing."""
    pytest.importorskip("langgraph")
    pytest.importorskip("langchain_openai")
    if shutil.which("prism") is None:
        pytest.skip("prism not installed (npm i -g @stoplight/prism-cli)")


def test_pilot_runs_end_to_end_and_passes_gate(pilot_deps):
    trace, report, result = run_pilot()
    assert report.passed, report.to_text()
    assert trace["run_id"] == RUN_ID
    assert trace["seed"] == 7
    assert trace["expected"] == EXPECTED
    # The real routing, reproduced: general_chat at 0.85 goes straight
    # to response_formatter, and the real graph has no answer for it.
    assert result["intent"] == "general_chat"
    assert result["confidence"] == 0.85
    assert result["route"] == "response_formatter"
    assert result["final_answer"] == "No response generated."
    assert "No response generated." in result["finding"]
    assert final_answer(trace) == "No response generated."
    # The context read came from the world-API mock, not from the LLM.
    context_step = next(s for s in trace["steps"] if s.get("name") == "fetch_business_context")
    assert context_step["result"]["name"] == "Demo Business"
    # The memory write landed: both messages read back from the stub.
    memory_step = next(s for s in trace["steps"] if s.get("name") == "memory_write")
    assert memory_step["result"]["stored"] == 2
    assert [m["role"] for m in memory_step["result"]["messages"]] == ["user", "assistant"]
    assert result["memory_stored"] == 2
    # No tool calls: the intent classification is a plain completion.
    assert [s for s in trace["steps"] if "tool_calls" in s] == []


def test_pilot_is_deterministic(pilot_deps):
    trace1, _, _ = run_pilot()
    trace2, _, _ = run_pilot()
    assert trace_hash(trace1) == trace_hash(trace2)


def test_pilot_makes_no_real_network_calls(pilot_deps, monkeypatch):
    """The pilot talks only to localhost mocks — any other host fails.

    Same guard as the demo: the fake LLM server, the Prism mock and
    the pilot's HTTP calls all bind 127.0.0.1, so a connection anywhere
    else would be a real-world call and must surface here.
    """
    orig_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"pilot tried a non-local connection to {address!r}")
        return orig_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    trace, report, _ = run_pilot()
    assert report.passed, report.to_text()


def test_pilot_missing_prism_fails_closed(monkeypatch):
    # Isolate the prism path: pretend the demo deps are installed, so
    # this test fails on the missing prism even in environments (like
    # CI) where both are missing.
    monkeypatch.setattr("simwork.pilot._check_pilot_deps", lambda: None)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(PilotError, match="prism"):
        run_pilot()


def test_pilot_missing_langgraph_fails_closed(monkeypatch):
    # Block the lazy langgraph import: None in sys.modules makes the
    # import raise ImportError, which run_pilot turns into a PilotError
    # with the install hint.
    monkeypatch.setitem(sys.modules, "langgraph", None)
    monkeypatch.setitem(sys.modules, "langgraph.graph", None)
    with pytest.raises(PilotError, match=r"uv sync --group demo"):
        run_pilot()


def test_cli_pilot_without_langgraph_reports_install_hint(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "langgraph", None)
    monkeypatch.setitem(sys.modules, "langgraph.graph", None)
    assert main(["pilot"]) == 1
    assert "uv sync --group demo" in capsys.readouterr().err


def test_cli_pilot_passes_gate_and_writes_files(pilot_deps, tmp_path, capsys):
    trace_path = tmp_path / "pilot-trace.json"
    report_path = tmp_path / "pilot-report.json"
    assert main(["pilot", "--trace", str(trace_path), "--report", str(report_path)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "Trace hash:" in out
    assert "general_chat" in out
    assert "No response generated." in out
    saved = json.loads(trace_path.read_text(encoding="utf-8"))
    assert saved["run_id"] == RUN_ID
    assert evaluate_run(saved).passed
    assert json.loads(report_path.read_text(encoding="utf-8"))["passed"] is True


# -- Pure ported-rules tests (run everywhere, no mocks) --------------------


def test_route_after_intent_matches_real_router():
    # Confidence below the 0.6 threshold always goes to the planner.
    assert route_after_intent("general_chat", 0.59) == "planner"
    assert route_after_intent("general_chat", 0.6) == "response_formatter"
    # The planner intents, at high confidence.
    assert route_after_intent("support_request", 0.9) == "planner"
    assert route_after_intent("capability", 0.9) == "planner"
    assert route_after_intent("artifact_create", 0.9) == "planner"
    # Proactivity goes to the executor; anything else to the formatter.
    assert route_after_intent("proactivity_response", 0.9) == "executor"
    assert route_after_intent("general_chat", 0.85) == "response_formatter"


def test_intent_prompt_is_the_real_prompt():
    prompt = intent_prompt("Hola, ¿qué puedes hacer por mi negocio?")
    assert "Hola, ¿qué puedes hacer por mi negocio?" in prompt
    assert "general_chat" in prompt
    assert "support_request" in prompt
    assert "businesses serving their own customers is not Polygrow support" in prompt


def test_calibration_sample_matches_real_rules():
    """Every deterministic calibration case matches the ported rules.

    The LLM-classified case is skipped here — it is verified by the
    end-to-end pilot run, not by the pure rules.
    """
    cases = yaml.safe_load(CALIBRATION_PATH.read_text(encoding="utf-8"))
    assert isinstance(cases, list) and len(cases) >= 5
    for case in cases:
        assert set(case) <= {
            "message",
            "has_active_artifact",
            "expected_intent",
            "expected_confidence",
            "expected_bi",
            "expected_planner_action",
            "llm_classified",
            "source",
        }, f"unknown key in calibration case: {case}"
        message = case["message"]
        if case.get("llm_classified"):
            continue
        decided = classify_deterministic(
            message, has_active_artifact=case.get("has_active_artifact", False)
        )
        if case.get("expected_intent") is None:
            assert decided is None, f"{message!r}: expected no rule to fire, got {decided}"
        else:
            assert decided == (case["expected_intent"], case["expected_confidence"]), (
                f"{message!r}: expected "
                f"{(case['expected_intent'], case['expected_confidence'])}, got {decided}"
            )
        if "expected_bi" in case:
            assert is_bi_request(message) is case["expected_bi"], (
                f"{message!r}: is_bi_request mismatch"
            )
        if "expected_planner_action" in case:
            # The planner action is the real code's hardcoded branch for
            # BI messages (planner_node); the pilot asserts the BI flag
            # that triggers it, the branch itself lives in Polygrow.
            assert case["expected_planner_action"] == "delegate:bi"
            assert is_bi_request(message) is True
