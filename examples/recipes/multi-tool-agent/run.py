"""Run the multi-tool-agent recipe end-to-end.

A multi-tool agent, simulated: the scripted LLM first calls
`search_flights` — a thin wrapper over GET /flights of the bundled
travel API (`travel-api.yaml`) — then calls `search_hotels`, a thin
wrapper over GET /hotels of the same API, and finally answers by
adding flight + hotel ($420 + $120 x 1 night = $540 total). The
chain is the point: the hotel call's arguments come from the flight
result (destination city "Paris" and arrival date "2026-12-10" of
the cheapest flight), so each tool call depends on the previous
result. The run is recorded as a trace and gated with the $0 eval
(tool correctness + task completion).

This is the multi-tool pattern: several tools chained in one run,
each call's arguments derived from an earlier result, and the final
answer computed from the chained results — not quoted from one doc
(the RAG recipe) and not computed from one call (the API-backed
recipe). To chain another tool, add its operation to the spec, add
a tool definition following the same 1:1 mapping, and extend the
scenario turns. The loop is the plain-OpenAI-client pattern — a raw
HTTP agent loop against the fake server, no LangGraph — bounded
(5 turns) and failing closed: an unknown tool, a failed mock call,
or a loop that never answers all raise instead of falling back to
anything real. Everything runs on localhost: $0, no real LLM or
world-API calls.

Usage (from this directory, with SimWork installed):

    python run.py [--trace-out evals/multi-tool-agent-trace.json]

Exits 0 when the gate passes, 1 when it fails. Needs `httpx`
(`uv sync --group demo` from the repo root) and the `prism` binary
(`npm i -g @stoplight/prism-cli`).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from simwork.api_mock import PrismMockServer
from simwork.eval import EvalReport, evaluate_run
from simwork.llm import FakeOpenAIServer, load_scenario
from simwork.trace import Trace, TraceRecorder

HERE = Path(__file__).resolve().parent
RUN_ID = "multi-tool-agent-1"
SEED = 21
USER_QUESTION = (
    "Plan my trip from New York to Paris on 2026-12-10: find the cheapest "
    "flight and a hotel in Paris for the arrival night, and tell me the "
    "total for flight + one night."
)
MAX_TURNS = 5

EXPECTED: dict[str, Any] = {
    "tool_calls": [
        {
            "name": "search_flights",
            "arguments": {"from": "JFK", "to": "CDG", "date": "2026-12-10"},
        },
        {
            "name": "search_hotels",
            "arguments": {"city": "Paris", "checkin": "2026-12-10", "nights": 1},
        },
    ],
    "final_answer_contains": ["$540", "$420", "$120"],
}

_RECIPE_DEPS_HINT = (
    "the multi-tool-agent recipe needs httpx — install the demo dependencies with "
    "`uv sync --group demo` (from the repo root)"
)
_PRISM_INSTALL_HINT = "npm i -g @stoplight/prism-cli (requires Node 18+)"

# The two tools the scripted LLM may call. Each is a thin wrapper over
# one operation of the bundled travel API (see travel-api.yaml); the
# function definitions are what a real harness would send, and the
# implementations below execute them against the Prism mock.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": "Search flights between two airports on a date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["from", "to", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hotels",
            "description": "Search hotels in a city for a check-in date and nights.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "checkin": {"type": "string"},
                    "nights": {"type": "integer"},
                },
                "required": ["city", "checkin", "nights"],
            },
        },
    },
]


class RecipeError(Exception):
    """Raised when the recipe cannot run (missing deps, bad mock, no answer)."""


def _check_recipe_deps() -> None:
    try:
        import httpx  # noqa: F401
    except ImportError as e:
        raise RecipeError(_RECIPE_DEPS_HINT) from e
    if shutil.which("prism") is None:
        raise RecipeError(
            f"the `prism` binary was not found on PATH — install it with {_PRISM_INSTALL_HINT}"
        )


def _execute_tool(client: Any, api_base_url: str, call: dict[str, Any]) -> dict[str, Any]:
    """Execute one tool call against the travel API mock; fail closed otherwise."""
    name = call["name"]
    args = call["arguments"]
    # trust_env=False: the tool talks to the local mock directly — never
    # via a proxy from the environment (a proxy would be a real-world
    # egress path for what must stay a $0 local call).
    if name == "search_flights":
        response = client.get(
            f"{api_base_url}/flights",
            params={"from": args["from"], "to": args["to"], "date": args["date"]},
            timeout=10.0,
        )
    elif name == "search_hotels":
        response = client.get(
            f"{api_base_url}/hotels",
            params={
                "city": args["city"],
                "checkin": args["checkin"],
                "nights": args["nights"],
            },
            timeout=10.0,
        )
    else:
        raise RecipeError(
            f"unknown tool {name!r} — the recipe only knows search_flights and search_hotels"
        )
    response.raise_for_status()
    return response.json()


def run_recipe() -> tuple[Trace, EvalReport]:
    """Run the recipe: both mocks, the agent loop, the eval gate."""
    import httpx

    _check_recipe_deps()
    scenario = load_scenario(HERE / "scenarios" / "multi-tool-agent.yaml")
    with tempfile.TemporaryDirectory(prefix="simwork-multi-tool-") as tmp:
        spec_path = Path(tmp) / "travel-api.json"
        # Prism reads the spec as JSON, so the bundled YAML spec is
        # converted on the way to the temp file (same as the demo).
        spec_path.write_text(
            json.dumps(yaml.safe_load((HERE / "travel-api.yaml").read_text(encoding="utf-8"))),
            encoding="utf-8",
        )
        llm = scenario.to_llm()
        with (
            FakeOpenAIServer(llm) as llm_server,
            PrismMockServer(spec_path) as api_server,
        ):
            recorder = TraceRecorder(run_id=RUN_ID, seed=SEED)
            messages: list[dict[str, Any]] = [{"role": "user", "content": USER_QUESTION}]
            with httpx.Client(trust_env=False, timeout=10.0) as client:
                for _ in range(MAX_TURNS):
                    response = client.post(
                        f"{llm_server.base_url}/chat/completions",
                        json={
                            "model": "simwork-mock",
                            "messages": messages,
                            "tools": TOOLS,
                            "temperature": 0,
                        },
                    )
                    response.raise_for_status()
                    completion = response.json()
                    recorder.record_completion(completion)
                    message = completion["choices"][0]["message"]
                    raw_calls = message.get("tool_calls") or []
                    if not raw_calls:
                        break
                    messages.append(message)
                    for raw_call in raw_calls:
                        call = {
                            "name": raw_call["function"]["name"],
                            "arguments": json.loads(raw_call["function"]["arguments"]),
                        }
                        result = _execute_tool(client, api_server.base_url, call)
                        recorder.record_tool_result(call["name"], result)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": raw_call["id"],
                                "content": json.dumps(result),
                            }
                        )
                else:
                    raise RecipeError(
                        f"agent loop did not answer within {MAX_TURNS} turns — "
                        "the script must end in a content turn, not loop on tools"
                    )
    trace = recorder.to_trace(expected=EXPECTED)
    return trace, evaluate_run(trace)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the multi-tool-agent recipe end-to-end ($0).")
    parser.add_argument(
        "--trace-out",
        type=Path,
        default=None,
        help="also write the recorded trace to this JSON file",
    )
    args = parser.parse_args(argv)
    try:
        trace, report = run_recipe()
    except RecipeError as e:
        print(f"multi-tool-agent recipe: error: {e}", file=sys.stderr)
        return 1
    print(report.to_text())
    if args.trace_out is not None:
        try:
            args.trace_out.parent.mkdir(parents=True, exist_ok=True)
            args.trace_out.write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n")
        except OSError as e:
            print(f"multi-tool-agent recipe: error: cannot write trace: {e}", file=sys.stderr)
            return 1
        print(f"trace written to {args.trace_out}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
