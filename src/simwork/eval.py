"""DeepEval harness, first slice (Phase 3, task 1).

Evaluates a recorded run trace with two deterministic metrics — tool
correctness and task completion — and produces a pass/fail report.
No LLM judge, no network, $0 by default.

Why the metrics are computed natively: DeepEval 4.3.4 was verified
2026-11-17 to require an ``OPENAI_API_KEY`` at construction of its own
``ToolCorrectnessMetric`` (its ``measure()`` is deterministic and works
offline with a dummy key, but demanding a key at construction breaks
SimWork's $0 / no-secrets default), and its ``TaskCompletionMetric`` is
an LLM judge. The metric names and semantics below match DeepEval's:
tool correctness is the share of expected tool calls matched exactly
(name + arguments); task completion is whether the run's final answer
covers the expected facts. DeepEval's own classes are wired for the
opt-in judge path in ``simwork.deepeval_judge`` (``simwork eval
--judge``); the $0 gate here never imports them.
See ``docs/deepeval-wiring-2026-11-17.md``.

The report carries a ``trace_hash`` (SHA-256 of the canonical JSON of
the trace) so the spec's acceptance criterion holds: same seed + same
scenario run twice produces an identical trace hash and identical
eval report.

The trace shape itself — parse, validate, hash, steps, final answer —
is owned by ``simwork.trace``; this module only evaluates a trace
through that interface.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from simwork.trace import Trace, final_answer, tool_calls, trace_hash, validate_trace

_DEFAULT_THRESHOLD = 1.0
# The metric names, shared with the opt-in judge adapter
# (`simwork.deepeval_judge`): one source of truth for both adapters, so
# a metric cannot be spelled one way natively and another by the judge.
METRIC_NAMES = ("tool_correctness", "task_completion")


@dataclass(frozen=True)
class MetricResult:
    """One metric's outcome: score in [0, 1] against its threshold."""

    name: str
    score: float
    threshold: float
    passed: bool
    details: str


@dataclass(frozen=True)
class EvalReport:
    """Pass/fail report for one evaluated trace."""

    run_id: str | None
    seed: int
    trace_hash: str
    metrics: tuple[MetricResult, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """The gate passes only when every metric passes."""
        return all(m.passed for m in self.metrics)

    def metric(self, name: str) -> MetricResult:
        """Return one metric's result by name."""
        for result in self.metrics:
            if result.name == name:
                return result
        raise KeyError(f"no metric named {name!r} in this report")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "seed": self.seed,
            "trace_hash": self.trace_hash,
            "passed": self.passed,
            "metrics": [
                {
                    "name": m.name,
                    "score": m.score,
                    "threshold": m.threshold,
                    "passed": m.passed,
                    "details": m.details,
                }
                for m in self.metrics
            ],
        }

    def to_json(self) -> str:
        """Machine-readable report (stable key order, deterministic)."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def to_text(self) -> str:
        """Human-readable report."""
        lines = [
            f"SimWork eval report — run: {self.run_id or '(unnamed)'} (seed {self.seed})",
            f"trace: {self.trace_hash}",
        ]
        for m in self.metrics:
            verdict = "PASS" if m.passed else "FAIL"
            lines.append(
                f"  {m.name}: {m.score:.2f} (threshold {m.threshold:.2f}) {verdict} — {m.details}"
            )
        lines.append(f"Overall: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines) + "\n"


def unknown_metric_names(names: Iterable[str]) -> list[str]:
    """Names in ``names`` that are not one of ``METRIC_NAMES``.

    Shared with the judge adapter so both adapters reject the same
    unknown names; each caller raises its own error type.
    """
    return [name for name in names if name not in METRIC_NAMES]


def evaluate_run(trace: Trace, *, thresholds: dict[str, float] | None = None) -> EvalReport:
    """Evaluate a validated trace and return the pass/fail report.

    Thresholds default to 1.0 (strict gate); pass ``thresholds`` to
    relax one metric, e.g. ``{"tool_correctness": 0.5}``.
    """
    trace = validate_trace(trace)
    thresholds = thresholds or {}
    unknown = unknown_metric_names(thresholds)
    if unknown:
        raise ValueError(f"unknown metric(s) in thresholds: {sorted(unknown)}")
    results = (
        _tool_correctness(trace, thresholds.get("tool_correctness", _DEFAULT_THRESHOLD)),
        _task_completion(trace, thresholds.get("task_completion", _DEFAULT_THRESHOLD)),
    )
    return EvalReport(
        run_id=trace.get("run_id"),
        seed=trace.get("seed", 0),
        trace_hash=trace_hash(trace),
        metrics=results,
    )


def _tool_call_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return actual.get("name") == expected.get("name") and actual.get(
        "arguments", {}
    ) == expected.get("arguments", {})


def _tool_correctness(trace: Trace, threshold: float) -> MetricResult:
    expected = trace.get("expected", {}).get("tool_calls", [])
    actual = tool_calls(trace)
    if not expected:
        score = 1.0 if not actual else 0.0
        details = (
            "no tool calls expected and none made"
            if not actual
            else f"no tool calls expected but {len(actual)} made"
        )
    else:
        remaining = list(actual)
        matched = 0
        for want in expected:
            for i, got in enumerate(remaining):
                if _tool_call_matches(got, want):
                    matched += 1
                    del remaining[i]
                    break
        score = matched / len(expected)
        details = f"{matched}/{len(expected)} expected tool call(s) matched"
    return MetricResult(
        name="tool_correctness",
        score=score,
        threshold=threshold,
        passed=score >= threshold,
        details=details,
    )


def _task_completion(trace: Trace, threshold: float) -> MetricResult:
    wanted = trace.get("expected", {}).get("final_answer_contains", [])
    answer = final_answer(trace)
    missing = [s for s in wanted if s not in answer]
    score = 1.0 if not missing else 0.0
    details = (
        "final answer contains all expected facts"
        if not missing
        else f"final answer missing: {missing}"
    )
    return MetricResult(
        name="task_completion",
        score=score,
        threshold=threshold,
        passed=score >= threshold,
        details=details,
    )
