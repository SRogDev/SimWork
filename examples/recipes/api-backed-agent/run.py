"""Run the API-backed-agent recipe end-to-end.

An API-backed agent, simulated: the scripted LLM calls the
`get_exchange_rates` tool — a thin wrapper over one endpoint of the
ExchangeRate-API spec fetched from the APIs.guru catalog
(`exchangerate-api.yaml`) — and answers by computing from the
structured rates the tool returns (100 USD x 0.92 = 92 EUR,
100 USD x 0.79 = 79 GBP). The run is recorded as a trace and gated
with the $0 eval (tool correctness + task completion).

This is the API-backed pattern: the agent's tools ARE the world API
— each tool maps 1:1 to an OpenAPI operation, and the answer is
computed from the API's structured fields, not quoted from prose.
To expose another endpoint, add its operation as another tool
following the same mapping. The loop is the plain-OpenAI-client
pattern — a raw HTTP agent loop against the fake server, no
LangGraph — bounded (5 turns) and failing closed: an unknown tool,
a failed mock call, or a loop that never answers all raise instead
of falling back to anything real. Everything runs on localhost:
$0, no real LLM or world-API calls.

Usage (from this directory, with SimWork installed):

    python run.py [--trace-out evals/api-backed-agent-trace.json]

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
RUN_ID = "api-backed-agent-1"
SEED = 11
USER_QUESTION = "How much is 100 US dollars in euros and pounds?"
MAX_TURNS = 5

EXPECTED: dict[str, Any] = {
    "tool_calls": [{"name": "get_exchange_rates", "arguments": {"base_currency": "USD"}}],
    "final_answer_contains": ["92 EUR", "79 GBP"],
}

_RECIPE_DEPS_HINT = (
    "the API-backed-agent recipe needs httpx — install the demo dependencies with "
    "`uv sync --group demo` (from the repo root)"
)
_PRISM_INSTALL_HINT = "npm i -g @stoplight/prism-cli (requires Node 18+)"

# The one tool the scripted LLM may call: fetch the latest exchange
# rates for a base currency. The function definition is what a real
# harness would send; the implementation below executes it against
# the Prism mock of the ExchangeRate-API spec. The tool maps 1:1 to
# the spec's GET /latest/{base_currency} operation.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_exchange_rates",
            "description": "Fetch the latest exchange rates for a base currency.",
            "parameters": {
                "type": "object",
                "properties": {"base_currency": {"type": "string"}},
                "required": ["base_currency"],
            },
        },
    }
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
    """Execute one tool call against the exchange-rates API mock; fail closed otherwise."""
    name = call["name"]
    if name != "get_exchange_rates":
        raise RecipeError(f"unknown tool {name!r} — the recipe only knows get_exchange_rates")
    # trust_env=False: the tool talks to the local mock directly — never
    # via a proxy from the environment (a proxy would be a real-world
    # egress path for what must stay a $0 local call).
    response = client.get(
        f"{api_base_url}/latest/{call['arguments']['base_currency']}", timeout=10.0
    )
    response.raise_for_status()
    return response.json()


def run_recipe() -> tuple[Trace, EvalReport]:
    """Run the recipe: both mocks, the agent loop, the eval gate."""
    import httpx

    _check_recipe_deps()
    scenario = load_scenario(HERE / "scenarios" / "api-backed-agent.yaml")
    with tempfile.TemporaryDirectory(prefix="simwork-api-backed-") as tmp:
        spec_path = Path(tmp) / "exchangerate-api.json"
        # Prism reads the spec as JSON, so the bundled YAML spec is
        # converted on the way to the temp file (same as the demo).
        spec_path.write_text(
            json.dumps(
                yaml.safe_load((HERE / "exchangerate-api.yaml").read_text(encoding="utf-8"))
            ),
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
    parser = argparse.ArgumentParser(description="Run the API-backed-agent recipe end-to-end ($0).")
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
        print(f"api-backed-agent recipe: error: {e}", file=sys.stderr)
        return 1
    print(report.to_text())
    if args.trace_out is not None:
        try:
            args.trace_out.parent.mkdir(parents=True, exist_ok=True)
            args.trace_out.write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n")
        except OSError as e:
            print(f"api-backed-agent recipe: error: cannot write trace: {e}", file=sys.stderr)
            return 1
        print(f"trace written to {args.trace_out}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
