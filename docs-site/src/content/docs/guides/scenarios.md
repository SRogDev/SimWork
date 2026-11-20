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

## Scenario families

A family is one YAML file that generates many scenarios: named parameters with value lists, `{{param}}` placeholders in the turns (and in the optional `expected:` block), and a base seed. Member `i` gets seed `base + i` and its parameter values from a PRNG seeded with that member seed — the same family + index always yields the same scenario.

```yaml
name: ticket-status-family   # optional
seed: 7                      # optional, default 0
parameters:                  # required, non-empty
  ticket_id: ["T-101", "T-202", "T-303"]
  status: ["shipped", "processing", "delivered"]
turns:                       # required, non-empty (scenario shape)
  - tool_calls:
      - name: lookup_ticket
        arguments: {ticket_id: "{{ticket_id}}"}
  - content: "Your {{ticket_id}} replacement has {{status}}."
expected:                    # optional, trace-expected shape
  tool_calls:
    - name: lookup_ticket
      arguments: {ticket_id: "{{ticket_id}}"}
  final_answer_contains: ["{{status}}"]
```

A whole-string `{{param}}` keeps the value's type (an int stays an int in tool arguments); inside a longer string the value is interpolated as text. Without an `expected:` block it is derived from the member's own turns — the tool calls the script makes are the expected ones, nothing demanded of the final answer. Loading is strict: an undeclared placeholder or a bad schema fails closed with `FamilyError`.

```bash
simwork serve --family examples/ticket-status-family.yaml --member 2  # serve one member
simwork scale --family examples/ticket-status-family.yaml --runs 100   # one member per run
```

From Python:

```python
from simwork.families import load_family

family = load_family("family.yaml")
member = family.member(0)  # deterministic: seed 7, parameters picked from the lists
llm = member.scenario.to_llm()
```
