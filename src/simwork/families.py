"""Scenario families (adoption, readiness criterion 2).

One family file generates many scenarios: named parameters with value
lists, `{{param}}` placeholders in the turns (and in the optional
`expected:` block), and a base seed. Member `i` gets seed `base + i`
and its parameter values from a PRNG seeded with that member seed —
so the same family + index always yields the same scenario, and a
thousand runs are a thousand different situations, not a thousand
copies of one scenario (spec §4 SHOULD, S16).

.. code-block:: yaml

    name: ticket-status-family   # optional
    seed: 7                      # optional, default 0
    parameters:                  # required, non-empty
      ticket_id: ["T-101", "T-202", "T-303"]
      status: ["shipped", "processing", "delivered"]
    turns:                       # required, non-empty (scenario shape)
      - tool_calls:
          - name: lookup_ticket
            arguments: {ticket_id: "{{ticket_id}}"}
      - content: "Your {{ticket_id}} replacement has {{status}}."
    expected:                    # optional, trace-expected shape
      tool_calls:
        - name: lookup_ticket
          arguments: {ticket_id: "{{ticket_id}}"}
      final_answer_contains: ["{{status}}"]

Placeholders substitute by value: a string that is exactly one
placeholder keeps the value's type (`"{{attempts}}"` with `attempts:
[1, 2]` stays an int in the tool arguments); inside a longer string
the value is interpolated as text. When `expected:` is absent it is
derived from the member's own turns (the tool calls the script makes
are the expected ones, nothing demanded of the final answer).

Loading is strict and fails closed, like scenarios: a bad schema, an
undeclared placeholder, or a non-scalar parameter value raises
`FamilyError` instead of silently producing a wrong member.
"""

from __future__ import annotations

import copy
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from simwork.llm.scenario import (
    Scenario,
    _validate_model,
    _validate_name,
    _validate_seed,
    _validate_turns,
)

_TOP_LEVEL_KEYS = {"name", "seed", "model", "parameters", "turns", "expected"}
_EXPECTED_KEYS = {"tool_calls", "final_answer_contains"}
_SCALARS = (str, int, float, bool)
# `{{ name }}` — whitespace inside the braces is allowed.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_SENTINEL = "x"


class FamilyError(ValueError):
    """Raised when a family file is missing, unparseable, or invalid."""


@dataclass(frozen=True)
class FamilyMember:
    """One generated member: its parameters, scenario, and expectation."""

    index: int
    seed: int
    parameters: dict[str, Any]
    scenario: Scenario
    expected: dict[str, Any]


@dataclass(frozen=True)
class ScenarioFamily:
    """A validated family: parameter lists plus templated turns."""

    parameters: dict[str, list]
    turns: list[dict]
    name: str | None = None
    seed: int = 0
    model: str = "simwork-mock"
    expected: dict[str, Any] | None = None

    def member(self, index: int) -> FamilyMember:
        """Generate member `index`: deterministic per (family, index).

        The member seed is `base + index`; parameter values are picked
        by a PRNG seeded with it (parameter names in sorted order, so
        the pick does not depend on the YAML mapping order).
        """
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise FamilyError(f"member index must be a non-negative integer, got {index!r}")
        member_seed = self.seed + index
        rng = random.Random(member_seed)
        parameters = {name: rng.choice(values) for name, values in sorted(self.parameters.items())}
        try:
            turns = _validate_turns(_substitute(self.turns, parameters), f"member {index}")
        except ValueError as e:
            raise FamilyError(str(e)) from None
        scenario = Scenario(turns=turns, name=self.name, seed=member_seed, model=self.model)
        return FamilyMember(
            index=index,
            seed=member_seed,
            parameters=parameters,
            scenario=scenario,
            expected=self._expected_for(turns, parameters, index),
        )

    def members(self, count: int) -> list[FamilyMember]:
        """Generate members `0..count-1` (deterministic, in order)."""
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise FamilyError(f"count must be a positive integer, got {count!r}")
        return [self.member(i) for i in range(count)]

    def _expected_for(
        self, turns: list[dict], parameters: dict[str, Any], index: int
    ) -> dict[str, Any]:
        """The member's expectation: declared (substituted) or derived.

        Derived from the member's own turns: the tool calls the script
        makes are the expected ones, and nothing is demanded of the
        final answer.
        """
        if self.expected is None:
            calls = [call for turn in turns for call in turn.get("tool_calls", [])]
            return {"tool_calls": calls, "final_answer_contains": []}
        try:
            return _validate_expected(_substitute(self.expected, parameters), f"member {index}")
        except ValueError as e:
            raise FamilyError(str(e)) from None


def load_family(path: str | Path) -> ScenarioFamily:
    """Load and validate a family from a YAML file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise FamilyError(f"cannot read family file {path}: {e}") from e
    return parse_family(text, source=str(path))


def parse_family(text: str, *, source: str = "<string>") -> ScenarioFamily:
    """Parse and validate a family from YAML text."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise FamilyError(f"{source}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise FamilyError(f"{source}: family must be a mapping, got {type(data).__name__}")
    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise FamilyError(f"{source}: unknown top-level key(s): {sorted(unknown)}")
    try:
        name = _validate_name(data.get("name"), source)
        seed = _validate_seed(data.get("seed", 0), source)
        model = _validate_model(data.get("model", "simwork-mock"), source)
    except ValueError as e:
        raise FamilyError(str(e)) from None
    parameters = _validate_parameters(data.get("parameters"), source)
    turns = _validate_template_turns(data.get("turns"), parameters, source)
    expected = _validate_template_expected(data.get("expected"), parameters, source)
    return ScenarioFamily(
        parameters=parameters,
        turns=turns,
        name=name,
        seed=seed,
        model=model,
        expected=expected,
    )


