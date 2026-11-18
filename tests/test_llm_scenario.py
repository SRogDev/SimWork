"""Tests for YAML scenario loading (Phase 1, task 2).

Scenarios are defined in files, not code (spec §4): a YAML file declares
the scripted turns a `ScriptedLLM` replays. Loading is strict and fails
closed — a bad schema raises `ScenarioError` instead of silently
producing a wrong script.
"""

from pathlib import Path

import pytest

from simwork.llm import ScenarioError, load_scenario, parse_scenario

VALID_YAML = """\
name: ticket-status
seed: 7
model: simwork-mock
turns:
  - content: "I will check the ticket."
  - tool_calls:
      - name: lookup_ticket
        arguments:
          ticket_id: T-123
  - content: "Your replacement has shipped."
"""

MESSAGES = [{"role": "user", "content": "What's the status of ticket T-123?"}]


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "scenario.yaml"
    path.write_text(text)
    return path


def test_valid_scenario_loads_turns_seed_and_model(tmp_path: Path) -> None:
    scenario = load_scenario(_write(tmp_path, VALID_YAML))
    assert scenario.name == "ticket-status"
    assert scenario.seed == 7
    assert scenario.model == "simwork-mock"
    assert scenario.turns == [
        {"content": "I will check the ticket."},
        {"tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}]},
        {"content": "Your replacement has shipped."},
    ]


def test_defaults_when_optional_keys_missing() -> None:
    scenario = parse_scenario("turns:\n  - content: hi\n")
    assert scenario.name is None
    assert scenario.seed == 0
    assert scenario.model == "simwork-mock"


def test_tool_call_without_arguments_defaults_to_empty_dict() -> None:
    scenario = parse_scenario("turns:\n  - tool_calls:\n      - name: ping\n")
    assert scenario.turns == [{"tool_calls": [{"name": "ping", "arguments": {}}]}]


def test_loaded_scenario_replays_deterministically(tmp_path: Path) -> None:
    first = load_scenario(_write(tmp_path, VALID_YAML)).to_llm()
    second = load_scenario(_write(tmp_path, VALID_YAML)).to_llm()
    assert [first.complete(MESSAGES) for _ in range(3)] == [
        second.complete(MESSAGES) for _ in range(3)
    ]


def test_to_llm_passes_recorder_to_the_llm(tmp_path: Path) -> None:
    """The recorder reaches the LLM through the scenario, not the server.

    A server built from this LLM records the run; the server itself
    takes no recorder anymore (candidate 5).
    """
    from simwork.trace import TraceRecorder

    recorder = TraceRecorder(run_id="r", seed=7)
    llm = load_scenario(_write(tmp_path, VALID_YAML)).to_llm(recorder=recorder)
    llm.complete(MESSAGES)
    assert recorder.to_trace()["steps"] == [
        {"type": "assistant", "content": "I will check the ticket."}
    ]


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ScenarioError):
        load_scenario(tmp_path / "no-such-file.yaml")


def test_invalid_yaml_fails_closed() -> None:
    with pytest.raises(ScenarioError):
        parse_scenario("turns: [unclosed")


def test_top_level_must_be_a_mapping() -> None:
    with pytest.raises(ScenarioError):
        parse_scenario("- just\n- a\n- list\n")


@pytest.mark.parametrize(
    "yaml_text",
    [
        "name: no-turns\n",  # missing turns
        "turns: []\n",  # empty turns
        "turns: not-a-list\n",  # turns not a list
        "turns:\n  - {}\n",  # turn with neither content nor tool_calls
        "turns:\n  - content: a\n    tool_calls:\n      - name: x\n",  # both
        "turns:\n  - content: 42\n",  # content not a string
        "turns:\n  - tool_calls: []\n",  # empty tool_calls
        "turns:\n  - tool_calls:\n      - arguments: {}\n",  # tool call without name
        "turns:\n  - tool_calls:\n      - name: x\n        arguments: not-a-map\n",
        "turns:\n  - content: hi\n    extra: nope\n",  # unknown turn key
        "turns:\n  - content: hi\nseed: not-an-int\n",  # seed not an int
        "turns:\n  - content: hi\nseed: true\n",  # bool is not an int here
        "turns:\n  - content: hi\nunknown_key: 1\n",  # unknown top-level key
    ],
)
def test_bad_schema_fails_closed(yaml_text: str) -> None:
    with pytest.raises(ScenarioError):
        parse_scenario(yaml_text)


def test_loaded_turns_are_copies_not_aliases(tmp_path: Path) -> None:
    scenario = load_scenario(_write(tmp_path, VALID_YAML))
    scenario.turns[0]["content"] = "mutated"
    reloaded = load_scenario(_write(tmp_path, VALID_YAML))
    assert reloaded.turns[0]["content"] == "I will check the ticket."
