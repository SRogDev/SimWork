# Polygrow pilot

One real Polygrow flow simulated end-to-end with SimWork: a Mind chat
turn (`POST /api/v1/chat` → the `ai_mind` LangGraph graph) for a plain
general-chat message. Run it with:

```bash
simwork pilot
```

The pilot mirrors the real graph's node sequence and routing rules from
the Polygrow checkout (`main` @ `7655a65`): `entry → context_gatherer →
intent_router → response_formatter → memory_write`, with the route decided
by the real `route_after_intent` (confidence threshold 0.6) and the
intent-classification prompt verbatim from `nodes.py`. The LLM call goes
to SimWork's scripted fake OpenAI server; the business context comes from
a Prism mock; the memory write goes to the stateful stub and is read back.

## Files

- `calibration.yaml` — a small calibration sample: real user messages with
  the intent the real Mind code assigns them, each with its source rule.
- The pilot harness itself lives in `src/simwork/pilot.py` (scenario,
  context-API spec, graph, eval gate), following the `simwork/demo.py`
  pattern; `tests/test_pilot.py` covers it.

## Honest finding

For a confident `general_chat` turn the real graph returns
"No response generated." — `route_after_intent` sends it straight to
`response_formatter`, and no node before it sets `ai_response`. The pilot
reproduces this faithfully and the gate passes on it: the simulation
surfaces a real gap before launch instead of pretending the chat works.

## Known limits of this slice

- The pilot is a faithful replica of the flow, not the live `ai-services`
  import: running the real graph would need Supabase, keys and the whole
  service.
- Only the general-chat flow is covered (one message, one route). Other
  intents route to the planner/executor/core-agent paths, which need the
  Core Agent registry and task persistence — later slices.
- The `@Agent` mention rule is not ported: it needs the business's agent
  registry. The pilot message carries no "@".
- The context API and the memory write stand in for the real
  `ContextBuilder` / `SessionMemory` (Supabase); their outputs are
  simulated, clearly labelled as such.
