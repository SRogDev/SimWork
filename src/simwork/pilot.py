"""The Polygrow pilot (adoption readiness criterion 3, slice 1).

One real Polygrow flow simulated end-to-end: a Mind chat turn
(`POST /api/v1/chat` → the `ai_mind` LangGraph graph) for a plain
general-chat message. The pilot mirrors the real graph's node sequence
and routing rules, copied from the Polygrow checkout
(`~/workspace/polygrow-main`, `main` @ `7655a65`):

- entry → context_gatherer → intent_router → response_formatter →
  memory_write → END (`ai_services/app/ai_mind/graph.py`);
- routing per `route_after_intent` (`ai_services/app/ai_mind/router.py`,
  confidence threshold 0.6);
- the intent-classification prompt is verbatim from
  `intent_router_node` (`ai_services/app/ai_mind/nodes.py`), and the
  router model is the real default (`openai/gpt-4o-mini`,
  `ai_services/app/shared/config.py`).

What is mocked, and what stands in for what:

- the LLM call (the intent-router fallback — Jev is an external
  service, unavailable in sim by design, so the real code's LLM
  fallback is the path exercised) goes to SimWork's scripted fake
  OpenAI server, fed by the pilot scenario;
- the context gatherer reads business context from a Prism mock of
  the bundled context-API spec — it stands in for the real
  `ContextBuilder` (Supabase/session memory), which the pilot does
  not stand up;
- the memory write posts the turn to the stateful stub and reads it
  back — it stands in for the real `SessionMemory` (Supabase).

The pilot is a faithful replica of the flow, not the live
`ai-services` import: running the real graph would need Supabase,
keys and the whole service. That gap is documented, not hidden.

Honest finding the pilot reproduces: for a confident `general_chat`
turn the real graph returns "No response generated." —
`route_after_intent` sends it straight to `response_formatter`, and
no node before it sets `ai_response`. The pilot asserts exactly that
behaviour, so the simulation surfaces a real gap before launch
instead of pretending the chat works.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypedDict

import yaml

from simwork.api_mock import PrismMockServer
from simwork.eval import EvalReport, evaluate_run
from simwork.llm import FakeOpenAIServer, ScriptedLLM, parse_scenario
from simwork.stateful import StatefulStubServer
from simwork.trace import Trace, validate_trace

_PILOT_DEPS_HINT = (
    "the Polygrow pilot needs the demo dependencies "
    "(langgraph, langchain-openai, httpx) — install them with "
    "`uv sync --group demo`"
)
_PRISM_INSTALL_HINT = "npm i -g @stoplight/prism-cli (requires Node 18+)"

RUN_ID = "polygrow-pilot-mind-chat-1"
SEED = 7
# The real router model: settings.openrouter_default_chat_model.
ROUTER_MODEL = "openai/gpt-4o-mini"
USER_MESSAGE = "Hola, ¿qué puedes hacer por mi negocio?"
# Simulated identifiers (fixed, so the run is deterministic). They are
# not real Polygrow ids — the pilot never touches a real database.
BUSINESS_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"
SESSION_ID = "pilot-session-1"

# The scripted intent classification for the pilot message: the real
# flow's LLM fallback answers `general_chat` with high confidence, so
# the real router sends the turn straight to `response_formatter`.
_SCENARIO_YAML = """\
name: polygrow-pilot-mind-chat
seed: 7
model: openai/gpt-4o-mini
turns:
  - content: '{"intent": "general_chat", "confidence": 0.85}'
"""

# The world API the pilot's context gatherer and memory writer call:
# one context endpoint (Prism serves the example) and the session
# messages collection (the stateful stub remembers the writes, so the
# read-back proves the memory write landed). The context example is a
# clearly simulated stand-in for the real ContextBuilder output.
_CONTEXT_API_YAML = """\
openapi: 3.0.0
info:
  title: Polygrow Context API (pilot stand-in)
  version: 1.0.0
paths:
  /businesses/{business_id}/context:
    get:
      parameters:
        - name: business_id
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
                  business_id:
                    type: string
                  name:
                    type: string
                  context:
                    type: string
                required: [business_id, name, context]
              example:
                business_id: "11111111-1111-4111-8111-111111111111"
                name: "Demo Business"
                context: "Demo Business is a small café selling coffee and pastries."
  /sessions/{session_id}/messages:
    get:
      parameters:
        - name: session_id
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
                type: array
                items:
                  type: object
              example: []
    post:
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                role:
                  type: string
                content:
                  type: string
              required: [role, content]
      responses:
        '201':
          description: created
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                  role:
                    type: string
                  content:
                    type: string
