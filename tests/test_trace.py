"""Tests for trace capture from a simulated run (Phase 3, task 2).

A `TraceRecorder` turns a simulated run into the trace format
`simwork eval` already evaluates: assistant steps come from the
completions the scripted LLM returns, tool-result steps come from the
harness executing the called tools. No LLM judge, no network, $0.
"""

import json
import urllib.error
import urllib.request

import pytest

from simwork.eval import evaluate_run
from simwork.llm import FakeOpenAIServer, ScriptedLLM
from simwork.routing import SimWorkConfig, SimWorkRouter
from simwork.trace import (
    TraceError,
    TraceRecorder,
    completion_to_step,
    final_answer,
    load_trace,
    tool_calls,
    trace_hash,
)

SCRIPT = [
    {"content": "I will check the ticket."},
    {"tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}]},
    {"content": "Your replacement has shipped."},
]

MESSAGES = [{"role": "user", "content": "What's the status of ticket T-123?"}]

EXPECTED = {
    "tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}],
    "final_answer_contains": ["shipped"],
}

EXAMPLE_HASH = "b0122a56efdfda2a9df27860cb73344c05f1855f6e36622b76b7d1bcca7bd5e0"


def _run_ticket_loop(*, seed: int = 7) -> TraceRecorder:
    """The demo agent loop: scripted LLM + one fake tool, recorded.

    Mirrors what a real harness does — call the LLM, execute the tool
    it asks for, feed the result back — with every step recorded.
    """
    llm = ScriptedLLM(SCRIPT, seed=seed)
    recorder = TraceRecorder(run_id="ticket-status-1", seed=seed)
    messages = list(MESSAGES)
    for _ in range(len(SCRIPT)):
        completion = llm.complete(messages)
        recorder.record_completion(completion)
        step = completion_to_step(completion)
        for call in step.get("tool_calls", []):
            assert call["name"] == "lookup_ticket"  # the demo's only tool
            result = {"status": "shipped"}
            recorder.record_tool_result(call["name"], result)
            messages.append(
                {"role": "tool", "tool_call_id": "call-x", "content": json.dumps(result)}
            )
    return recorder


def test_completion_to_step_content_turn() -> None:
    llm = ScriptedLLM(SCRIPT, seed=7)
    step = completion_to_step(llm.complete(MESSAGES))
    assert step == {"type": "assistant", "content": "I will check the ticket."}


def test_completion_to_step_tool_calls_turn_parses_arguments() -> None:
    llm = ScriptedLLM(SCRIPT, seed=7)
    llm.complete(MESSAGES)
    step = completion_to_step(llm.complete(MESSAGES))
    assert step == {
        "type": "assistant",
        "tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}],
    }


def test_completion_to_step_rejects_missing_choices() -> None:
    with pytest.raises(TraceError, match="choices"):
        completion_to_step({})


def test_completion_to_step_rejects_empty_message() -> None:
    completion = {"choices": [{"message": {"role": "assistant", "content": None}}]}
    with pytest.raises(TraceError, match="no content and no tool_calls"):
        completion_to_step(completion)


def test_completion_to_step_rejects_bad_arguments_json() -> None:
    completion = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "lookup_ticket", "arguments": "{bad"},
                        }
                    ],
                }
            }
        ]
    }
    with pytest.raises(TraceError, match="arguments"):
        completion_to_step(completion)


def test_recorder_builds_trace_with_expected() -> None:
    recorder = _run_ticket_loop()
    trace = recorder.to_trace(expected=EXPECTED)
    assert trace["run_id"] == "ticket-status-1"
    assert trace["seed"] == 7
    assert trace["steps"] == [
        {"type": "assistant", "content": "I will check the ticket."},
        {
            "type": "assistant",
            "tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}],
        },
        {"type": "tool_result", "name": "lookup_ticket", "result": {"status": "shipped"}},
        {"type": "assistant", "content": "Your replacement has shipped."},
    ]
    assert trace["expected"] == EXPECTED


def test_recorder_to_trace_empty_fails_closed() -> None:
    with pytest.raises(TraceError, match="no steps recorded"):
        TraceRecorder().to_trace()


def test_recorder_rejects_non_json_tool_result() -> None:
    recorder = TraceRecorder()
    with pytest.raises(TraceError, match="JSON-serializable"):
        recorder.record_tool_result("lookup_ticket", object())


def test_recorder_save_load_round_trip(tmp_path) -> None:
    recorder = _run_ticket_loop()
    path = tmp_path / "trace.json"
    saved = recorder.save(path, expected=EXPECTED)
    assert load_trace(path) == saved
    assert saved == recorder.to_trace(expected=EXPECTED)


def test_load_trace_accepts_valid_file(tmp_path):
    trace = _run_ticket_loop().to_trace(expected=EXPECTED)
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    assert load_trace(path) == trace


