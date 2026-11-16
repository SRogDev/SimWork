"""Tests for the scripted LLM layer (Phase 1 skeleton).

The scripted LLM is SimWork's own deterministic mock: a fixed script of
turns, replayed in order, failing closed when the script runs out.
The fake server exposes it as an OpenAI-compatible
`POST /v1/chat/completions` endpoint so an unmodified harness can point
at it with a base-URL swap.
"""

import json
import urllib.error
import urllib.request

import pytest

from simwork.llm import FakeOpenAIServer, ScriptedLLM, ScriptExhaustedError

SCRIPT = [
    {"content": "I will check the ticket."},
    {"tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}]},
    {"content": "Your replacement has shipped."},
]

MESSAGES = [{"role": "user", "content": "What's the status of ticket T-123?"}]


def test_same_seed_same_script_same_responses() -> None:
    first = ScriptedLLM(SCRIPT, seed=7)
    second = ScriptedLLM(SCRIPT, seed=7)
    assert [first.complete(MESSAGES) for _ in SCRIPT] == [
        second.complete(MESSAGES) for _ in SCRIPT
    ]


def test_script_order_and_tool_call_shape() -> None:
    llm = ScriptedLLM(SCRIPT, seed=7)
    text = llm.complete(MESSAGES)
    assert text["choices"][0]["message"]["content"] == "I will check the ticket."
    assert text["choices"][0]["finish_reason"] == "stop"

    tool_turn = llm.complete(MESSAGES)
    choice = tool_turn["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "lookup_ticket"
    assert json.loads(call["function"]["arguments"]) == {"ticket_id": "T-123"}


def test_exhausted_script_fails_closed() -> None:
    llm = ScriptedLLM(SCRIPT, seed=7)
    for _ in SCRIPT:
        llm.complete(MESSAGES)
    with pytest.raises(ScriptExhaustedError):
        llm.complete(MESSAGES)


def test_reset_replays_deterministically() -> None:
    llm = ScriptedLLM(SCRIPT, seed=7)
    first_run = [llm.complete(MESSAGES) for _ in SCRIPT]
    llm.reset()
    assert [llm.complete(MESSAGES) for _ in SCRIPT] == first_run


def test_complete_records_calls() -> None:
    llm = ScriptedLLM(SCRIPT, seed=7)
    llm.complete(MESSAGES)
    llm.complete(MESSAGES)
    assert llm.calls == [MESSAGES, MESSAGES]


def _post(base_url: str, path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_server_serves_openai_shaped_completion() -> None:
    with FakeOpenAIServer(SCRIPT, seed=7).start() as server:
        status, body = _post(
            server.base_url,
            "/chat/completions",
            {"model": "gpt-4o-mini", "messages": MESSAGES},
        )
        assert status == 200
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["choices"][0]["message"]["content"] == "I will check the ticket."

        status, body = _post(
            server.base_url,
            "/chat/completions",
            {"model": "gpt-4o-mini", "messages": MESSAGES},
        )
        assert status == 200
        assert body["choices"][0]["finish_reason"] == "tool_calls"


def test_server_rejects_unknown_paths() -> None:
    with FakeOpenAIServer(SCRIPT, seed=7).start() as server:
        status, _ = _post(
            server.base_url, "/v1/other", {"model": "gpt-4o-mini", "messages": MESSAGES}
        )
        assert status == 404


def test_server_exhausted_script_is_a_visible_error() -> None:
    with FakeOpenAIServer(SCRIPT[:1], seed=7).start() as server:
        _post(server.base_url, "/chat/completions", {"model": "x", "messages": MESSAGES})
        status, body = _post(
            server.base_url, "/chat/completions", {"model": "x", "messages": MESSAGES}
        )
        assert status == 500
        assert "error" in body
