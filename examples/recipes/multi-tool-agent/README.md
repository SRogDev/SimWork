# Multi-tool agent recipe

A multi-tool agent, simulated end-to-end with SimWork: the
assistant plans a trip from New York to Paris on 2026-12-10 by
calling a `search_flights` tool — a thin wrapper over one endpoint
of the bundled travel API — then a `search_hotels` tool over the
same API, and finally answering with the total for flight + one
night ($420 + $120 = $540).

The point of this recipe is the **multi-tool pattern**: several
tools chained in one run, each call's arguments derived from an
earlier result. The hotel call asks for Paris from 2026-12-10
because the cheapest flight the first call returned (DL456, $420)
lands in Paris on 2026-12-10 — and the final answer is computed
from the chained results. That is the difference from the RAG
recipe, where the answer quotes one retrieved doc, and from the
API-backed recipe, where the answer is computed from one call. The
eval gate checks tool correctness + task completion, and the
recipe's own test additionally asserts the chain: the hotel
arguments match the cheapest flight's destination and arrival date,
and the total equals flight + hotel × nights.

## What's here

- `simwork.yaml` — starter config: simulate mode, scenario + eval paths.
- `scenarios/multi-tool-agent.yaml` — scripted LLM turns: call
  `search_flights`, then `search_hotels` with arguments from the
  flight result, then answer computed from both results.
- `travel-api.yaml` — the travel API spec (flights + hotels
  operations), hand-written for the recipe with fixed `example:`
  responses, so the Prism mock returns deterministic data. The
  flight list is deliberately unsorted — the agent picks the
  cheapest.
- `evals/multi-tool-agent-trace.json` — the recorded trace of the run.
- `tests/test_multi_tool_agent.py` — the eval suite: it gates the
  trace on tool correctness + task completion and asserts the chain
  (hotel arguments from the flight result, total from both results).
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
simwork serve --scenario scenarios/multi-tool-agent.yaml
simwork eval --trace evals/multi-tool-agent-trace.json
```

`run.py` exits 0 when the gate passes, 1 when it fails. Everything
runs on localhost — $0, no real LLM calls, no real world-API calls.

## Make it yours

- Change the trip in `run.py` (`USER_QUESTION`) and the flights and
  hotels in `travel-api.yaml`, then update the scenario turns to
  match: the scripted LLM must call `search_flights` with your
  route and date, `search_hotels` with the cheapest flight's
  destination city and arrival date, and compute the total from the
  two results.
- Chain another tool: add its operation to the spec, add a tool
  definition in `run.py` following the same 1:1 mapping (operation
  → tool, path/query parameters → tool arguments), and extend the
  scenario turns — each new call's arguments should come from an
  earlier result, and the test will catch a chain that does not.
- Re-record the trace: `python run.py --trace-out
  evals/multi-tool-agent-trace.json` rewrites the recorded trace file
  from a live run (it must match the scenario, or the eval suite
  will fail — the checked-in file is the trace of the checked-in
  scenario).
