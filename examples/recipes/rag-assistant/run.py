"""Run the RAG-assistant recipe end-to-end.

A retrieval-augmented assistant, simulated: the scripted LLM calls
the `retrieve_docs` tool, the tool hits a Prism mock of the bundled
docs-search API (`docs-api.yaml`), and the LLM answers grounded in
the retrieved doc. The run is recorded as a trace and gated with the
$0 eval (tool correctness + task completion).

This is the plain-OpenAI-client pattern — a raw HTTP agent loop
against the fake server, no LangGraph — for harnesses that talk to
an OpenAI-compatible client directly. The loop is bounded (5 turns)
and fails closed: an unknown tool, a failed mock call, or a loop
that never answers all raise instead of falling back to anything
real. Everything runs on localhost: $0, no real LLM or world-API
calls.

Usage (from this directory, with SimWork installed):

    python run.py [--trace-out evals/rag-assistant-trace.json]

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
RUN_ID = "rag-assistant-1"
SEED = 7
USER_QUESTION = "What is the refund window?"
MAX_TURNS = 5

EXPECTED: dict[str, Any] = {
    "tool_calls": [{"name": "retrieve_docs", "arguments": {"query": USER_QUESTION}}],
    "final_answer_contains": ["30 days"],
}

_RECIPE_DEPS_HINT = (
    "the RAG recipe needs httpx — install the demo dependencies with "
    "`uv sync --group demo` (from the repo root)"
)
_PRISM_INSTALL_HINT = "npm i -g @stoplight/prism-cli (requires Node 18+)"

# The one tool the scripted LLM may call: retrieve docs for a query.
# The function definition is what a real harness would send; the
# implementation below executes it against the Prism mock.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "retrieve_docs",
            "description": "Search the docs for the text answering a question.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
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
    """Execute one tool call against the docs-API mock; fail closed otherwise."""
    name = call["name"]
    if name != "retrieve_docs":
        raise RecipeError(f"unknown tool {name!r} — the recipe only knows retrieve_docs")
    # trust_env=False: the tool talks to the local mock directly — never
    # via a proxy from the environment (a proxy would be a real-world
    # egress path for what must stay a $0 local call).
    response = client.get(
        f"{api_base_url}/search", params={"q": call["arguments"]["query"]}, timeout=10.0
    )
    response.raise_for_status()
    return response.json()


def run_recipe() -> tuple[Trace, EvalReport]:
    """Run the recipe: both mocks, the agent loop, the eval gate."""
    import httpx

    _check_recipe_deps()
    scenario = load_scenario(HERE / "scenarios" / "rag-assistant.yaml")
    with tempfile.TemporaryDirectory(prefix="simwork-rag-") as tmp:
        spec_path = Path(tmp) / "docs-api.json"
        # Prism reads the spec as JSON, so the bundled YAML spec is
        # converted on the way to the temp file (same as the demo).
        spec_path.write_text(
            json.dumps(yaml.safe_load((HERE / "docs-api.yaml").read_text(encoding="utf-8"))),
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
    parser = argparse.ArgumentParser(description="Run the RAG-assistant recipe end-to-end ($0).")
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
        print(f"rag-assistant recipe: error: {e}", file=sys.stderr)
        return 1
    print(report.to_text())
    if args.trace_out is not None:
        try:
            args.trace_out.parent.mkdir(parents=True, exist_ok=True)
            args.trace_out.write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n")
        except OSError as e:
            print(f"rag-assistant recipe: error: cannot write trace: {e}", file=sys.stderr)
            return 1
        print(f"trace written to {args.trace_out}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
