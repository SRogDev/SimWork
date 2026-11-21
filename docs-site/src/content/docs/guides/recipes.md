---
title: 'Recipes: runnable examples'
description: Short runnable patterns — RAG assistant, API-backed agent, multi-tool agent — each a copyable SimWork project.
---

Recipes are small, self-contained SimWork projects under
`examples/recipes/` — each one a pattern a developer can copy into
their own harness. Every recipe follows the `simwork init` starter
layout (`simwork.yaml` + scenario + recorded trace + pytest suite),
plus a `run.py` that runs the pattern live against both mocks and a
README that says what to change.

## RAG assistant (`examples/recipes/rag-assistant/`)

A retrieval-augmented assistant: it answers a question about the
returns policy by first calling the `retrieve_docs` tool, which hits
a Prism mock of a docs-search API, then answers grounded in the doc
it retrieved — never from memory alone.

```bash
cd examples/recipes/rag-assistant
python run.py                   # live run: both mocks, gate printed
pytest                          # the eval suite passes
simwork serve --scenario scenarios/rag-assistant.yaml
simwork eval --trace evals/rag-assistant-trace.json
```

The pattern worth copying is the grounding check: the recipe's own
test asserts the final answer contains a phrase from the retrieved
doc (`30 days from delivery`), not just that the gate passes. The
agent loop is a raw HTTP loop against the fake OpenAI server — the
plain-OpenAI-client pattern, no LangGraph — bounded at 5 turns and
failing closed on an unknown tool or a loop that never answers.

## API-backed agent (`examples/recipes/api-backed-agent/`)

An API-backed agent: it answers "How much is 100 US dollars in euros
and pounds?" by calling a `get_exchange_rates` tool — a thin wrapper
over one endpoint of the ExchangeRate-API spec, fetched from the
APIs.guru catalog — then computing the answer from the structured
rates the API returns (100 USD × 0.92 = 92 EUR, 100 USD × 0.79 =
79 GBP).

```bash
cd examples/recipes/api-backed-agent
python run.py                   # live run: both mocks, gate printed
pytest                          # the eval suite passes
simwork serve --scenario scenarios/api-backed-agent.yaml
simwork eval --trace evals/api-backed-agent-trace.json
```

The pattern worth copying is the 1:1 mapping from OpenAPI operation
to tool: each tool wraps one endpoint, path and query parameters
become tool arguments, and the answer is computed from the API's
structured fields, not quoted from prose. The recipe's own test
asserts the amounts in the answer equal 100 USD times the rates the
tool result returned. The bundled spec is the real ExchangeRate-API
v4 spec from APIs.guru, with one documented addition: a fixed
`example:` on the 200 response, so the mock returns deterministic
rates (the fetched spec has no example for `rates`). The agent loop
is the same raw-HTTP, bounded, fail-closed loop as the RAG recipe.

## Multi-tool agent (`examples/recipes/multi-tool-agent/`)

A multi-tool agent: it plans a trip from New York to Paris on
2026-12-10 by calling a `search_flights` tool — a thin wrapper over
one endpoint of a bundled travel API, served as a Prism mock — then
a `search_hotels` tool over the same API, and finally answering with
the total for flight + one night ($420 + $120 = $540).

```bash
cd examples/recipes/multi-tool-agent
python run.py                   # live run: both mocks, gate printed
pytest                          # the eval suite passes
simwork serve --scenario scenarios/multi-tool-agent.yaml
simwork eval --trace evals/multi-tool-agent-trace.json
```

The pattern worth copying is the chain: each tool call's arguments
come from an earlier result — the hotel call asks for Paris from
2026-12-10 because the cheapest flight the first call returned
(DL456, $420) lands in Paris on 2026-12-10 — and the final answer
is computed from the chained results. The recipe's own test asserts
the chain: the hotel arguments match the cheapest flight's
destination and arrival date, and the total equals flight + hotel ×
nights. The flight list in the bundled spec is deliberately
unsorted, so the agent picks the cheapest. The agent loop is the
same raw-HTTP, bounded, fail-closed loop as the RAG recipe.
