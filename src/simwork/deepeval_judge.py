"""Opt-in DeepEval LLM-judge path (Phase 3, task 3).

The $0 default gate stays native (see ``simwork.eval``): it computes tool
correctness + task completion deterministically, with no dependency and
no API key. This module wires DeepEval's *own* metric classes for users
who explicitly opt in to a judge run — ``simwork eval --judge``.

What is wired:

- ``trace_to_test_case`` converts a SimWork trace into a DeepEval
  ``LLMTestCase`` (input = the run's task, actual output = the final
  answer, tools called / expected tools mapped 1:1).
- ``judge_metrics`` builds the library metric objects, so a pytest file
  can use DeepEval's own ``evaluate()`` / ``assert_test`` directly::

      from deepeval import assert_test
      from simwork.deepeval_judge import judge_metrics, trace_to_test_case

      def test_simulated_run():
          assert_test(trace_to_test_case(trace), judge_metrics())

- ``run_judge`` / ``evaluate_run_with_judge`` run those metrics over a
  trace and append the results (``judge_tool_correctness``,
  ``judge_task_completion``) to SimWork's report shape, so the CLI gate
  includes them when the user opts in.

Verified 2026-11-18 against DeepEval 4.3.4 (still the latest release):

- The constructor still demands ``OPENAI_API_KEY`` — that is why the
  library is an *optional* dependency (``simwork[deepeval]``) and the
  judge path fails closed without a key.
- ``ToolCorrectnessMetric`` with ``should_exact_match=True`` compares
  tool *names only* unless ``ToolCallParams.INPUT_PARAMETERS`` is in
  ``evaluation_params`` (found by reading the library source after a
  wrong-arguments case scored 1.0). With that flag, plus
  ``async_mode=False``, it matches the native metric exactly — name +
  arguments, order-sensitive — works offline with a dummy key, and
  makes no network call (a real call with a dummy key would fail auth).
- ``TaskCompletionMetric`` is an LLM judge: it makes a real model call
  (default model ``gpt-5.4`` in 4.3.4) and therefore costs real money.
  Pass ``model=`` to pick a cheaper one.

Budget: ``max_llm_calls`` counts real model calls per run. The
exact-match tool-correctness metric makes 0 calls; task completion
makes 1. The default budget of 1 covers the default judge set; a run
whose judge work would exceed the budget fails closed *before* any
call is made. Judge scores are LLM-generated, so a report that
includes them is not reproducible run-to-run — the trace hash is
unchanged, only the judge scores vary.
"""

from __future__ import annotations

import os
from typing import Any

from simwork.eval import (
    METRIC_NAMES,
    EvalReport,
    MetricResult,
    evaluate_run,
    unknown_metric_names,
)
from simwork.trace import Trace, final_answer, tool_calls, validate_trace

# LLM calls per judge metric: exact-match tool correctness is deterministic
# (async_mode=False, verified offline); task completion is an LLM judge.
_LLM_CALLS_PER_METRIC = {"tool_correctness": 0, "task_completion": 1}
_DEFAULT_JUDGE_THRESHOLD = 0.5  # DeepEval's own default
_REASON_MAX_LEN = 300


class JudgeError(Exception):
    """Raised when the opt-in judge path cannot run (fail closed)."""


def deepeval_available() -> bool:
    """True when the optional ``deepeval`` dependency is importable."""
    try:
        import deepeval  # noqa: F401
    except ImportError:
        return False
    return True


def _load_deepeval() -> tuple[Any, Any, Any, Any, Any]:
    """Import DeepEval's classes, or fail closed with install guidance."""
    if not deepeval_available():
        raise JudgeError(
            "DeepEval is not installed. The judge path is opt-in: install it with "
            "`uv pip install 'simwork[deepeval]'` (or `uv add simwork[deepeval]`), "
            "then re-run with --judge."
        )
    from deepeval.metrics import TaskCompletionMetric, ToolCorrectnessMetric
    from deepeval.test_case import LLMTestCase, ToolCall, ToolCallParams

    return LLMTestCase, ToolCall, ToolCallParams, ToolCorrectnessMetric, TaskCompletionMetric


