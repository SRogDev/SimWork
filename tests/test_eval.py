"""Tests for the DeepEval harness, first slice (Phase 3, task 1).

Deterministic metrics over a recorded run trace: tool correctness and
task completion. No LLM judge, no network, $0 — the DeepEval library's
own metric classes were verified (2026-11-17, deepeval 4.3.4) to require
an OPENAI_API_KEY at construction, so the $0 gate computes these two
metrics natively with the same names/semantics; see
docs/deepeval-wiring-2026-11-17.md.
"""

import json

import pytest

from simwork.cli import main
from simwork.eval import (
    EvalReport,
    TraceError,
    evaluate_run,
    load_trace,
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


def test_load_trace_accepts_valid_file(tmp_path):
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(PASSING_TRACE), encoding="utf-8")
    assert load_trace(path) == PASSING_TRACE


def test_load_trace_missing_file_fails_closed(tmp_path):
    with pytest.raises(TraceError, match="cannot read trace"):
        load_trace(tmp_path / "nope.json")


def test_load_trace_invalid_json_fails_closed(tmp_path):
    path = tmp_path / "trace.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(TraceError, match="invalid JSON"):
        load_trace(path)


def test_load_trace_rejects_unknown_top_level_key(tmp_path):
    bad = dict(PASSING_TRACE, surprise=True)
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(TraceError, match="unknown top-level key"):
        load_trace(path)


def test_load_trace_rejects_empty_steps(tmp_path):
    bad = dict(PASSING_TRACE, steps=[])
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(TraceError, match="non-empty"):
        load_trace(path)


def test_load_trace_rejects_unknown_step_type(tmp_path):
    bad = json.loads(json.dumps(PASSING_TRACE))
    bad["steps"][0] = {"type": "mystery", "content": "?"}
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(TraceError, match="unknown step type"):
        load_trace(path)


def test_tool_correctness_exact_match_scores_one():
    report = evaluate_run(PASSING_TRACE)
    metric = report.metric("tool_correctness")
    assert metric.score == 1.0
    assert metric.passed is True


def test_tool_correctness_wrong_arguments_scores_zero():
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["steps"][1]["tool_calls"][0]["arguments"] = {"ticket_id": "T-999"}
    report = evaluate_run(trace)
    assert report.metric("tool_correctness").score == 0.0
    assert report.passed is False


def test_tool_correctness_partial_match_scores_fraction():
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["expected"]["tool_calls"].append(
        {"name": "refund_order", "arguments": {"order_id": "O-1"}}
    )
    report = evaluate_run(trace)
    assert report.metric("tool_correctness").score == 0.5
    assert report.passed is False


def test_tool_correctness_unexpected_call_with_no_expected_scores_zero():
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["expected"]["tool_calls"] = []
    report = evaluate_run(trace)
    assert report.metric("tool_correctness").score == 0.0


def test_tool_correctness_no_expected_no_actual_scores_one():
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["steps"] = [s for s in trace["steps"] if "tool_calls" not in s]
    trace["expected"]["tool_calls"] = []
    report = evaluate_run(trace)
    assert report.metric("tool_correctness").score == 1.0


def test_task_completion_final_answer_contains_expected():
    report = evaluate_run(PASSING_TRACE)
    metric = report.metric("task_completion")
    assert metric.score == 1.0
    assert metric.passed is True


def test_task_completion_missing_fact_scores_zero():
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["expected"]["final_answer_contains"] = ["refunded"]
    report = evaluate_run(trace)
    assert report.metric("task_completion").score == 0.0
    assert report.passed is False


def test_task_completion_no_expectations_scores_one():
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["expected"]["final_answer_contains"] = []
    report = evaluate_run(trace)
    assert report.metric("task_completion").score == 1.0


def test_threshold_override_passes_metric_but_overall_still_fails():
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["expected"]["tool_calls"].append(
        {"name": "refund_order", "arguments": {"order_id": "O-1"}}
    )
    trace["expected"]["final_answer_contains"] = ["refunded"]
    report = evaluate_run(trace, thresholds={"tool_correctness": 0.5})
    assert report.metric("tool_correctness").passed is True
    assert report.metric("task_completion").passed is False
    assert report.passed is False


def test_threshold_override_passes_overall_when_all_metrics_pass():
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["expected"]["tool_calls"].append(
        {"name": "refund_order", "arguments": {"order_id": "O-1"}}
    )
    trace["expected"]["final_answer_contains"] = []
    report = evaluate_run(trace, thresholds={"tool_correctness": 0.5})
    assert report.passed is True


def test_same_trace_twice_gives_identical_report():
    first = evaluate_run(PASSING_TRACE)
    second = evaluate_run(PASSING_TRACE)
    assert first.to_json() == second.to_json()
    assert first.trace_hash == second.trace_hash


def test_report_text_names_metrics_and_verdict():
    report = evaluate_run(PASSING_TRACE)
    text = report.to_text()
    assert "tool_correctness" in text
    assert "task_completion" in text
    assert "PASS" in text


def test_report_json_is_machine_readable():
    report = evaluate_run(PASSING_TRACE)
    data = json.loads(report.to_json())
    assert data["passed"] is True
    assert data["run_id"] == "ticket-status-1"
    assert data["seed"] == 7
    assert len(data["metrics"]) == 2
    assert all(m["passed"] for m in data["metrics"])


def test_cli_eval_passing_trace_exits_zero(tmp_path, capsys):
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(PASSING_TRACE), encoding="utf-8")
    assert main(["eval", "--trace", str(path)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_eval_failing_trace_exits_one(tmp_path, capsys):
    trace = json.loads(json.dumps(PASSING_TRACE))
    trace["expected"]["final_answer_contains"] = ["refunded"]
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    assert main(["eval", "--trace", str(path)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_eval_writes_json_report_when_asked(tmp_path):
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(PASSING_TRACE), encoding="utf-8")
    report_path = tmp_path / "report.json"
    assert main(["eval", "--trace", str(trace_path), "--report", str(report_path)]) == 0
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert data["trace_hash"] == evaluate_run(PASSING_TRACE).trace_hash


def test_cli_eval_missing_trace_file_fails_closed(tmp_path, capsys):
    assert main(["eval", "--trace", str(tmp_path / "nope.json")]) == 1
    assert "cannot read trace" in capsys.readouterr().err


def test_cli_eval_invalid_trace_fails_closed(tmp_path, capsys):
    path = tmp_path / "trace.json"
    path.write_text("{not json", encoding="utf-8")
    assert main(["eval", "--trace", str(path)]) == 1
    assert "invalid JSON" in capsys.readouterr().err


def test_cli_eval_on_shipped_example_passes():
    assert main(["eval", "--trace", "examples/ticket-status-trace.json"]) == 0


def test_evaluate_run_rejects_unknown_metric_threshold():
    with pytest.raises(ValueError, match="unknown metric"):
        evaluate_run(PASSING_TRACE, thresholds={"nope": 0.5})


def test_report_is_an_eval_report_instance():
    assert isinstance(evaluate_run(PASSING_TRACE), EvalReport)
