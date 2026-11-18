"""Trace capture from a simulated run (Phase 3, task 2) — and the trace
itself (architecture review 2026-11-18, candidate 2).

The trace is SimWork's central domain concept: a recorded run, as a
JSON object with ``steps`` (assistant turns, with ``content`` and/or
``tool_calls``, plus ``tool_result`` steps) and ``expected`` (the tool
calls the run should have made, the facts the final answer should
cover). This module owns that shape — parse it, validate it, hash it,
read its steps and final answer — and every other module consumes it
through this interface instead of re-implementing the shape:

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

- `TraceRecorder` captures a trace from a real simulated run:
  assistant steps come from the completions the scripted LLM returns
  (`record_completion`, or automatically when the recorder is handed
  to `ScriptedLLM` — directly, or via `Scenario.to_llm()` /
  `SimWorkRouter`), and tool-result steps come from the harness executing
  the harness executing the tools the LLM asked for
  (`record_tool_result`).
- `simwork.eval` evaluates a trace with the $0 metrics; it never
  validates or hashes one itself.
- `simwork.deepeval_judge` converts a trace into a DeepEval test case
  through `tool_calls` / `final_answer` here.
- `simwork.init` validates its starter trace through `validate_trace`.

A captured run feeds straight into `simwork eval` — same seed + same
scenario run twice produces the same trace hash and the same report.
No LLM judge, no network, $0.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

# The trace shape: a JSON object (see the module docstring). It travels
# as a plain dict because it is read from and written to JSON files;
# the alias names the domain concept at every seam instead of leaving
# `dict[str, Any]` everywhere.
Trace = dict[str, Any]

_TOP_LEVEL_KEYS = {"run_id", "seed", "steps", "expected"}
_EXPECTED_KEYS = {"tool_calls", "final_answer_contains"}
_STEP_TYPES = ("assistant", "tool_result")


class TraceError(ValueError):
    """Raised when a trace file is missing, unparseable, or invalid."""


def validate_trace(data: Any, *, source: str = "<trace>") -> Trace:
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


def load_trace(path: str | Path) -> Trace:
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


def trace_hash(trace: Trace) -> str:
    """SHA-256 of the canonical JSON of the trace (stable key order).

    Same seed + same scenario run twice produces the same hash, so a
    report for the same run is comparable across runs.
    """
    canonical = json.dumps(trace, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def final_answer(trace: Trace) -> str:
    """The run's final answer: the last assistant step's content, or ""."""
    for step in reversed(trace["steps"]):
        if step.get("type") == "assistant" and isinstance(step.get("content"), str):
            return step["content"]
    return ""


def tool_calls(trace: Trace) -> list[dict[str, Any]]:
    """Every tool call the run's assistant steps made, in order."""
    calls: list[dict[str, Any]] = []
    for step in trace["steps"]:
        calls.extend(step.get("tool_calls", []))
    return calls


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


def completion_to_step(completion: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAI chat-completion dict into one trace step.

    The assistant message's ``content`` becomes the step's ``content``
    and each function ``tool_calls`` entry becomes a trace tool call
    with its ``arguments`` parsed from the JSON string the API carries.
    Fails closed (`TraceError`) on a malformed completion instead of
    recording a wrong step.
    """
    try:
        message = completion["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise TraceError(f"completion has no choices[0].message: {completion!r}") from e
    if not isinstance(message, dict):
        raise TraceError(f"completion message must be a mapping, got {message!r}")
    step: dict[str, Any] = {"type": "assistant"}
    content = message.get("content")
    if content is not None:
        if not isinstance(content, str):
            raise TraceError(f"completion content must be a string, got {content!r}")
        step["content"] = content
    raw_calls = message.get("tool_calls") or []
    if not isinstance(raw_calls, list):
        raise TraceError(f"completion tool_calls must be a list, got {raw_calls!r}")
    if raw_calls:
        step["tool_calls"] = [_completion_tool_call(call) for call in raw_calls]
    if "content" not in step and "tool_calls" not in step:
        raise TraceError(f"completion has no content and no tool_calls: {completion!r}")
    return step


def _completion_tool_call(call: Any) -> dict[str, Any]:
    if not isinstance(call, dict):
        raise TraceError(f"tool call must be a mapping, got {call!r}")
    function = call.get("function")
    if not isinstance(function, dict) or not isinstance(function.get("name"), str):
        raise TraceError(f"tool call has no function name: {call!r}")
    arguments = function.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as e:
            raise TraceError(
                f"tool call {function['name']!r} arguments are not valid JSON: {e}"
            ) from e
    if not isinstance(arguments, dict):
        raise TraceError(
            f"tool call {function['name']!r} arguments must be a mapping, got {arguments!r}"
        )
    return {"name": function["name"], "arguments": arguments}


class TraceRecorder:
    """Records the steps of one simulated run as an eval trace.

    The harness (or the scripted LLM, when handed this recorder)
    records each assistant completion, and the harness records each
    tool result after executing a called tool::

        recorder = TraceRecorder(run_id="ticket-status-1", seed=7)
        llm = ScriptedLLM(script, seed=7, recorder=recorder)
        completion = llm.complete(messages)          # assistant step recorded
        recorder.record_tool_result("lookup_ticket", {"status": "shipped"})
        trace = recorder.to_trace(expected={...})     # eval-ready, validated
        report = evaluate_run(trace)                  # pass/fail gate
    """

    def __init__(self, *, run_id: str | None = None, seed: int = 0):
        self.run_id = run_id
        self.seed = seed
        self._steps: list[dict[str, Any]] = []

    @property
    def steps(self) -> list[dict[str, Any]]:
        """The recorded steps so far (a copy)."""
        return copy.deepcopy(self._steps)

    def record_completion(self, completion: dict[str, Any]) -> dict[str, Any]:
        """Record one assistant step from a chat completion; returns it."""
        step = completion_to_step(completion)
        self._steps.append(copy.deepcopy(step))
        return copy.deepcopy(step)

    def record_tool_result(self, name: str, result: Any) -> dict[str, Any]:
        """Record the result of executing a tool the LLM called.

        The result must be JSON-serializable — a trace is JSON — so a
        non-serializable result fails closed here, not later at eval.
        """
        if not isinstance(name, str) or not name:
            raise TraceError("tool result needs a non-empty 'name'")
        try:
            json.dumps(result)
        except (TypeError, ValueError) as e:
            raise TraceError(f"tool result for {name!r} must be JSON-serializable: {e}") from e
        step = {"type": "tool_result", "name": name, "result": copy.deepcopy(result)}
        self._steps.append(step)
        return copy.deepcopy(step)

    def to_trace(self, *, expected: dict[str, Any] | None = None) -> Trace:
        """Return the recorded run as a validated eval trace dict."""
        if not self._steps:
            raise TraceError("no steps recorded yet — nothing to evaluate")
        trace: Trace = {
            "run_id": self.run_id,
            "seed": self.seed,
            "steps": copy.deepcopy(self._steps),
        }
        if self.run_id is None:
            del trace["run_id"]
        if expected is not None:
            trace["expected"] = copy.deepcopy(expected)
        return validate_trace(trace)

    def save(self, path: str | Path, *, expected: dict[str, Any] | None = None) -> Trace:
        """Write the recorded trace as canonical JSON; returns the trace."""
        trace = self.to_trace(expected=expected)
        path = Path(path)
        try:
            path.write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as e:
            raise TraceError(f"cannot write trace file {path}: {e}") from e
        return trace