def _validate_include(include: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    unknown = unknown_metric_names(include)
    if unknown:
        raise JudgeError(
            f"unknown judge metric(s): {sorted(unknown)} (choose from: {', '.join(METRIC_NAMES)})"
        )
    return tuple(include)


def _task_text(trace: Trace) -> str:
    """Task description for the judge: run id + the facts it must cover."""
    run_id = trace.get("run_id") or "unnamed"
    facts = trace.get("expected", {}).get("final_answer_contains", [])
    if facts:
        return f"Run {run_id}: the final answer must mention: {', '.join(facts)}"
    return f"Run {run_id}"


def trace_to_test_case(trace: Trace) -> Any:
    """Convert a validated SimWork trace into a DeepEval ``LLMTestCase``."""
    LLMTestCase, ToolCall, _, _, _ = _load_deepeval()
    trace = validate_trace(trace)
    actual_calls = tool_calls(trace)
    expected_calls = trace.get("expected", {}).get("tool_calls", [])
    return LLMTestCase(
        input=_task_text(trace),
        actual_output=final_answer(trace),
        tools_called=[
            ToolCall(name=c["name"], input_parameters=c.get("arguments", {})) for c in actual_calls
        ],
        expected_tools=[
            ToolCall(name=c["name"], input_parameters=c.get("arguments", {}))
            for c in expected_calls
        ],
    )


def judge_metrics(
    *,
    model: str | None = None,
    thresholds: dict[str, float] | None = None,
    include: tuple[str, ...] | list[str] = METRIC_NAMES,
) -> list[Any]:
    """Build DeepEval's metric objects for the requested judge metrics.

    ``model`` is passed to both metrics (``None`` = DeepEval's default,
    ``gpt-5.4`` in 4.3.4 — a real, billable model for the judge). The
    tool-correctness metric is built deterministic: exact match, input
    parameters compared, sync mode — it makes no model call.

    Metrics come back in the caller's ``include`` order, so `run_judge`
    can pair each result with its name by position.
    """
    _, _, ToolCallParams, ToolCorrectnessMetric, TaskCompletionMetric = _load_deepeval()
    include = _validate_include(include)
    thresholds = thresholds or {}
    unknown = unknown_metric_names(thresholds)
    if unknown:
        raise JudgeError(f"unknown metric(s) in thresholds: {sorted(unknown)}")
    builders = {
        "tool_correctness": lambda: ToolCorrectnessMetric(
            threshold=thresholds.get("tool_correctness", _DEFAULT_JUDGE_THRESHOLD),
            should_exact_match=True,
            evaluation_params=[ToolCallParams.INPUT_PARAMETERS],
            async_mode=False,
            model=model,
        ),
        "task_completion": lambda: TaskCompletionMetric(
            threshold=thresholds.get("task_completion", _DEFAULT_JUDGE_THRESHOLD),
            model=model,
        ),
    }
    return [builders[name]() for name in include]


def check_judge_ready(
    *,
    max_llm_calls: int = 1,
    include: tuple[str, ...] | list[str] = METRIC_NAMES,
) -> None:
    """Fail closed before any judge work: dep installed, key set, budget ok."""
    _load_deepeval()
    if not os.environ.get("OPENAI_API_KEY"):
        raise JudgeError(
            "OPENAI_API_KEY is not set. The judge path needs it: DeepEval's "
            "metric constructors demand a key, and the task-completion judge "
            "makes a real (billable) model call. A dummy key is enough for "
            "the deterministic tool-correctness metric alone, but the judge "
            "needs a real key."
        )
    include = _validate_include(include)
    needed = sum(_LLM_CALLS_PER_METRIC[name] for name in include)
    if needed > max_llm_calls:
        raise JudgeError(
            f"judge budget exceeded: the requested judge metrics need "
            f"{needed} LLM call(s) but max_llm_calls={max_llm_calls}. "
            f"Raise --judge-max-calls or drop 'task_completion' from "
            f"--judge-metrics."
        )


def run_judge(
    trace: Trace,
    *,
    model: str | None = None,
    max_llm_calls: int = 1,
    thresholds: dict[str, float] | None = None,
    include: tuple[str, ...] | list[str] = METRIC_NAMES,
) -> tuple[MetricResult, ...]:
    """Run DeepEval's judge metrics over a trace; returns judge results.

    Fails closed (``JudgeError``) before any model call when deepeval is
    missing, no key is set, or the budget does not cover the work.
    """
    include = _validate_include(include)
    check_judge_ready(max_llm_calls=max_llm_calls, include=include)
    test_case = trace_to_test_case(trace)
    metrics = judge_metrics(model=model, thresholds=thresholds, include=include)
    results = []
    for name, metric in zip(include, metrics):
        metric.measure(test_case)
        reason = (getattr(metric, "reason", "") or "").strip()
        reason = " ".join(reason.split())  # library reasons span lines; keep one line
        if len(reason) > _REASON_MAX_LEN:
            reason = reason[:_REASON_MAX_LEN].rstrip() + " …"
        score = float(metric.score)
        threshold = float(getattr(metric, "threshold", _DEFAULT_JUDGE_THRESHOLD))
        results.append(
            MetricResult(
                name=f"judge_{name}",
                score=score,
                threshold=threshold,
                passed=score >= threshold,
                details=reason or f"DeepEval {name} score {score:.2f}",
            )
        )
    return tuple(results)


def evaluate_run_with_judge(
    trace: Trace,
    *,
    model: str | None = None,
    max_llm_calls: int = 1,
    thresholds: dict[str, float] | None = None,
    judge_thresholds: dict[str, float] | None = None,
    include: tuple[str, ...] | list[str] = METRIC_NAMES,
) -> EvalReport:
    """Native $0 gate + opt-in DeepEval judge metrics, one combined report.

    The trace hash is the native report's hash, so a judge run stays
    comparable to a $0 run of the same trace; only the judge scores vary.
    """
    native = evaluate_run(trace, thresholds=thresholds)
    judge_results = run_judge(
        trace,
        model=model,
        max_llm_calls=max_llm_calls,
        thresholds=judge_thresholds,
        include=include,
    )
    return EvalReport(
        run_id=native.run_id,
        seed=native.seed,
        trace_hash=native.trace_hash,
        metrics=native.metrics + judge_results,
    )
