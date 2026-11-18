"""Tests for the opt-in DeepEval LLM-judge path (Phase 3, task 3).

The $0 default gate stays native (see tests/test_eval.py). This module
wires DeepEval's own metric classes for the opt-in judge path:
``trace_to_test_case`` + ``judge_metrics`` (pytest-native, for use with
DeepEval's ``evaluate()`` / ``assert_test``) and ``run_judge`` /
``evaluate_run_with_judge`` (CLI path, ``simwork eval --judge``).

Most tests run against a stub ``deepeval`` module injected into
``sys.modules`` — the real library is an optional dependency and is not
installed in the project venv. Tests that need the real library are
marked to skip when it is absent; run them with deepeval installed
(e.g. the scratch venv) to verify the wiring against DeepEval 4.3.4.
"""

import json
import sys
import types

import pytest

from simwork.eval import evaluate_run
from simwork.deepeval_judge import (
    JudgeError,
    check_judge_ready,
    deepeval_available,
    evaluate_run_with_judge,
    judge_metrics,
    run_judge,
    trace_to_test_case,
)

PASSING_TRACE = {
    "run_id": "ticket-status-1",
    "seed": 7,
    "steps": [
        {"type": "assistant", "content": "I will check the ticket."},
        {
            "type": "assistant",
            "tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}],
        },
        {
            "type": "tool_result",
            "name": "lookup_ticket",
            "result": {"status": "shipped"},
        },
        {"type": "assistant", "content": "Your replacement has shipped."},
    ],
    "expected": {
        "tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}],
        "final_answer_contains": ["shipped"],
    },
}


# ---------------------------------------------------------------------------
# Stub deepeval module (mirrors the real 4.3.4 API surface we use)
# ---------------------------------------------------------------------------


class _FakeToolCall:
    def __init__(self, name, input_parameters=None, **kwargs):
        self.name = name
        self.input_parameters = input_parameters or {}
        self.output = kwargs.get("output")


class _FakeToolCallParams:
    INPUT_PARAMETERS = "input_parameters"
    OUTPUT = "output"


class _FakeLLMTestCase:
    def __init__(self, input, actual_output, tools_called=None, expected_tools=None):
        self.input = input
        self.actual_output = actual_output
        self.tools_called = tools_called or []
        self.expected_tools = expected_tools or []


class _FakeToolCorrectnessMetric:
    instances = []

    def __init__(
        self,
        threshold=0.5,
        should_exact_match=False,
        evaluation_params=None,
        async_mode=True,
        model=None,
        **kwargs,
    ):
        self.threshold = threshold
        self.should_exact_match = should_exact_match
        self.evaluation_params = list(evaluation_params or [])
        self.async_mode = async_mode
        self.model = model
        self.measure_calls = 0
        self.score = None
        self.reason = None
        self.success = None
        type(self).instances.append(self)

    def measure(self, test_case):
        self.measure_calls += 1
        called = test_case.tools_called
        expected = test_case.expected_tools
        if len(called) != len(expected):
            score = 0.0
        else:
            score = 1.0
            for got, want in zip(called, expected):
                if got.name != want.name:
                    score = 0.0
                    break
                if "input_parameters" in self.evaluation_params and (
                    got.input_parameters != want.input_parameters
                ):
                    score = 0.0
                    break
        self.score = score
        self.reason = f"fake tool-correctness reason (score {score})"
        self.success = score >= self.threshold
        return score


class _FakeTaskCompletionMetric:
    instances = []
    next_score = 1.0

    def __init__(self, threshold=0.5, task=None, model=None, **kwargs):
        self.threshold = threshold
        self.task = task
        self.model = model
        self.measure_calls = 0
        self.score = None
        self.reason = None
        self.success = None
        type(self).instances.append(self)

    def measure(self, test_case):
        self.measure_calls += 1
        self.score = type(self).next_score
        self.reason = "fake judge reason"
        self.success = self.score >= self.threshold
        return self.score


