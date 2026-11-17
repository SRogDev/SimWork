"""Trace capture from a simulated run (Phase 3, task 2).

`simwork eval` evaluates a recorded run trace — until now those traces
had to be hand-written. A `TraceRecorder` captures one from a real
simulated run instead: assistant steps come from the completions the
scripted LLM returns (`record_completion`, or automatically when the
recorder is handed to `ScriptedLLM` / `FakeOpenAIServer` /
`SimWorkRouter`), and tool-result steps come from the harness executing
the tools the LLM asked for (`record_tool_result`).

The trace a recorder produces is the trace format `simwork.eval`
validates, so a captured run feeds straight into `simwork eval` —
same seed + same scenario run twice produces the same trace hash and
the same report. No LLM judge, no network, $0.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from simwork.eval import TraceError, validate_trace


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

    def to_trace(self, *, expected: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the recorded run as a validated eval trace dict."""
        if not self._steps:
            raise TraceError("no steps recorded yet — nothing to evaluate")
        trace: dict[str, Any] = {
            "run_id": self.run_id,
            "seed": self.seed,
            "steps": copy.deepcopy(self._steps),
        }
        if self.run_id is None:
            del trace["run_id"]
        if expected is not None:
            trace["expected"] = copy.deepcopy(expected)
        return validate_trace(trace)

    def save(self, path: str | Path, *, expected: dict[str, Any] | None = None) -> dict[str, Any]:
        """Write the recorded trace as canonical JSON; returns the trace."""
        trace = self.to_trace(expected=expected)
        path = Path(path)
        try:
            path.write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as e:
            raise TraceError(f"cannot write trace file {path}: {e}") from e
        return trace
