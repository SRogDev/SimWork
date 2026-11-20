"""YAML scenario files for the scripted LLM (Phase 1, task 2).

Scenarios are defined in files, not code (spec §4). A scenario file
declares the scripted turns a `ScriptedLLM` replays:

.. code-block:: yaml

    name: ticket-status        # optional
    seed: 7                    # optional, default 0
    model: simwork-mock        # optional, default "simwork-mock"
    turns:                     # required, non-empty
      - content: "I will check the ticket."
      - tool_calls:
          - name: lookup_ticket
            arguments: {ticket_id: "T-123"}
      - content: "Your replacement has shipped."

Loading is strict and fails closed: any schema violation raises
`ScenarioError` instead of silently producing a wrong script.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from simwork.llm.scripted import ScriptedLLM

if TYPE_CHECKING:
    from simwork.trace import TraceRecorder

_DEFAULT_MODEL = "simwork-mock"
_TOP_LEVEL_KEYS = {"name", "seed", "model", "turns"}
_TURN_KEYS = {"content", "tool_calls"}


class ScenarioError(ValueError):
    """Raised when a scenario file is missing, unparseable, or invalid."""


@dataclass(frozen=True)
class Scenario:
    """A validated scenario: scripted turns plus replay settings."""

    turns: list[dict]
    name: str | None = None
    seed: int = 0
    model: str = _DEFAULT_MODEL

    def to_llm(self, recorder: TraceRecorder | None = None) -> ScriptedLLM:
        """Build the deterministic scripted LLM for this scenario.

        A recorder handed here is recorded by the LLM itself, so a
        server built from this LLM captures the run without the server
        needing to know about recording.
        """
        return ScriptedLLM(
            copy.deepcopy(self.turns), seed=self.seed, model=self.model, recorder=recorder
        )

    def to_dict(self) -> dict:
        """Serialise back to the YAML shape `parse_scenario` reads.

        Used to materialise a scenario family member as a file (so
        `simwork serve --family` can serve one member through the same
        path as a plain scenario file); round-trips through
        `parse_scenario`.
        """
        data: dict = {"seed": self.seed, "model": self.model, "turns": copy.deepcopy(self.turns)}
        if self.name is not None:
            data["name"] = self.name
        return data


def load_scenario(path: str | Path) -> Scenario:
    """Load and validate a scenario from a YAML file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ScenarioError(f"cannot read scenario file {path}: {e}") from e
    return parse_scenario(text, source=str(path))


def parse_scenario(text: str, *, source: str = "<string>") -> Scenario:
    """Parse and validate a scenario from YAML text."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ScenarioError(f"{source}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ScenarioError(f"{source}: scenario must be a mapping, got {type(data).__name__}")
    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise ScenarioError(f"{source}: unknown top-level key(s): {sorted(unknown)}")
    return Scenario(
        name=_validate_name(data.get("name"), source),
        seed=_validate_seed(data.get("seed", 0), source),
        model=_validate_model(data.get("model", _DEFAULT_MODEL), source),
        turns=_validate_turns(data.get("turns"), source),
    )


def _validate_name(value: Any, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ScenarioError(f"{source}: 'name' must be a string")
    return value


def _validate_seed(value: Any, source: str) -> int:
    # bool is a subclass of int — reject it explicitly, it is never a seed.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScenarioError(f"{source}: 'seed' must be an integer")
    return value


def _validate_model(value: Any, source: str) -> str:
    if not isinstance(value, str):
        raise ScenarioError(f"{source}: 'model' must be a string")
    return value


def _validate_turns(value: Any, source: str) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ScenarioError(f"{source}: 'turns' must be a non-empty list")
    return [_validate_turn(turn, source, i) for i, turn in enumerate(value)]


def _validate_turn(turn: Any, source: str, index: int) -> dict:
    where = f"{source}: turn {index}"
    if not isinstance(turn, dict):
        raise ScenarioError(f"{where}: turn must be a mapping")
    unknown = set(turn) - _TURN_KEYS
    if unknown:
        raise ScenarioError(f"{where}: unknown key(s): {sorted(unknown)}")
    has_content = "content" in turn
    has_calls = "tool_calls" in turn
    if has_content == has_calls:
        raise ScenarioError(f"{where}: turn needs exactly one of 'content' or 'tool_calls'")
    if has_content:
        if not isinstance(turn["content"], str):
            raise ScenarioError(f"{where}: 'content' must be a string")
        return {"content": turn["content"]}
    return {"tool_calls": _validate_tool_calls(turn["tool_calls"], where)}


def _validate_tool_calls(value: Any, where: str) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ScenarioError(f"{where}: 'tool_calls' must be a non-empty list")
    calls = []
    for i, call in enumerate(value):
        if not isinstance(call, dict):
            raise ScenarioError(f"{where}: tool call {i} must be a mapping")
        if set(call) - {"name", "arguments"}:
            raise ScenarioError(
                f"{where}: tool call {i} has unknown key(s): "
                f"{sorted(set(call) - {'name', 'arguments'})}"
            )
        name = call.get("name")
        if not isinstance(name, str) or not name:
            raise ScenarioError(f"{where}: tool call {i} needs a non-empty 'name'")
        arguments = call.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ScenarioError(f"{where}: tool call {i} 'arguments' must be a mapping")
        calls.append({"name": name, "arguments": copy.deepcopy(arguments)})
    return calls
