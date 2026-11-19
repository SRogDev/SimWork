"""The LangGraph demo end-to-end (Phase 4, task 3).

A small LangGraph agent app that calls one LLM and one world API, so a
simulated run exercises both mocks and the eval gate (spec §4 SHOULD):

- the LLM is SimWork's scripted fake OpenAI server, fed by the demo
  scenario (two turns: call `lookup_ticket`, then answer);
- the world API is a Prism mock of a tiny ticket API spec bundled
  here, so the demo needs no network beyond localhost;
- the run is recorded as a trace (assistant steps from the LangGraph
  messages, tool results from the API mock) and gated with the $0 eval.

The demo's dependencies (langgraph, langchain-openai, httpx) live in
the `demo` dependency group and are imported lazily, so importing
`simwork` never requires them: `run_demo` fails closed with an install
hint when they are missing, and `simwork demo` reports the same.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from simwork.api_mock import PrismMockServer
from simwork.eval import EvalReport, evaluate_run
from simwork.llm import FakeOpenAIServer, ScriptedLLM, parse_scenario
from simwork.trace import Trace, validate_trace

_DEMO_DEPS_HINT = (
    "the LangGraph demo needs the demo dependencies "
    "(langgraph, langchain-openai, httpx) — install them with "
    "`uv sync --group demo`"
)
_PRISM_INSTALL_HINT = "npm i -g @stoplight/prism-cli (requires Node 18+)"

RUN_ID = "langgraph-demo-1"
SEED = 7
USER_MESSAGE = "What's the status of ticket T-123?"

# Two turns, same shape as the `simwork init` starter: the scripted LLM
# calls the tool first (the agent has nothing to say before it knows
# the ticket status), then answers from the tool result. A turn cannot
# carry both content and tool calls (see `ScriptedLLM`), and the
# LangGraph agent stops after a content-only turn, so the tool call
# must be the first turn — otherwise the demo would never touch the
# world API.
_SCENARIO_YAML = """\
name: langgraph-demo
seed: 7
turns:
  - tool_calls:
      - name: lookup_ticket
        arguments: {ticket_id: "T-123"}
  - content: "Your replacement has shipped."
"""

# The world API the demo's tool calls: one endpoint, one example.
# Prism serves the example deterministically, so the tool result — and
# therefore the trace — is the same on every run.
_TICKETS_API_YAML = """\
openapi: 3.0.0
info:
  title: Ticket API
  version: 1.0.0
paths:
  /tickets/{ticket_id}:
    get:
      parameters:
        - name: ticket_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                type: object
                properties:
                  ticket_id:
                    type: string
                  status:
                    type: string
                required: [ticket_id, status]
              example: {ticket_id: "T-123", status: "shipped"}
"""

# The expected outcome of the demo run, shared with the scale batch
# (`simwork.scale` repeats this run): the tool call the agent should
# make, and the facts the final answer should cover.
EXPECTED: dict[str, Any] = {
    "tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}],
    "final_answer_contains": ["shipped"],
}


class DemoError(Exception):
    """Raised when the demo cannot run (missing deps, missing prism)."""


def _check_demo_deps() -> None:
    """Fail closed with the install hint when the demo group is missing."""
    try:
        import langchain_core  # noqa: F401
        import langchain_openai  # noqa: F401
        import langgraph  # noqa: F401
    except ImportError as e:
        raise DemoError(_DEMO_DEPS_HINT) from e


def messages_to_trace(
    messages: list[Any],
    *,
    run_id: str,
    seed: int,
    expected: dict[str, Any] | None = None,
) -> Trace:
    """Convert a LangGraph run's messages into an eval trace.

    Assistant messages become `assistant` steps (content and/or tool
    calls — message ids are dropped, they are not deterministic),
    tool messages become `tool_result` steps (their JSON content parsed
    back into a value), and human input is left out: a trace records
    what the run did, not what it was asked.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    steps: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, AIMessage):
            step: dict[str, Any] = {"type": "assistant"}
            if isinstance(msg.content, str) and msg.content:
                step["content"] = msg.content
            if msg.tool_calls:
                step["tool_calls"] = [
                    {"name": call["name"], "arguments": dict(call["args"])}
                    for call in msg.tool_calls
                ]
            if "content" in step or "tool_calls" in step:
                steps.append(step)
        elif isinstance(msg, ToolMessage):
            content = msg.content
            if isinstance(content, str):
                try:
                    result: Any = json.loads(content)
                except ValueError:
                    result = content
            else:
                result = content
            steps.append({"type": "tool_result", "name": msg.name, "result": result})
    trace: Trace = {"run_id": run_id, "seed": seed, "steps": steps}
    if expected is not None:
        trace["expected"] = expected
    return validate_trace(trace)


