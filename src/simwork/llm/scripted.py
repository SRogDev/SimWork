"""Deterministic scripted LLM responses for simulate mode.

A `ScriptedLLM` replays a fixed script of turns, in order, and fails
closed (`ScriptExhaustedError`) when the script runs out — a simulated
run must error visibly, never silently fall back to a real LLM call.
Same seed + same script always produces the same responses.
"""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simwork.trace import TraceRecorder

Turn = dict


class ScriptExhaustedError(RuntimeError):
    """Raised when a scripted LLM is asked for a turn past its script."""


class ScriptedLLM:
    """Replays scripted turns as OpenAI-shaped chat completions.

    A turn is a dict with either ``{"content": "..."}`` for a plain reply
    or ``{"tool_calls": [{"name": ..., "arguments": {...}}]}`` for a
    tool-calling reply. The response shape (including ids) is fully
    determined by the seed and the turn index.
    """

    def __init__(
        self,
        script: list[Turn],
        *,
        seed: int = 0,
        model: str = "simwork-mock",
        recorder: TraceRecorder | None = None,
    ):
        self._script = [copy.deepcopy(turn) for turn in script]
        self.seed = seed
        self.model = model
        self.recorder = recorder
        self.calls: list[list[dict]] = []
        self._index = 0

    def complete(self, messages: list[dict]) -> dict:
        """Return the next scripted turn as a chat-completion dict."""
        if self._index >= len(self._script):
            raise ScriptExhaustedError(
                f"scripted LLM exhausted after {len(self._script)} turn(s); "
                "add more turns to the scenario instead of falling back to a real LLM"
            )
        turn = self._script[self._index]
        self.calls.append(copy.deepcopy(messages))
        turn_index = self._index
        self._index += 1
        completion = self._completion(turn, turn_index)
        if self.recorder is not None:
            self.recorder.record_completion(completion)
        return completion

    def reset(self) -> None:
        """Restart the script from the first turn (same seed, same trace)."""
        self._index = 0
        self.calls.clear()

    def _completion(self, turn: Turn, turn_index: int) -> dict:
        tool_calls = turn.get("tool_calls")
        if tool_calls:
            message: dict = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call-simwork-{self.seed}-{turn_index}-{i}",
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                    for i, call in enumerate(tool_calls)
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": turn.get("content", "")}
            finish_reason = "stop"
        return {
            "id": f"chatcmpl-simwork-{self.seed}-{turn_index}",
            "object": "chat.completion",
            "created": 0,
            "model": self.model,
            "choices": [
                {"index": 0, "message": message, "finish_reason": finish_reason}
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
