# RAG assistant recipe

A retrieval-augmented assistant, simulated end-to-end with SimWork:
the assistant answers a question about the returns policy by first
retrieving the relevant doc from a (mocked) docs API, then answering
grounded in what it retrieved — never from memory alone.

The point of this recipe is the **grounding pattern**: the scripted
LLM calls the `retrieve_docs` tool, the tool hits a Prism mock of a
docs-search API, and the final answer repeats a phrase from the
retrieved doc. The eval gate checks tool correctness + task
completion, and the recipe's own test additionally asserts grounding:
the final answer must contain a phrase that came from the tool
result, not from the model's script alone.

## What's here

- `simwork.yaml` — starter config: simulate mode, scenario + eval paths.
- `scenarios/rag-assistant.yaml` — scripted LLM turns: call
  `retrieve_docs`, then answer from the retrieved doc.
- `docs-api.yaml` — the OpenAPI spec of the docs-search API; Prism
  serves it as the world-API mock (`GET /search?q=...`).
- `evals/rag-assistant-trace.json` — the recorded trace of the run.
- `tests/test_rag_assistant.py` — the eval suite: it gates the trace
  on tool correctness + task completion and asserts grounding.
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
simwork serve --scenario scenarios/rag-assistant.yaml
simwork eval --trace evals/rag-assistant-trace.json
```

`run.py` exits 0 when the gate passes, 1 when it fails. Everything
runs on localhost — $0, no real LLM calls, no real world-API calls.

## Make it yours

- Change the question in `run.py` (`USER_QUESTION`) and the doc in
  `docs-api.yaml`, then update the scenario turns to match: the
  scripted LLM must call `retrieve_docs` with your query and answer
  from the doc text.
- Add more docs to the `results` example and more turns that call
  `retrieve_docs` again — the loop runs until the LLM answers with
  content (bounded at 5 turns, then it fails closed).
- Re-record the trace: `python run.py --trace-out
  evals/rag-assistant-trace.json` rewrites the recorded trace file
  from a live run (it must match the scenario, or the eval suite
  will fail — the checked-in file is the trace of the checked-in
  scenario).
