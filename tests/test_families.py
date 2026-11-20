"""Tests for scenario families (adoption, readiness criterion 2).

A family is one YAML file that generates many scenarios: named
parameters with value lists, `{{param}}` placeholders in the turns
(and in the optional `expected:` block), and a base seed. Member `i`
gets seed `base + i` and its parameter values from a PRNG seeded with
that member seed — so the same family + index always yields the same
scenario, and a thousand runs are a thousand different situations,
not a thousand copies of one scenario (spec SHOULD, S16).

Loading is strict and fails closed, like scenarios: a bad schema, an
undeclared placeholder, or a non-scalar parameter value raises
`FamilyError` instead of silently producing a wrong member.
"""

from pathlib import Path

import pytest

from simwork.families import FamilyError, load_family, parse_family

FAMILY_YAML = """\
name: ticket-status-family
seed: 7
parameters:
  ticket_id: ["T-101", "T-202", "T-303"]
  status: ["shipped", "processing", "delivered"]
  attempts: [1, 2, 3]
turns:
  - tool_calls:
      - name: lookup_ticket
        arguments: {ticket_id: "{{ticket_id}}", attempts: "{{attempts}}"}
  - content: "Your {{ticket_id}} replacement has {{status}}."
expected:
  tool_calls:
    - name: lookup_ticket
      arguments: {ticket_id: "{{ticket_id}}", attempts: "{{attempts}}"}
  final_answer_contains: ["{{status}}"]
"""

FAMILY_NO_EXPECTED = """\
name: minimal-family
seed: 3
parameters:
  ticket_id: ["T-1", "T-2"]
turns:
  - tool_calls:
      - name: lookup_ticket
        arguments: {ticket_id: "{{ticket_id}}"}
  - content: "Done."
"""


