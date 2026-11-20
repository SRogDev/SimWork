---
title: Polygrow pilot
description: One real Polygrow flow simulated end-to-end with SimWork — a Mind chat turn, with the honest finding it surfaced.
---

The first real harness simulated with SimWork — not the toy demo. The pilot
runs one real Polygrow flow end-to-end in simulate mode: a Mind chat turn
(`POST /api/v1/chat` → the `ai_mind` LangGraph graph) for a general-chat
message.

```bash
simwork pilot
```

## What it mirrors

The pilot (`simwork.pilot`) mirrors the real graph's node sequence from the
Polygrow checkout (`main` @ `7655a65`):

```
entry → context_gatherer → intent_router → response_formatter → memory_write
```

- The route is decided by the real `route_after_intent` (confidence
  threshold 0.6), ported verbatim from `ai_services/app/ai_mind/router.py`.
- The intent-classification prompt is verbatim from `intent_router_node`
  (`ai_services/app/ai_mind/nodes.py`) — verified byte-identical — and the
  router model is the real default, `openai/gpt-4o-mini`.
- The deterministic intent rules (artifact create/modify, personalized-agent
  creation, workflow creation, BI requests) are ported verbatim from the
  same router file.

## What is mocked, and what stands in for what

- The LLM call — the intent-router fallback, since Jev is an external
  service, unavailable in sim by design — goes to SimWork's scripted fake
  OpenAI server, fed by the pilot scenario.
- The context gatherer reads business context from a Prism mock of a small
  bundled context API — it stands in for the real `ContextBuilder`
  (Supabase/session memory), which the pilot does not stand up.
- The memory write posts the turn to the stateful stub and reads it back —
  it stands in for the real `SessionMemory` (Supabase).

The pilot is a faithful replica of the flow, not the live `ai-services`
import: running the real graph would need Supabase, keys and the whole
service. That gap is documented, not hidden.

## The calibration sample

`examples/polygrow-pilot/calibration.yaml` carries a small set of real user
messages with the intent the real Mind code assigns them, each with its
source rule — for example `"crea un producto"` → `artifact_create` at 0.9
(`is_artifact_create_request`), and `"¿Por qué cayó la venta este mes?"` →
a BI request, so the planner emits `delegate:bi`. The pure-rules test
(`tests/test_pilot.py::test_calibration_sample_matches_real_rules`) checks
every deterministic case; the LLM-classified case is verified by the
end-to-end run.

## The honest finding

For a confident `general_chat` turn the real graph returns
"No response generated." — `route_after_intent` sends it straight to
`response_formatter`, and no node before it sets `ai_response`. The pilot
reproduces this faithfully and the gate passes on it:

```text
SimWork eval report — run: polygrow-pilot-mind-chat-1 (seed 7)
trace: 2f05d6cc3ad4842c…
  tool_correctness: 1.00 (threshold 1.00) PASS — no tool calls expected and none made
  task_completion: 1.00 (threshold 1.00) PASS — final answer contains all expected facts
Overall: PASS
Pilot: intent general_chat (confidence 0.85) → route response_formatter
Finding: The real Mind graph returns 'No response generated.' for a confident
general_chat turn ...
```

The simulation surfaces a real gap before launch instead of pretending the
chat works. Two live runs produce the identical trace hash (`2f05d6cc…`),
gate PASS, $0.

## Known limits of this slice

- Only the general-chat flow is covered (one message, one route). Other
  intents route to the planner/executor/core-agent paths, which need the
  Core Agent registry and task persistence — later slices.
- The `@Agent` mention rule is not ported: it needs the business's agent
  registry. The pilot message carries no "@".
- The context API and the memory write stand in for the real
  `ContextBuilder` / `SessionMemory`; their outputs are simulated, clearly
  labelled as such.
