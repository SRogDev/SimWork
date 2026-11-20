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

## Coming next

- **API-backed agent** — an agent whose tools are real world-API
  calls, all served by Prism mocks from APIs.guru specs.
- **Multi-tool agent** — an agent that chains several tools in one
  run, with the trace gating every tool call in order.