def test_load_trace_missing_file_fails_closed(tmp_path):
    with pytest.raises(TraceError, match="cannot read trace"):
        load_trace(tmp_path / "nope.json")


def test_load_trace_invalid_json_fails_closed(tmp_path):
    path = tmp_path / "trace.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(TraceError, match="invalid JSON"):
        load_trace(path)


def test_load_trace_rejects_unknown_top_level_key(tmp_path):
    trace = _run_ticket_loop().to_trace(expected=EXPECTED)
    trace["surprise"] = True
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    with pytest.raises(TraceError, match="unknown top-level key"):
        load_trace(path)


def test_load_trace_rejects_empty_steps(tmp_path):
    trace = _run_ticket_loop().to_trace(expected=EXPECTED)
    trace["steps"] = []
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    with pytest.raises(TraceError, match="non-empty"):
        load_trace(path)


def test_load_trace_rejects_unknown_step_type(tmp_path):
    trace = _run_ticket_loop().to_trace(expected=EXPECTED)
    trace["steps"][0] = {"type": "mystery", "content": "?"}
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    with pytest.raises(TraceError, match="unknown step type"):
        load_trace(path)


def test_trace_hash_matches_example() -> None:
    assert trace_hash(_run_ticket_loop().to_trace(expected=EXPECTED)) == EXAMPLE_HASH


def test_tool_calls_collects_from_steps() -> None:
    trace = _run_ticket_loop().to_trace(expected=EXPECTED)
    assert tool_calls(trace) == [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}]


def test_final_answer_returns_last_assistant_content() -> None:
    trace = _run_ticket_loop().to_trace(expected=EXPECTED)
    assert final_answer(trace) == "Your replacement has shipped."


def test_final_answer_empty_when_no_assistant_content() -> None:
    assert final_answer({"steps": [{"type": "tool_result", "name": "x", "result": {}}]}) == ""


def test_scripted_llm_records_each_turn_when_given_a_recorder() -> None:
    recorder = TraceRecorder(run_id="r", seed=7)
    llm = ScriptedLLM(SCRIPT, seed=7, recorder=recorder)
    for _ in SCRIPT:
        llm.complete(MESSAGES)
    assert len(recorder.to_trace()["steps"]) == 3
    assert recorder.to_trace()["steps"][1]["tool_calls"][0]["name"] == "lookup_ticket"


def test_fake_server_records_completions_over_http() -> None:
    recorder = TraceRecorder(run_id="r", seed=7)
    with FakeOpenAIServer(ScriptedLLM(SCRIPT, seed=7, recorder=recorder)).start() as server:
        req = urllib.request.Request(
            f"{server.base_url}/chat/completions",
            data=json.dumps({"model": "x", "messages": MESSAGES}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
        except urllib.error.HTTPError as e:  # pragma: no cover - server must answer 200
            raise AssertionError(f"unexpected HTTP {e.code}") from e
    steps = recorder.to_trace()["steps"]
    assert steps == [{"type": "assistant", "content": "I will check the ticket."}]


def test_simulated_run_loop_produces_evaluable_trace() -> None:
    """A captured trace is exactly the trace `simwork eval` evaluates.

    The recorded run reproduces the hand-written example trace
    (same steps, same hash) and passes the eval gate.
    """
    recorder = _run_ticket_loop()
    trace = recorder.to_trace(expected=EXPECTED)
    with open("examples/ticket-status-trace.json", encoding="utf-8") as f:
        example = json.load(f)
    assert trace == example
    report = evaluate_run(trace)
    assert report.trace_hash == EXAMPLE_HASH
    assert report.passed
    assert report.metric("tool_correctness").score == 1.0
    assert report.metric("task_completion").score == 1.0


def test_same_seed_same_run_same_trace_hash() -> None:
    first = evaluate_run(_run_ticket_loop().to_trace(expected=EXPECTED))
    second = evaluate_run(_run_ticket_loop().to_trace(expected=EXPECTED))
    assert first.trace_hash == second.trace_hash
    assert first.to_json() == second.to_json()


def test_router_passes_recorder_to_fake_server(tmp_path) -> None:
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(
        'name: ticket-status\nseed: 7\nturns:\n  - content: "I will check the ticket."\n',
        encoding="utf-8",
    )
    config = SimWorkConfig(mode="simulate", scenario_path=scenario)
    recorder = TraceRecorder(run_id="router-run", seed=7)
    with SimWorkRouter(config, recorder=recorder) as router:
        assert router.base_url is not None
        req = urllib.request.Request(
            f"{router.base_url}/chat/completions",
            data=json.dumps({"model": "x", "messages": MESSAGES}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
    assert recorder.to_trace()["steps"] == [
        {"type": "assistant", "content": "I will check the ticket."}
    ]
