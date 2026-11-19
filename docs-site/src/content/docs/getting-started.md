---
title: Getting Started
description: Install SimWork, scaffold a working starter, and run the end-to-end demo in under 15 minutes.
---

SimWork lets a Python developer add simulation to an existing app or harness with minimal setup: every AI call routes to an LLM mock and every API call routes to an API mock. A full simulated run costs **$0 by default**, with zero real network calls to LLM providers or real world APIs.

Requires Python 3.11+.

## Install

Install from the repo:

```bash
pip install git+https://github.com/SRogDev/SimWork
simwork --help
```

Or work from a checkout (uses [uv](https://docs.astral.sh/uv/) only for the checkout path):

```bash
git clone https://github.com/SRogDev/SimWork
cd SimWork
uv sync
uv run simwork --help
uv run pytest
```

PyPI publication is not done yet — install from source or git, as above.

## Scaffold a starter

`simwork init` generates a working starter in a directory — your project dir, or a fresh one:

```bash
simwork init my-app
cd my-app
simwork serve --scenario scenarios/ticket-status.yaml   # fake OpenAI server
pytest                                                 # the eval suite passes
simwork eval --trace evals/ticket-status-trace.json    # the same gate, directly
```

It generates `simwork.yaml` (config: simulate mode, scenario + eval paths), `scenarios/ticket-status.yaml` (scripted LLM turns), `evals/ticket-status-trace.json` (the recorded trace of that run) and `tests/test_simwork_eval.py` (a pytest file that gates the trace on tool correctness + task completion), plus a starter README and the pre-made AI configuration prompt. The scenario parses and the trace passes the $0 gate before anything is written, so `init` can never scaffold a broken starter. Existing files owned by `init` are only overwritten with `--force`; other files in the directory — your harness — are never touched.

## Run the demo

The end-to-end proof: a small LangGraph agent that asks about ticket `T-123`, calls one LLM and one world API, and gates the run — all simulated, $0.

```bash
uv sync --group demo   # langgraph + langchain-openai + httpx (demo only)
npm i -g @stoplight/prism-cli   # the API-mock engine (Node 18+)
simwork demo           # prints the eval report + trace hash, exits 0 on PASS
simwork demo --trace evals/demo-trace.json --report evals/demo-report.json
```

## What next?

- [Routing & simulate mode](/guides/routing/) — point your own harness at the mocks.
- [Scenario files](/guides/scenarios/) — script what the mock LLM says.
- [API mocks](/guides/api-mocks/) — mock any API in the APIs.guru catalog.
- [Evals & the $0 gate](/guides/evals/) — how every run is judged.
- [AI configuration prompt](/guides/ai-prompt/) — hand the setup to an AI assistant.
- [CLI reference](/reference/cli/) — every command and flag.