def _validate_parameters(value: Any, source: str) -> dict[str, list]:
    if not isinstance(value, dict) or not value:
        raise FamilyError(f"{source}: 'parameters' must be a non-empty mapping")
    parameters: dict[str, list] = {}
    for name, values in value.items():
        where = f"{source}: parameter {name!r}"
        if not isinstance(name, str) or not name:
            raise FamilyError(f"{where}: parameter names must be non-empty strings")
        if not isinstance(values, list) or not values:
            raise FamilyError(f"{where}: values must be a non-empty list")
        for item in values:
            if not isinstance(item, _SCALARS):
                raise FamilyError(
                    f"{where}: values must be scalars (string, number, boolean), got {item!r}"
                )
        parameters[name] = list(values)
    return parameters


def _validate_template_turns(value: Any, parameters: dict[str, list], source: str) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise FamilyError(f"{source}: 'turns' must be a non-empty list")
    _check_placeholders(value, set(parameters), source)
    try:
        # Validate the shape with the placeholders blanked out; the
        # real template is kept as-is for substitution at member time.
        _validate_turns(_substitute(value, {name: _SENTINEL for name in parameters}), source)
    except ValueError as e:
        raise FamilyError(str(e)) from None
    return copy.deepcopy(value)


def _validate_template_expected(
    value: Any, parameters: dict[str, list], source: str
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise FamilyError(f"{source}: 'expected' must be a mapping")
    _check_placeholders(value, set(parameters), source)
    try:
        # Validate the shape with the placeholders blanked out; the
        # real template is kept as-is for substitution at member time.
        _validate_expected(_substitute(value, {name: _SENTINEL for name in parameters}), source)
    except ValueError as e:
        raise FamilyError(str(e)) from None
    return copy.deepcopy(value)


def _validate_expected(value: Any, source: str) -> dict[str, Any]:
    """Validate an `expected` block (trace-expected shape)."""
    if not isinstance(value, dict):
        raise FamilyError(f"{source}: 'expected' must be a mapping")
    unknown = set(value) - _EXPECTED_KEYS
    if unknown:
        raise FamilyError(f"{source}: unknown 'expected' key(s): {sorted(unknown)}")
    expected: dict[str, Any] = {}
    calls = value.get("tool_calls", [])
    if not isinstance(calls, list):
        raise FamilyError(f"{source}: 'expected.tool_calls' must be a list")
    validated_calls = []
    for i, call in enumerate(calls):
        where = f"{source}: expected tool call {i}"
        if not isinstance(call, dict) or set(call) - {"name", "arguments"}:
            raise FamilyError(f"{where}: must be a mapping with 'name' and 'arguments'")
        name = call.get("name")
        if not isinstance(name, str) or not name:
            raise FamilyError(f"{where}: needs a non-empty 'name'")
        arguments = call.get("arguments", {})
        if not isinstance(arguments, dict):
            raise FamilyError(f"{where}: 'arguments' must be a mapping")
        validated_calls.append({"name": name, "arguments": copy.deepcopy(arguments)})
    expected["tool_calls"] = validated_calls
    final = value.get("final_answer_contains", [])
    if not isinstance(final, list) or any(not isinstance(s, str) for s in final):
        raise FamilyError(f"{source}: 'expected.final_answer_contains' must be a list of strings")
    expected["final_answer_contains"] = list(final)
    return expected


def _check_placeholders(value: Any, declared: set[str], source: str) -> None:
    """Every `{{name}}` in `value` must name a declared parameter."""
    for string in _strings(value):
        _check_string_placeholders(string, declared, source)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _check_string_placeholders(string: str, declared: set[str], source: str) -> None:
    for match in _PLACEHOLDER_RE.finditer(string):
        name = match.group(1).strip()
        if not name:
            raise FamilyError(f"{source}: empty placeholder in {string!r}")
        if name not in declared:
            raise FamilyError(
                f"{source}: undeclared parameter {name!r} in {string!r} "
                f"(declared: {sorted(declared)})"
            )
    stripped = _PLACEHOLDER_RE.sub("", string)
    if "{{" in stripped or "}}" in stripped:
        raise FamilyError(f"{source}: unbalanced placeholder braces in {string!r}")


def _substitute(value: Any, parameters: dict[str, Any]) -> Any:
    """Replace `{{name}}` placeholders with the member's values.

    A string that is exactly one placeholder keeps the value's type;
    inside a longer string the value is interpolated as text.
    """
    if isinstance(value, str):
        whole = re.fullmatch(r"\{\{\s*([^{}]+?)\s*\}\}", value)
        if whole is not None:
            return parameters[whole.group(1).strip()]
        return _PLACEHOLDER_RE.sub(lambda m: str(parameters[m.group(1).strip()]), value)
    if isinstance(value, dict):
        return {key: _substitute(item, parameters) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, parameters) for item in value]
    return value