@pytest.fixture
def fake_deepeval(monkeypatch):
    """Inject a stub deepeval package into sys.modules for this test."""
    _FakeToolCorrectnessMetric.instances.clear()
    _FakeTaskCompletionMetric.instances.clear()
    _FakeTaskCompletionMetric.next_score = 1.0
    pkg = types.ModuleType("deepeval")
    test_case_mod = types.ModuleType("deepeval.test_case")
    test_case_mod.LLMTestCase = _FakeLLMTestCase
    test_case_mod.ToolCall = _FakeToolCall
    test_case_mod.ToolCallParams = _FakeToolCallParams
    metrics_mod = types.ModuleType("deepeval.metrics")
    metrics_mod.ToolCorrectnessMetric = _FakeToolCorrectnessMetric
    metrics_mod.TaskCompletionMetric = _FakeTaskCompletionMetric
    monkeypatch.setitem(sys.modules, "deepeval", pkg)
    monkeypatch.setitem(sys.modules, "deepeval.test_case", test_case_mod)
    monkeypatch.setitem(sys.modules, "deepeval.metrics", metrics_mod)
    pkg.test_case = test_case_mod
    pkg.metrics = metrics_mod
    yield types.SimpleNamespace(
        ToolCorrectnessMetric=_FakeToolCorrectnessMetric,
        TaskCompletionMetric=_FakeTaskCompletionMetric,
    )


@pytest.fixture
def dummy_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-dummy")
    return "sk-fake-dummy"


# ---------------------------------------------------------------------------
# Availability / readiness
# ---------------------------------------------------------------------------


def test_deepeval_available_reports_real_state(monkeypatch):
    # Availability is whatever an import attempt says (stub counts as present).
    import importlib.util

    monkeypatch.delitem(sys.modules, "deepeval", raising=False)
    expected = importlib.util.find_spec("deepeval") is not None
    assert deepeval_available() == expected


