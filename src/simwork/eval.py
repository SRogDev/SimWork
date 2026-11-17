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
covers the expected facts. Wiring DeepEval's own classes (pytest-native
``evaluate()`` / LLM-judge metrics) is a later Phase 3 task, opt-in.
See ``docs/deepeval-wiring-2026-11-17.md``.

Trace format (JSON, strict — anything invalid fails closed)::

    {
      "run_id": "ticket-status-1",   // optional
      "seed": 7,                     // optional, default 0
      "steps": [                     // required, non-empty
        {"type": "assistant", "content": "I will check the ticket."},
        {"type": "assistant",
         "tool_calls": [{"name": "lookup_ticket",
                         "arguments": {"ticket_id": "T-123"}}]},
        {"type": "tool_result", "name": "lookup_ticket",
         "result": {"status": "shipped"}},
        {"type": "assistant", "content": "Your replacement has shipped."}
      ],
      "expected": {                  // optional
        "tool_calls": [{"name": "lookup_ticket",
                        "arguments": {"ticket_id": "T-123"}}],
        "final_answer_contains": ["shipped"]
      }
    }

The report carries a ``trace_hash`` (SHA-256 of the canonical JSON of
the trace) so the spec's acceptance criterion holds: same seed + same
scenario run twice produces an identical trace hash and identical
eval report.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_THRESHOLD = 1.0
_METRIC_NAMES = ("tool_correctness", "task_completion")
_TOP_LEVEL_KEYS = {"run_id", "seed", "steps", "expected"}
_EXPECTED_KEYS = {"tool_calls", "final_answer_contains"}
_STEP_TYPES = ("assistant", "tool_result")


class TraceError(ValueError):
    """Raised when a trace file is missing, unparseable, or invalid."""


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


def load_trace(path: str | Path) -> dict[str, Any]:
    """Load and validate a trace from a JSON file (fails closed)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise TraceError(f"cannot read trace file {path}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise TraceError(f"{path}: invalid JSON: {e}") from e
    return validate_trace(data, source=str(path))


def validate_trace(data: Any, *, source: str = "<trace>") -> dict[str, Any]:
    """Validate a parsed trace dict; returns it unchanged if valid."""
    if not isinstance(data, dict):
        raise TraceError(f"{source}: trace must be a mapping, got {type(data).__name__}")
    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise TraceError(f"{source}: unknown top-level key(s): {sorted(unknown)}")
    if not isinstance(data.get("steps"), list) or not data["steps"]:
        raise TraceError(f"{source}: 'steps' must be a non-empty list")
    for i, step in enumerate(data["steps"]):
        _validate_step(step, i, source)
    if "expected" in data:
        if not isinstance(data["expected"], dict):
            raise TraceError(f"{source}: 'expected' must be a mapping")
        unknown_expected = set(data["expected"]) - _EXPECTED_KEYS
        if unknown_expected:
            raise TraceError(f"{source}: unknown 'expected' key(s): {sorted(unknown_expected)}")
        _validate_tool_calls(data["expected"].get("tool_calls", []), source, "expected")
        final = data["expected"].get("final_answer_contains", [])
        if not isinstance(final, list) or not all(isinstance(s, str) for s in final):
            raise TraceError(
                f"{source}: 'expected.final_answer_contains' must be a list of strings"
            )
    if "seed" in data and (isinstance(data["seed"], bool) or not isinstance(data["seed"], int)):
        raise TraceError(f"{source}: 'seed' must be an integer")
    if "run_id" in data and not isinstance(data["run_id"], str):
        raise TraceError(f"{source}: 'run_id' must be a string")
    return data


def evaluate_run(
    trace: dict[str, Any], *, thresholds: dict[str, float] | None = None
) -> EvalReport:
    """Evaluate a validated trace and return the pass/fail report.

    Thresholds default to 1.0 (strict gate); pass ``thresholds`` to
    relax one metric, e.g. ``{"tool_correctness": 0.5}``.
    """
    trace = validate_trace(trace)
    thresholds = thresholds or {}
    unknown = set(thresholds) - set(_METRIC_NAMES)
    if unknown:
        raise ValueError(f"unknown metric(s) in thresholds: {sorted(unknown)}")
    results = (
        _tool_correctness(trace, thresholds.get("tool_correctness", _DEFAULT_THRESHOLD)),
        _task_completion(trace, thresholds.get("task_completion", _DEFAULT_THRESHOLD)),
    )
    return EvalReport(
        run_id=trace.get("run_id"),
        seed=trace.get("seed", 0),
        trace_hash=_trace_hash(trace),
        metrics=results,
    )


def _trace_hash(trace: dict[str, Any]) -> str:
    canonical = json.dumps(trace, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _actual_tool_calls(trace: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for step in trace["steps"]:
        calls.extend(step.get("tool_calls", []))
    return calls


def _tool_call_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return actual.get("name") == expected.get("name") and actual.get(
        "arguments", {}
    ) == expected.get("arguments", {})


def _tool_correctness(trace: dict[str, Any], threshold: float) -> MetricResult:
    expected = trace.get("expected", {}).get("tool_calls", [])
    actual = _actual_tool_calls(trace)
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


def _final_answer(trace: dict[str, Any]) -> str:
    for step in reversed(trace["steps"]):
        if step.get("type") == "assistant" and isinstance(step.get("content"), str):
            return step["content"]
    return ""


def _task_completion(trace: dict[str, Any], threshold: float) -> MetricResult:
    wanted = trace.get("expected", {}).get("final_answer_contains", [])
    answer = _final_answer(trace)
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


def _validate_step(step: Any, index: int, source: str) -> None:
    if not isinstance(step, dict):
        raise TraceError(f"{source}: step {index} must be a mapping")
    step_type = step.get("type")
    if step_type not in _STEP_TYPES:
        raise TraceError(f"{source}: step {index} has unknown step type {step_type!r}")
    unknown = set(step) - {"type", "content", "tool_calls", "name", "result"}
    if unknown:
        raise TraceError(f"{source}: step {index} has unknown key(s): {sorted(unknown)}")
    if step_type == "assistant":
        if "content" in step and not isinstance(step["content"], str):
            raise TraceError(f"{source}: step {index} 'content' must be a string")
        if "tool_calls" in step:
            _validate_tool_calls(step["tool_calls"], source, f"step {index}")
        if "content" not in step and "tool_calls" not in step:
            raise TraceError(f"{source}: step {index} needs 'content' and/or 'tool_calls'")
    else:  # tool_result
        if not isinstance(step.get("name"), str):
            raise TraceError(f"{source}: step {index} 'name' must be a string")


def _validate_tool_calls(calls: Any, source: str, where: str) -> None:
    if not isinstance(calls, list):
        raise TraceError(f"{source}: {where} 'tool_calls' must be a list")
    for i, call in enumerate(calls):
        if not isinstance(call, dict):
            raise TraceError(f"{source}: {where} tool call {i} must be a mapping")
        if not isinstance(call.get("name"), str):
            raise TraceError(f"{source}: {where} tool call {i} 'name' must be a string")
        if "arguments" in call and not isinstance(call["arguments"], dict):
            raise TraceError(f"{source}: {where} tool call {i} 'arguments' must be a mapping")