def _write(tmp_path: Path, text: str, name: str = "family.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_valid_family_loads_name_seed_and_parameters(tmp_path: Path) -> None:
    family = load_family(_write(tmp_path, FAMILY_YAML))
    assert family.name == "ticket-status-family"
    assert family.seed == 7
    assert family.parameters == {
        "ticket_id": ["T-101", "T-202", "T-303"],
        "status": ["shipped", "processing", "delivered"],
        "attempts": [1, 2, 3],
    }


def test_defaults_when_optional_keys_missing() -> None:
    family = parse_family("parameters:\n  x: [a]\nturns:\n  - content: hi\n")
    assert family.name is None
    assert family.seed == 0


def test_member_seed_is_base_plus_index() -> None:
    family = parse_family(FAMILY_YAML)
    assert family.member(0).seed == 7
    assert family.member(1).seed == 8
    assert family.member(41).seed == 48
    assert family.member(0).scenario.seed == 7


def test_member_is_deterministic_per_index() -> None:
    family = parse_family(FAMILY_YAML)
    first = family.member(2)
    second = family.member(2)
    assert first.parameters == second.parameters
    assert first.scenario.turns == second.scenario.turns
    assert first.expected == second.expected


def test_member_parameters_come_from_the_declared_lists() -> None:
    family = parse_family(FAMILY_YAML)
    for index in range(20):
        member = family.member(index)
        assert member.parameters["ticket_id"] in ["T-101", "T-202", "T-303"]
        assert member.parameters["status"] in ["shipped", "processing", "delivered"]
        assert member.parameters["attempts"] in [1, 2, 3]
        assert set(member.parameters) == {"ticket_id", "status", "attempts"}


def test_member_substitutes_placeholders_in_turns_and_expected() -> None:
    family = parse_family(FAMILY_YAML)
    member = family.member(0)
    ticket = member.parameters["ticket_id"]
    status = member.parameters["status"]
    attempts = member.parameters["attempts"]
    assert member.scenario.turns == [
        {
            "tool_calls": [
                {
                    "name": "lookup_ticket",
                    "arguments": {"ticket_id": ticket, "attempts": attempts},
                }
            ]
        },
        {"content": f"Your {ticket} replacement has {status}."},
    ]
    assert member.expected == {
        "tool_calls": [
            {
                "name": "lookup_ticket",
                "arguments": {"ticket_id": ticket, "attempts": attempts},
            }
        ],
        "final_answer_contains": [status],
    }
    # No placeholder survives substitution.
    assert "{{" not in str(member.scenario.turns)
    assert "{{" not in str(member.expected)


def test_typed_substitution_keeps_non_string_values() -> None:
    """A whole-string `{{param}}` keeps the value's type (int stays int)."""
    family = parse_family(FAMILY_YAML)
    member = family.member(0)
    attempts = member.scenario.turns[0]["tool_calls"][0]["arguments"]["attempts"]
    assert isinstance(attempts, int)
    assert attempts == member.parameters["attempts"]


def test_member_scenario_replays_like_a_plain_scenario() -> None:
    family = parse_family(FAMILY_YAML)
    member = family.member(0)
    assert member.scenario.name == "ticket-status-family"
    llm = member.scenario.to_llm()
    completion = llm.complete([{"role": "user", "content": "hi"}])
    assert completion["choices"][0]["finish_reason"] == "tool_calls"
    assert (
        completion["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "lookup_ticket"
    )


def test_members_returns_count_deterministic_members() -> None:
    family = parse_family(FAMILY_YAML)
    members = family.members(3)
    assert len(members) == 3
    assert [m.index for m in members] == [0, 1, 2]
    assert members[1].parameters == family.member(1).parameters


def test_expected_derived_from_turns_when_absent() -> None:
    """No `expected:` block: the tool calls in the turns are the
    expectation, and there is nothing to demand of the final answer."""
    family = parse_family(FAMILY_NO_EXPECTED)
    member = family.member(0)
    assert member.expected == {
        "tool_calls": [
            {
                "name": "lookup_ticket",
                "arguments": {"ticket_id": member.parameters["ticket_id"]},
            }
        ],
        "final_answer_contains": [],
    }


def test_missing_parameters_fails_closed() -> None:
    with pytest.raises(FamilyError, match="parameters"):
        parse_family("turns:\n  - content: hi\n")


def test_empty_parameter_list_fails_closed() -> None:
    with pytest.raises(FamilyError, match="non-empty"):
        parse_family("parameters:\n  x: []\nturns:\n  - content: hi\n")


def test_non_scalar_parameter_value_fails_closed() -> None:
    with pytest.raises(FamilyError, match="scalar"):
        parse_family("parameters:\n  x: [{a: 1}]\nturns:\n  - content: hi\n")


def test_undeclared_placeholder_in_turns_fails_closed() -> None:
    with pytest.raises(FamilyError, match="undeclared parameter 'nope'"):
        parse_family("parameters:\n  x: [a]\nturns:\n  - content: 'hi {{nope}}'\n")


def test_undeclared_placeholder_in_expected_fails_closed() -> None:
    with pytest.raises(FamilyError, match="undeclared parameter 'nope'"):
        parse_family(
            "parameters:\n  x: [a]\nturns:\n  - content: hi\n"
            "expected:\n  final_answer_contains: ['{{nope}}']\n"
        )


def test_unbalanced_placeholder_fails_closed() -> None:
    with pytest.raises(FamilyError, match="unbalanced"):
        parse_family("parameters:\n  x: [a]\nturns:\n  - content: 'hi {{x'\n")


def test_empty_placeholder_fails_closed() -> None:
    with pytest.raises(FamilyError, match="empty placeholder"):
        parse_family("parameters:\n  x: [a]\nturns:\n  - content: 'hi {{ }}'\n")


def test_unknown_top_level_key_fails_closed() -> None:
    with pytest.raises(FamilyError, match="unknown top-level key"):
        parse_family("parameters:\n  x: [a]\nturns:\n  - content: hi\nsurprise: 1\n")


def test_bad_turn_shape_fails_closed() -> None:
    with pytest.raises(FamilyError, match="exactly one of"):
        parse_family(
            "parameters:\n  x: [a]\nturns:\n  - content: hi\n    tool_calls: [{name: ping}]\n"
        )


def test_empty_turns_fails_closed() -> None:
    with pytest.raises(FamilyError, match="non-empty list"):
        parse_family("parameters:\n  x: [a]\nturns: []\n")


def test_negative_member_index_fails_closed() -> None:
    with pytest.raises(FamilyError, match="non-negative"):
        parse_family(FAMILY_YAML).member(-1)


def test_members_rejects_non_positive_count() -> None:
    with pytest.raises(FamilyError, match="positive"):
        parse_family(FAMILY_YAML).members(0)


def test_missing_family_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FamilyError, match="cannot read family file"):
        load_family(tmp_path / "nope.yaml")


def test_invalid_yaml_fails_closed() -> None:
    with pytest.raises(FamilyError, match="invalid YAML"):
        parse_family("parameters: [unclosed\n")


def test_bool_seed_fails_closed() -> None:
    with pytest.raises(FamilyError, match="seed"):
        parse_family("seed: true\nparameters:\n  x: [a]\nturns:\n  - content: hi\n")


def test_whitespace_inside_placeholder_is_allowed() -> None:
    family = parse_family("parameters:\n  x: [hello]\nturns:\n  - content: 'say {{ x }} now'\n")
    assert family.member(0).scenario.turns == [{"content": "say hello now"}]
