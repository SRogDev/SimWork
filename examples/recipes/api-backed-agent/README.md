# API-backed agent recipe

An API-backed agent, simulated end-to-end with SimWork: the
assistant answers "How much is 100 US dollars in euros and pounds?"
by calling a `get_exchange_rates` tool, which hits a Prism mock of
the ExchangeRate-API spec fetched from the APIs.guru catalog — then
answers by computing from the structured rates the API returns
(100 USD × 0.92 = 92 EUR, 100 USD × 0.79 = 79 GBP).

The point of this recipe is the **API-backed pattern**: the agent's
tools ARE the world API — each tool maps 1:1 to an OpenAPI
operation (`GET /latest/{base_currency}`), and the final answer is
computed from the API's structured fields, not quoted from prose.
That is the difference from the RAG recipe, where the answer quotes
a retrieved doc. The eval gate checks tool correctness + task
completion, and the recipe's own test additionally asserts the
amounts in the answer equal 100 USD times the rates the tool result
returned.

## What's here

- `simwork.yaml` — starter config: simulate mode, scenario + eval paths.
- `scenarios/api-backed-agent.yaml` — scripted LLM turns: call
  `get_exchange_rates`, then answer computed from the rates.
- `exchangerate-api.yaml` — the ExchangeRate-API v4 spec, fetched
  from the APIs.guru catalog
  (`https://api.apis.guru/v2/specs/exchangerate-api.com/4/openapi.json`)
  and converted JSON → YAML. One addition, marked in the file: a
  fixed `example:` on the 200 response, so the Prism mock returns
  deterministic rates (the fetched spec has no example for `rates`).
- `evals/api-backed-agent-trace.json` — the recorded trace of the run.
- `tests/test_api_backed_agent.py` — the eval suite: it gates the
  trace on tool correctness + task completion and asserts the answer
  is computed from the API rates.
- `run.py` — runs the recipe live: fake OpenAI server + Prism mock,
  a raw-HTTP agent loop (no LangGraph — this is the plain
  OpenAI-compatible-client pattern), trace recorded and gated.

## Run it

```bash
# From this directory, with SimWork installed and the demo group:
#   uv sync --group demo        (from the repo root; installs httpx)
#   npm i -g @stoplight/prism-cli
python run.py                   # live run: both mocks, gate printed
pytest                          # the eval suite passes
simwork serve --scenario scenarios/api-backed-agent.yaml
simwork eval --trace evals/api-backed-agent-trace.json
```

`run.py` exits 0 when the gate passes, 1 when it fails. Everything
runs on localhost — $0, no real LLM calls, no real world-API calls.

## Make it yours

- Change the question in `run.py` (`USER_QUESTION`) and the rates in
  `exchangerate-api.yaml`, then update the scenario turns to match:
  the scripted LLM must call `get_exchange_rates` with your base
  currency and compute the answer from the returned rates.
- Expose another endpoint as another tool: add its OpenAPI operation
  to the spec, add a tool definition in `run.py` following the same
  1:1 mapping (operation → tool, path/query parameters → tool
  arguments), and extend the scenario turns. The multi-tool recipe
  shows several tools chained in one run.
- Re-record the trace: `python run.py --trace-out
  evals/api-backed-agent-trace.json` rewrites the recorded trace file
  from a live run (it must match the scenario, or the eval suite
  will fail — the checked-in file is the trace of the checked-in
  scenario).
