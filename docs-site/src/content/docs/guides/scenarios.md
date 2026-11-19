---
title: Scenario files
description: Script what the mock LLM says, turn by turn, in YAML — no code needed.
---

A scenario is a YAML file that scripts what the mock LLM says, turn by turn — no code needed. Loading is strict: a bad schema fails closed with `ScenarioError` instead of silently producing a wrong script.

## Format

```yaml
name: ticket-status        # optional
seed: 7                    # optional, default 0
model: simwork-mock        # optional, default "simwork-mock"
turns:                     # required, non-empty
  - content: "I will check the ticket."
  - tool_calls:
      - name: lookup_ticket
        arguments: {ticket_id: "T-123"}
  - content: "Your replacement has shipped."
```

Each turn is either assistant `content`, a `tool_calls` list (each with a `name` and `arguments`), or both. The scripted LLM replays the turns in order and raises `ScriptExhaustedError` when the script runs out, so an agent loop terminates instead of looping forever.

## Determinism

Keep `seed` fixed per scenario. Same seed + same scenario produces the same trace — and the same eval report — every time. That is what makes a simulated run reproducible and a thousand-run batch comparable.

From Python:

```python
from simwork.llm import load_scenario

llm = load_scenario("scenario.yaml").to_llm()  # deterministic ScriptedLLM
```

## Writing good scenarios

One scenario per behaviour you want to test. Script the tool calls the harness should make, in order, with the exact arguments you expect — the eval gate checks them. Ground the turns in real behaviour: copy the shape of real LLM replies and real tool results from the app's own logs or docs. A scenario that could never happen in production tests nothing.

Simulate failures too: timeouts, 500s, empty results, and malformed tool arguments belong in scenarios — an app that only passes on the happy path is not launch-ready.

For thousands of runs, write scenario *families*, not copies: parameterise scenarios by seed and by a small set of named variations (different user inputs, different tool results, different failure modes), so a thousand runs are a thousand different situations. See [Scale: 1,000 runs](/guides/scale/).