def build_graph(api_base_url: str, llm_base_url: str):
    """Build the demo agent graph: one LLM node, one tool node.

    The agent is a `ChatOpenAI` pointed at the fake server (base-URL
    swap — the harness is unchanged between simulate and live), with
    the `lookup_ticket` tool bound. The tool calls the world-API mock
    over HTTP; `max_retries=0` so a failed call fails visibly instead
    of retrying against the deterministic script and consuming the
    next scripted turn.
    """
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode, tools_condition

    import httpx

    @tool
    def lookup_ticket(ticket_id: str) -> str:
        """Look up a support ticket's status by id."""
        # trust_env=False: the tool talks to the local mock directly —
        # never via a proxy from the environment (this sandbox's proxy
        # variables break httpx's URL parsing, and a proxy would be a
        # real-world egress path for what must stay a $0 local call).
        response = httpx.get(f"{api_base_url}/tickets/{ticket_id}", timeout=10.0, trust_env=False)
        response.raise_for_status()
        return response.text

    llm = ChatOpenAI(
        model="simwork-mock",
        base_url=llm_base_url,
        api_key="simwork-simulated",
        temperature=0,
        max_retries=0,
    ).bind_tools([lookup_ticket])

    def call_agent(state: MessagesState) -> dict[str, Any]:
        return {"messages": [llm.invoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_agent)
    graph.add_node("tools", ToolNode([lookup_ticket]))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def run_demo() -> tuple[Trace, EvalReport]:
    """Run the demo end-to-end: both mocks, the graph, the eval gate.

    Starts the fake OpenAI server from the demo scenario and the Prism
    mock of the bundled ticket spec (both on localhost — $0, no real
    calls), runs the LangGraph agent once, records the trace and
    evaluates it. Returns `(trace, report)`; the caller decides what
    to do with the report (the CLI prints it and exits on the gate).
    """
    with demo_servers() as (_llm, llm_server, api_server):
        app = build_graph(api_server.base_url, llm_server.base_url)
        result = app.invoke({"messages": [{"role": "user", "content": USER_MESSAGE}]})
    trace = messages_to_trace(result["messages"], run_id=RUN_ID, seed=SEED, expected=EXPECTED)
    return trace, evaluate_run(trace)


@contextlib.contextmanager
def demo_servers() -> Iterator[tuple[ScriptedLLM, FakeOpenAIServer, PrismMockServer]]:
    """Start both demo mocks and yield `(llm, llm_server, api_server)`.

    The fake OpenAI server (demo scenario) and the Prism mock of the
    bundled ticket spec, both on localhost — $0, no real calls. The
    caller owns the graph and the runs: the scripted LLM is shared
    across runs, so call `llm.reset()` before each run to replay the
    scenario from the first turn. Exiting the context stops both
    servers.
    """
    if shutil.which("prism") is None:
        raise DemoError(
            f"the `prism` binary was not found on PATH — install it with {_PRISM_INSTALL_HINT}"
        )
    _check_demo_deps()
    scenario = parse_scenario(_SCENARIO_YAML, source="langgraph-demo scenario")
    with tempfile.TemporaryDirectory(prefix="simwork-demo-") as tmp:
        spec_path = Path(tmp) / "tickets-api.json"
        # Prism reads the spec as JSON (see `PrismMockServer`), so the
        # bundled YAML spec is converted on the way to the temp file.
        spec_path.write_text(json.dumps(yaml.safe_load(_TICKETS_API_YAML)), encoding="utf-8")
        llm = scenario.to_llm()
        with (
            FakeOpenAIServer(llm) as llm_server,
            PrismMockServer(spec_path) as api_server,
        ):
            yield llm, llm_server, api_server
