# SimWork

Simulate AI-app functionality first — before spending real LLM or world API calls — with evals on every run.

SimWork lets a Python developer add simulation to an existing app or harness with minimal setup: every AI call routes to an LLM mock and every API call routes to an API mock. A full simulated run costs **$0 by default**, with zero real network calls to LLM providers or real world APIs.

> **Status: Phase 3 — DeepEval harness, first slice done (v0.1.0).** Tenro 0.2.3 was evaluated and **not** adopted as the interception layer (it requires decorating the harness, which contradicts the spec's no-rewrite rule — see `docs/tenro-evaluation-2026-11-16.md`). SimWork's own scripted, deterministic fake OpenAI server is in place (`simwork.llm`: `ScriptedLLM` + `FakeOpenAIServer`), scripted turns load from YAML scenario files (`simwork.llm.load_scenario`), and routing is wired: `SIMWORK_MODE=simulate` + a scenario file starts the mock server (`simwork serve` or `SimWorkRouter`), 111 tests. `simwork mock --api <name>` fetches an API's OpenAPI spec from APIs.guru and serves it as a mock with Prism, and `simwork mock --stateful` adds the stateful stub layer (create-then-read returns the created record — see below). `simwork eval` evaluates a recorded run trace with the deterministic metrics tool correctness + task completion and prints a pass/fail report (see below). DeepEval 4.3.4 was verified: its `ToolCorrectnessMetric` is deterministic and works offline, but its constructor demands an `OPENAI_API_KEY`, so the $0 gate computes the two metrics natively with the same semantics — see `docs/deepeval-wiring-2026-11-17.md`. `simwork init` + demo (Phase 4) are not built yet. See `docs/` for the spec.

## Quickstart

```bash
uv sync
uv run simwork --help
uv run pytest
```

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

## Routing (`SIMWORK_MODE=simulate`)

Routing decides where AI calls go. In simulate mode every AI call routes to the mock LLM server; in live mode SimWork does nothing and the harness talks to its real provider. Anything misconfigured fails closed instead of silently falling back to a real call.

```bash
# Serve the mock from a scenario file (prints the env vars to point at it)
simwork serve --scenario scenario.yaml --port 8123
# OPENAI_BASE_URL=http://127.0.0.1:8123/v1
# OPENAI_API_KEY=simwork-simulated
```

Environment variables:

| Variable | Meaning |
|---|---|
| `SIMWORK_MODE` | `simulate` or `live` (default `live` — simulate is explicit opt-in, so an unset variable never silently intercepts a harness) |
| `SIMWORK_SCENARIO` | Path to the YAML scenario file; required in simulate mode |
| `SIMWORK_HOST` | Bind host for the fake server (default `127.0.0.1`) |
| `SIMWORK_PORT` | Bind port (default `0` = ephemeral) |

From Python, the same routing is available as a context manager — the harness only needs a base-URL swap:

```python
import os
from simwork import SimWorkRouter

with SimWorkRouter.from_env() as router:  # reads SIMWORK_MODE / SIMWORK_SCENARIO
    os.environ.update(router.env_overrides)  # OPENAI_BASE_URL + dummy OPENAI_API_KEY
    run_harness()  # $0, no real LLM calls
```

## Scenario files

A scenario is a YAML file that scripts what the mock LLM says, turn by turn — no code needed. Loading is strict: a bad schema fails closed with `ScenarioError` instead of silently producing a wrong script.

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

```python
from simwork.llm import load_scenario

llm = load_scenario("scenario.yaml").to_llm()  # deterministic ScriptedLLM
```

## API mock (`simwork mock`)

Any API in the [APIs.guru](https://apis.guru) catalog (2,529 APIs) can be served as a mock, with no real calls to the real API. Requires Node 18+ and Prism (`npm i -g @stoplight/prism-cli`); the spec is downloaded once and cached under `~/.cache/simwork`.

```bash
# Serve the httpbin API as a mock (prints the base URL to point at)
simwork mock --api httpbin.org --port 8124
# API_BASE_URL=http://127.0.0.1:8124

# With the stateful stub layer: writes are remembered, so create-then-read
# returns the created record (Prism alone is stateless)
simwork mock --api httpbin.org --port 8124 --stateful
```

Prism alone is stateless, so SimWork adds a state layer (`simwork.stateful`): a small proxy in front of Prism that remembers JSON writes per collection path. A `POST` stores the record (assigning a sequential `id` when the body has none) and answers `201`; a later `GET` on the collection returns the stored list and `GET <collection>/<id>` returns the stored record; `PUT`/`PATCH`/`DELETE` update or remove it. Reads on paths with nothing stored forward to Prism unchanged, so its example/schema behaviour is preserved. State is in-memory per process — restarting the mock resets the world, which keeps runs deterministic. An unknown API name, a download failure, a missing `prism` binary, or a Prism process that exits early all fail closed with a visible error instead of falling back to the real API.

## Eval (`simwork eval`)

Every simulated run is evaluated. The first slice evaluates a recorded run trace (JSON) with two deterministic metrics — **tool correctness** (share of expected tool calls matched exactly, name + arguments) and **task completion** (the final answer contains the expected facts) — and produces a pass/fail report. No LLM judge, no network, $0. Both metrics default to a strict threshold of 1.0.

```bash
# Evaluate a recorded trace (see examples/ticket-status-trace.json)
simwork eval --trace trace.json
# SimWork eval report — run: ticket-status-1 (seed 7)
# trace: b0122a56efdfda2a9df27860cb73344c05f1855f6e36622b76b7d1bcca7bd5e0
#   tool_correctness: 1.00 (threshold 1.00) PASS — 1/1 expected tool call(s) matched
#   task_completion: 1.00 (threshold 1.00) PASS — final answer contains all expected facts
# Overall: PASS

# Also write the machine-readable JSON report
simwork eval --trace trace.json --report report.json
```

A trace is a JSON object with `steps` (assistant turns, with `content` and/or `tool_calls`, plus `tool_result` steps) and `expected` (`tool_calls` the run should have made, `final_answer_contains` facts the final answer should cover). Loading is strict: a bad trace fails closed instead of producing a wrong report. The report carries a `trace_hash` (SHA-256 of the canonical trace JSON), so the same seed + same scenario run twice produces an identical report. DeepEval's own metric classes were verified but are not a dependency of this slice — its `ToolCorrectnessMetric` demands an `OPENAI_API_KEY` at construction, which would break the $0 default (see `docs/deepeval-wiring-2026-11-17.md`); LLM-judge metrics stay opt-in for a later slice.

## The $0 default

In simulate mode SimWork makes zero real calls to LLM providers and zero real calls to world APIs, and fails closed — it errors visibly instead of silently falling back to a real call if a mock is missing.

## Roadmap (v0.1)

| Phase | What | Status |
|---|---|---|
| 0 | Repo foundation: package, CLI, licence, CI | ✅ Done |
| 1 | LLM mock (OpenAI-compatible, scripted + deterministic) + routing | ✅ Done — Tenro evaluated, not adopted (see `docs/tenro-evaluation-2026-11-16.md`); scripted LLM + fake server + YAML scenarios + routing (`SIMWORK_MODE` / `simwork serve`) landed |
| 2 | API mock via Prism + APIs.guru, with a stateful stub layer | ✅ Done — `simwork mock --api` (fetch from APIs.guru + Prism serve) and `--stateful` (create-then-read via a proxy in front of Prism, `simwork.stateful`) landed |
| 3 | DeepEval harness + pass/fail report | First slice done — `simwork eval` over a recorded trace (tool correctness + task completion, deterministic, $0); LLM-judge metrics stay opt-in |
| 4 | `simwork init` + pre-made AI configuration prompt + LangGraph demo end-to-end | Planned |

Out of scope for v0.1: a managed/hosted service (not designed before 7 days after start), a Rust rewrite, TypeScript harness support, a real LLM judge by default.

## Licence

MIT — see [LICENSE](LICENSE).