"""

# The expected outcome of the pilot run: no tool calls (the intent
# classification is a plain completion, like the real
# `openrouter_client.generate`), and the final answer is exactly what
# the real graph produces for this turn.
EXPECTED: dict[str, Any] = {
    "tool_calls": [],
    "final_answer_contains": ["No response generated."],
}

FINDING = (
    "The real Mind graph returns 'No response generated.' for a confident "
    "general_chat turn: route_after_intent sends it straight to "
    "response_formatter, and no node before it sets ai_response. The pilot "
    "reproduces this faithfully — simulation surfacing a real gap before "
    "launch, not a passing chat."
)


class PilotError(Exception):
    """Raised when the pilot cannot run (missing deps, missing prism)."""


# -- Real routing rules, ported from ai_services/app/ai_mind/router.py --
# Term lists are verbatim; the pilot only ports the pure rules, no
# database or registry lookups. The @-mention rule is not ported: it
# needs the business's agent registry, and the pilot message carries
# no "@" — `classify_deterministic` documents that limit.

CONFIDENCE_THRESHOLD = 0.6

_BI_TERMS = (
    "ventas",
    "revenue",
    "ingresos",
    "conversion",
    "kpi",
    "métrica",
    "metric",
    "anomalía",
    "problema en el negocio",
    "forecast",
    "tendencia",
    "oportunidad",
    "riesgo",
    "por qué cayó",
)
_ARTIFACT_MODIFY_TERMS = (
    "hazla más grande",
    "hazlo más grande",
    "hazla más pequeña",
    "hazlo más pequeño",
    "cambia el material",
    "cambia el color",
    "cambia el tamaño",
    "modifica el producto",
    "modifica este producto",
    "make it bigger",
    "make it smaller",
    "change the material",
)
_ARTIFACT_CREATE_TERMS = (
    "crea un producto",
    "crea un artefacto",
    "diseña un producto",
    "create a product",
    "design a product",
)
_PERSONALIZED_CREATE_TERMS = (
    "i want to create a personalized agent",
    "create a personalized agent",
    "crear un agente personalizado",
    "quiero crear un agente",
    "create agent",
)
_WORKFLOW_CREATE_TERMS = (
    "create a workflow",
    "crear un workflow",
    "quiero crear un workflow",
    "new workflow",
    "crear un flujo de trabajo",
    "quiero un flujo de trabajo",
)


def is_bi_request(message: str) -> bool:
    return any(term in message.lower() for term in _BI_TERMS)


def is_artifact_modify_request(message: str, *, has_active_artifact: bool) -> bool:
    if not has_active_artifact:
        return False
    return any(term in message.lower() for term in _ARTIFACT_MODIFY_TERMS)


def is_artifact_create_request(message: str) -> bool:
    return any(term in message.lower() for term in _ARTIFACT_CREATE_TERMS)


def is_personalized_agent_creation_request(message: str) -> bool:
    return any(term in message.lower() for term in _PERSONALIZED_CREATE_TERMS)


def is_workflow_creation_request(message: str) -> bool:
    return any(term in message.lower() for term in _WORKFLOW_CREATE_TERMS)


def classify_deterministic(
    message: str, *, has_active_artifact: bool = False
) -> tuple[str, float] | None:
    """The deterministic intent rules from `intent_router_node`, in order.

    Returns `(intent, confidence)` when a rule fires, else None — the
    caller then falls through to the LLM call, exactly like the real
    node (after its Jev attempt, which is unavailable in sim). Messages
    containing "@" are not classified here: the real mention rule needs
    the business's agent registry, which the pilot does not stand up.
    """
    if "@" in message:
        return None
    if is_artifact_modify_request(message, has_active_artifact=has_active_artifact):
        return ("artifact_modify", 0.9)
    if is_artifact_create_request(message):
        return ("artifact_create", 0.9)
    if is_personalized_agent_creation_request(message):
        return ("personalized_agent_create", 0.9)
    if is_workflow_creation_request(message):
        return ("workflow_create", 0.9)
    return None


def route_after_intent(intent: str, confidence: float) -> str:
    """The real router (`router.py:route_after_intent`), verbatim logic."""
    if confidence < CONFIDENCE_THRESHOLD:
        return "planner"
    if intent in (
        "capability",
        "automation_request",
        "support_request",
        "artifact_create",
        "artifact_modify",
        "personalized_agent_create",
        "personalized_agent_invoke",
        "workflow_create",
    ):
        return "planner"
    if intent == "proactivity_response":
        return "executor"
    return "response_formatter"


def intent_prompt(message: str) -> str:
    """The real intent-classification prompt (`nodes.py:intent_router_node`).

    Verbatim, with only the user message substituted — so the scripted
    LLM answers the same question the real router asks.
    """
    return (
        "Classify the user intent for this message:\n\n"
        f"User: {message}\n\n"
        'Respond with JSON: {"intent": "<type>", "confidence": <0-1>}\n'
        "Intent types: capability, proactivity_response, general_chat, automation_request, support_request. "  # noqa: E501 — verbatim from the real prompt in nodes.py; must stay byte-identical.
        "Use support_request only for help using Polygrow or troubleshooting Polygrow itself; "
        "businesses serving their own customers is not Polygrow support."
    )


def _check_pilot_deps() -> None:
    """Fail closed with the install hint when the demo group is missing."""
    try:
        import langchain_core  # noqa: F401
        import langchain_openai  # noqa: F401
        import langgraph  # noqa: F401
    except ImportError as e:
        raise PilotError(_PILOT_DEPS_HINT) from e


class PilotState(TypedDict, total=False):
    """State of one pilot run (mirrors the real `AIMindState` fields used)."""

    session_id: str
    business_id: str
    user_id: str
    user_message: str
    context: dict[str, Any]
    intent: str
    confidence: float
    intent_completion: str
    ai_response: str
    memory_messages: list[dict[str, Any]]


def build_graph(api_base_url: str, llm_base_url: str):
    """Build the pilot graph: the real Mind node sequence for this flow.

    `entry → context_gatherer → intent_router → response_formatter →
    memory_write → END`, with the route decided by the real
    `route_after_intent`. Only the `response_formatter` route is
    implemented — the pilot covers one flow, and any other route ends
    the run so `run_pilot` can fail closed with a clear message instead
    of silently running a different flow.
    """
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, START, StateGraph

    import httpx

    llm = ChatOpenAI(
        model=ROUTER_MODEL,
        base_url=llm_base_url,
        api_key="simwork-simulated",
        temperature=0,
        max_retries=0,
    )

    def entry_node(state: PilotState) -> dict[str, Any]:
        return {
            "session_id": SESSION_ID,
            "business_id": BUSINESS_ID,
            "user_id": USER_ID,
            "user_message": USER_MESSAGE,
            "intent": "",
            "confidence": 0.0,
            "ai_response": "",
        }

    def context_gatherer_node(state: PilotState) -> dict[str, Any]:
        # trust_env=False: the node talks to the local mock directly —
        # never via a proxy from the environment (see demo.py).
        response = httpx.get(
            f"{api_base_url}/businesses/{state['business_id']}/context",
            timeout=10.0,
            trust_env=False,
        )
        response.raise_for_status()
        return {"context": response.json()}

    def intent_router_node(state: PilotState) -> dict[str, Any]:
        decided = classify_deterministic(state["user_message"])
        if decided is not None:
            intent, confidence = decided
            return {
                "intent": intent,
                "confidence": confidence,
                "intent_completion": json.dumps({"intent": intent, "confidence": confidence}),
            }
        # No deterministic rule fired: the LLM fallback, like the real
        # node when Jev is unavailable (always, in sim — no real calls).
        completion = llm.invoke([HumanMessage(content=intent_prompt(state["user_message"]))])
        content = completion.content if isinstance(completion.content, str) else ""
        try:
            parsed = json.loads(content)
            return {
                "intent": parsed.get("intent", "general_chat"),
                "confidence": parsed.get("confidence", 0.5),
                "intent_completion": content,
            }
        except (json.JSONDecodeError, AttributeError, TypeError):
            return {
                "intent": "general_chat",
                "confidence": 0.5,
                "intent_completion": content,
            }

    def route_node(state: PilotState) -> str:
        return route_after_intent(state["intent"], state["confidence"])

    def response_formatter_node(state: PilotState) -> dict[str, Any]:
        # Faithful to the real node: it passes ai_response through, and
        # nothing before it set one — so a confident general_chat turn
        # ends here with "No response generated."
        raw = state.get("ai_response", "")
        if not raw:
            return {"ai_response": "No response generated."}
        return {"ai_response": raw}

    def memory_write_node(state: PilotState) -> dict[str, Any]:
        # The real SessionMemory writes to Supabase; the pilot writes to
        # the stateful stub and reads the turn back to prove it landed.
        messages_url = f"{api_base_url}/sessions/{state['session_id']}/messages"
        for role, content in (
            ("user", state["user_message"]),
            ("assistant", state["ai_response"]),
        ):
            response = httpx.post(
                messages_url,
                json={"role": role, "content": content},
                timeout=10.0,
                trust_env=False,
            )
            response.raise_for_status()
        read_back = httpx.get(messages_url, timeout=10.0, trust_env=False)
        read_back.raise_for_status()
        return {"memory_messages": read_back.json()}

    graph = StateGraph(PilotState)
    graph.add_node("entry", entry_node)
    graph.add_node("context_gatherer", context_gatherer_node)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("response_formatter", response_formatter_node)
    graph.add_node("memory_write", memory_write_node)
    graph.add_edge(START, "entry")
    graph.add_edge("entry", "context_gatherer")
    graph.add_edge("context_gatherer", "intent_router")
    graph.add_conditional_edges(
        "intent_router",
        route_node,
        {"response_formatter": "response_formatter", "planner": END, "executor": END},
    )
    graph.add_edge("response_formatter", "memory_write")
    graph.add_edge("memory_write", END)
    return graph.compile()


def state_to_trace(state: PilotState) -> Trace:
    """Convert a finished pilot run's state into an eval trace.

    Steps in run order: the context read, the intent-classification
    completion, the memory write + read-back, and the final answer.
    """
    steps: list[dict[str, Any]] = [
        {"type": "tool_result", "name": "fetch_business_context", "result": state["context"]},
        {"type": "assistant", "content": state["intent_completion"]},
        {
            "type": "tool_result",
            "name": "memory_write",
            "result": {
                "stored": len(state["memory_messages"]),
                "messages": state["memory_messages"],
            },
        },
        {"type": "assistant", "content": state["ai_response"]},
    ]
    trace: Trace = {"run_id": RUN_ID, "seed": SEED, "steps": steps, "expected": EXPECTED}
    return validate_trace(trace)


def run_pilot() -> tuple[Trace, EvalReport, dict[str, Any]]:
    """Run the pilot end-to-end: both mocks, the graph, the eval gate.

    Starts the fake OpenAI server from the pilot scenario and the Prism
    mock of the bundled context API with the stateful stub in front
    (both on localhost — $0, no real calls), runs the Mind-chat graph
    once, records the trace and evaluates it. Returns
    `(trace, report, result)`; `result` carries the intent, the route
    and the honest finding. Raises `PilotError` when the run routes
    anywhere but `response_formatter` — the pilot covers one flow.
    """
    with pilot_servers() as (_llm, llm_server, api_base_url):
        app = build_graph(api_base_url, llm_server.base_url)
        result = app.invoke({})
    # The route is decided by the conditional edge, not written to state,
    # so recompute it from intent + confidence — and fail closed before
    # building a trace when the run took any other route.
    route = route_after_intent(result["intent"], result["confidence"])
    if route != "response_formatter":
        raise PilotError(
            f"pilot covers only the general_chat flow, but this run routed "
            f"to {route!r} (intent {result['intent']!r})"
        )
    trace = state_to_trace(result)
    report = evaluate_run(trace)
    pilot_result = {
        "run_id": RUN_ID,
        "intent": result["intent"],
        "confidence": result["confidence"],
        "route": route,
        "final_answer": result["ai_response"],
        "context_business": result["context"].get("name"),
        "memory_stored": len(result["memory_messages"]),
        "finding": FINDING,
    }
    return trace, report, pilot_result


@contextlib.contextmanager
def pilot_servers() -> Iterator[tuple[ScriptedLLM, FakeOpenAIServer, str]]:
    """Start both pilot mocks and yield `(llm, llm_server, api_base_url)`.

    The fake OpenAI server (pilot scenario) and the Prism mock of the
    bundled context-API spec, with the stateful stub proxy in front of
    Prism — the harness talks to the stub, which forwards the context
    read to Prism and remembers the memory writes. The caller owns the
    graph and the run; exiting the context stops all three servers.
    """
    _check_pilot_deps()
    if shutil.which("prism") is None:
        raise PilotError(
            f"the `prism` binary was not found on PATH — install it with {_PRISM_INSTALL_HINT}"
        )
    scenario = parse_scenario(_SCENARIO_YAML, source="polygrow-pilot scenario")
    with tempfile.TemporaryDirectory(prefix="simwork-pilot-") as tmp:
        spec_path = Path(tmp) / "context-api.json"
        spec_path.write_text(json.dumps(yaml.safe_load(_CONTEXT_API_YAML)), encoding="utf-8")
        llm = scenario.to_llm()
        with FakeOpenAIServer(llm) as llm_server, PrismMockServer(spec_path) as prism:
            with StatefulStubServer(prism.base_url) as stub:
                yield llm, llm_server, stub.base_url