def test_check_judge_ready_fails_closed_without_deepeval(monkeypatch):
    import importlib.util

    if importlib.util.find_spec("deepeval") is not None:
        pytest.skip("deepeval installed here; the absence path is untestable")
    monkeypatch.delitem(sys.modules, "deepeval", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(JudgeError, match="not installed"):
        check_judge_ready()


def test_check_judge_ready_fails_closed_without_api_key(fake_deepeval, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(JudgeError, match="OPENAI_API_KEY"):
        check_judge_ready()


def test_check_judge_ready_ok_with_stub_and_key(fake_deepeval, dummy_key):
    check_judge_ready()  # must not raise


def test_check_judge_ready_budget_blocks_judge_call(fake_deepeval, dummy_key):
    # Task completion costs 1 LLM call; a budget of 0 fails before any call.
    with pytest.raises(JudgeError, match="budget"):
        check_judge_ready(max_llm_calls=0)
    # ...but the deterministic tool-correctness metric alone needs no calls.
    check_judge_ready(max_llm_calls=0, include=("tool_correctness",))


# ---------------------------------------------------------------------------
# Trace -> DeepEval test case
# ---------------------------------------------------------------------------


def test_trace_to_test_case_maps_trace_fields(fake_deepeval):
    tc = trace_to_test_case(PASSING_TRACE)
    assert isinstance(tc, _FakeLLMTestCase)
    assert tc.actual_output == "Your replacement has shipped."
    assert "ticket-status-1" in tc.input
    assert "shipped" in tc.input  # expected facts become the task text
    assert [(t.name, t.input_parameters) for t in tc.tools_called] == [
        ("lookup_ticket", {"ticket_id": "T-123"})
    ]
    assert [(t.name, t.input_parameters) for t in tc.expected_tools] == [
        ("lookup_ticket", {"ticket_id": "T-123"})
    ]


def test_trace_to_test_case_without_expected(fake_deepeval):
    trace = {k: v for k, v in PASSING_TRACE.items() if k != "expected"}
    tc = trace_to_test_case(trace)
    assert tc.tools_called[0].name == "lookup_ticket"
    assert tc.expected_tools == []


def test_trace_to_test_case_rejects_invalid_trace(fake_deepeval):
    with pytest.raises(Exception, match="steps"):
        trace_to_test_case({"run_id": "x"})


def test_trace_to_test_case_without_deepeval(monkeypatch):
    import importlib.util

    if importlib.util.find_spec("deepeval") is not None:
        pytest.skip("deepeval installed here; the absence path is untestable")
    monkeypatch.delitem(sys.modules, "deepeval", raising=False)
    with pytest.raises(JudgeError, match="not installed"):
        trace_to_test_case(PASSING_TRACE)


# ---------------------------------------------------------------------------
# Metric factory (pytest-native wiring)
# ---------------------------------------------------------------------------


def test_judge_metrics_builds_library_metrics(fake_deepeval, dummy_key):
    metrics = judge_metrics(model="gpt-4o-mini")
    assert len(metrics) == 2
    tool_metric, judge_metric = metrics
    assert isinstance(tool_metric, _FakeToolCorrectnessMetric)
    assert isinstance(judge_metric, _FakeTaskCompletionMetric)
    # Exact-match mode, arguments compared, sync (deterministic, no LLM).
    assert tool_metric.should_exact_match is True
    assert "input_parameters" in tool_metric.evaluation_params
    assert tool_metric.async_mode is False
    assert tool_metric.model == "gpt-4o-mini"
    assert judge_metric.model == "gpt-4o-mini"


def test_judge_metrics_default_threshold_is_deepeval_default(fake_deepeval):
    metrics = judge_metrics()
    assert metrics[0].threshold == 0.5
    assert metrics[1].threshold == 0.5


def test_judge_metrics_include_selects_subset(fake_deepeval):
    assert len(judge_metrics(include=("tool_correctness",))) == 1
    assert len(judge_metrics(include=("task_completion",))) == 1


def test_judge_metrics_respects_include_order(fake_deepeval):
    """Metrics must come back in the caller's include order, not a fixed one.

    `run_judge` pairs names with metrics by position, so a fixed order
    here mislabels the scores (the --judge-metrics ordering bug).
    """
    metrics = judge_metrics(include=("task_completion", "tool_correctness"))
    assert isinstance(metrics[0], _FakeTaskCompletionMetric)
    assert isinstance(metrics[1], _FakeToolCorrectnessMetric)


def test_run_judge_respects_include_order(fake_deepeval, dummy_key):
    _FakeTaskCompletionMetric.next_score = 0.8
    results = run_judge(PASSING_TRACE, include=("task_completion", "tool_correctness"))
    assert [r.name for r in results] == ["judge_task_completion", "judge_tool_correctness"]
    assert results[0].score == 0.8  # the judge's score, on the judge's name
    assert results[1].score == 1.0  # the exact-match tool score, on its name


def test_judge_metrics_rejects_unknown_name(fake_deepeval):
    with pytest.raises(JudgeError, match="unknown judge metric"):
        judge_metrics(include=("bogus",))


# ---------------------------------------------------------------------------
# run_judge
# ---------------------------------------------------------------------------


def test_run_judge_returns_judge_results(fake_deepeval, dummy_key):
    _FakeTaskCompletionMetric.next_score = 0.8
    results = run_judge(PASSING_TRACE)
    assert [r.name for r in results] == ["judge_tool_correctness", "judge_task_completion"]
    assert results[0].score == 1.0  # exact tool match
    assert results[1].score == 0.8
    assert results[0].threshold == 0.5
    assert results[1].threshold == 0.5
    assert all(r.passed for r in results)
    assert "fake" in results[0].details


def test_run_judge_thresholds_apply(fake_deepeval, dummy_key):
    _FakeTaskCompletionMetric.next_score = 0.8
    results = run_judge(PASSING_TRACE, thresholds={"task_completion": 0.9})
    assert results[1].passed is False


def test_run_judge_failing_tool_call(fake_deepeval, dummy_key):
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["steps"][1]["tool_calls"][0]["arguments"] = {"ticket_id": "T-999"}
    results = run_judge(trace)
    assert results[0].score == 0.0
    assert results[0].passed is False


def test_run_judge_budget_blocks_before_any_call(fake_deepeval, dummy_key):
    with pytest.raises(JudgeError, match="budget"):
        run_judge(PASSING_TRACE, max_llm_calls=0)
    # No metric was even constructed, so nothing was measured.
    assert _FakeToolCorrectnessMetric.instances == []
    assert _FakeTaskCompletionMetric.instances == []


def test_run_judge_tool_correctness_only_needs_no_budget(fake_deepeval, dummy_key):
    results = run_judge(PASSING_TRACE, max_llm_calls=0, include=("tool_correctness",))
    assert [r.name for r in results] == ["judge_tool_correctness"]
    assert results[0].score == 1.0


def test_run_judge_fails_closed_without_key(fake_deepeval, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(JudgeError, match="OPENAI_API_KEY"):
        run_judge(PASSING_TRACE)


# ---------------------------------------------------------------------------
# Combined report
# ---------------------------------------------------------------------------


def test_evaluate_run_with_judge_combines_native_and_judge(fake_deepeval, dummy_key):
    native = evaluate_run(PASSING_TRACE)
    combined = evaluate_run_with_judge(PASSING_TRACE)
    assert combined.trace_hash == native.trace_hash
    assert combined.run_id == native.run_id
    assert [m.name for m in combined.metrics] == [
        "tool_correctness",
        "task_completion",
        "judge_tool_correctness",
        "judge_task_completion",
    ]
    assert combined.passed is True


def test_evaluate_run_with_judge_gate_includes_judge(fake_deepeval, dummy_key):
    _FakeTaskCompletionMetric.next_score = 0.2
    combined = evaluate_run_with_judge(PASSING_TRACE)
    assert combined.passed is False
    assert combined.metric("judge_task_completion").passed is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_eval_judge_fails_closed_without_deepeval(tmp_path, monkeypatch, capsys):
    from simwork.cli import main

    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(PASSING_TRACE), encoding="utf-8")
    monkeypatch.delitem(sys.modules, "deepeval", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rc = main(["eval", "--trace", str(trace_path), "--judge"])
    assert rc == 1
    assert "deepeval" in capsys.readouterr().err.lower()


def test_cli_eval_judge_with_stub(tmp_path, fake_deepeval, dummy_key, capsys):
    from simwork.cli import main

    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(PASSING_TRACE), encoding="utf-8")
    rc = main(["eval", "--trace", str(trace_path), "--judge"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "judge_tool_correctness" in out
    assert "judge_task_completion" in out
    assert "Overall: PASS" in out


def test_cli_eval_judge_rejects_unknown_metric(tmp_path, fake_deepeval, dummy_key, capsys):
    from simwork.cli import main

    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(PASSING_TRACE), encoding="utf-8")
    rc = main(["eval", "--trace", str(trace_path), "--judge", "--judge-metrics", "bogus"])
    assert rc == 1
    assert "bogus" in capsys.readouterr().err


def test_cli_eval_without_judge_unchanged(tmp_path, capsys):
    from simwork.cli import main

    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(PASSING_TRACE), encoding="utf-8")
    rc = main(["eval", "--trace", str(trace_path)])
    assert rc == 0
    assert "judge_" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Real DeepEval library (skipped unless deepeval is installed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not deepeval_available(), reason="deepeval not installed")
def test_real_library_tool_correctness_matches_native(monkeypatch):
    """DeepEval 4.3.4 ToolCorrectnessMetric, exact-match + INPUT_PARAMETERS,
    async_mode=False: same scores as the native metric, offline, dummy key.
    A real model call with a dummy key would fail auth — a returned score
    proves no network call happened."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-dummy")
    results = run_judge(PASSING_TRACE, include=("tool_correctness",), max_llm_calls=0)
    assert [r.name for r in results] == ["judge_tool_correctness"]
    assert results[0].score == 1.0
    assert results[0].passed is True


@pytest.mark.skipif(not deepeval_available(), reason="deepeval not installed")
def test_real_library_tool_correctness_catches_wrong_args(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-dummy")
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["steps"][1]["tool_calls"][0]["arguments"] = {"ticket_id": "T-999"}
    results = run_judge(trace, include=("tool_correctness",), max_llm_calls=0)
    assert results[0].score == 0.0
    assert results[0].passed is False
