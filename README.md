# SimWork

Simulate AI-app functionality first — before spending real LLM or world API calls — with evals on every run.

SimWork lets a Python developer add simulation to an existing app or harness with minimal setup: every AI call routes to an LLM mock and every API call routes to an API mock. A full simulated run costs **$0 by default**, with zero real network calls to LLM providers or real world APIs.

📖 **Documentation: https://simwork.vercel.app** — guides, CLI reference, and design decisions.

> **Status: v0.1.0 feature-complete — §7 acceptance criteria checked off 2026-11-19 (see below).** One item stays open by design: PyPI publication (a release decision for Roger — install from source/git is verified). CI is green on the latest landing (see the check-off). Tenro 0.2.3 was evaluated and **not** adopted as the interception layer (it requires decorating the harness, which contradicts the spec's no-rewrite rule — see `docs/tenro-evaluation-2026-11-16.md`). SimWork's own scripted, deterministic fake OpenAI server is in place (`simwork.llm`: `ScriptedLLM` + `FakeOpenAIServer`), scripted turns load from YAML scenario files (`simwork.llm.load_scenario`), and routing is wired: `SIMWORK_MODE=simulate` + a scenario file starts the mock server (`simwork serve` or `SimWorkRouter`), 316 tests. Scenario families (`simwork.families`: one YAML file generating many scenarios from named parameters + a seed — see below) landed 2026-11-20, with `simwork scale --family` running a different member per run. The Polygrow pilot (`simwork pilot` — see below) landed 2026-11-20: one real Polygrow flow (a Mind chat turn) simulated end-to-end with a scripted scenario + a small calibration sample, gate passing — and it surfaced a real gap: a confident general-chat turn returns "No response generated.". `simwork mock --api <name>` fetches an API's OpenAPI spec from APIs.guru and serves it as a mock with Prism, and `simwork mock --stateful` adds the stateful stub layer (create-then-read returns the created record — see below). `simwork eval` evaluates a recorded run trace with the deterministic metrics tool correctness + task completion and prints a pass/fail report, and a `TraceRecorder` (`simwork.trace`) captures such a trace from a real simulated run — assistant steps from the scripted LLM, tool-result steps from the harness executing the tools (see below). DeepEval 4.3.4 was verified: its `ToolCorrectnessMetric` is deterministic and works offline, but its constructor demands an `OPENAI_API_KEY`, so the $0 gate computes the two metrics natively with the same semantics — and the opt-in judge path (`simwork eval --judge`, `simwork.deepeval_judge`) now wires DeepEval's own classes, off by default, budgeted per run — see `docs/deepeval-wiring-2026-11-17.md`. `simwork init` scaffolds a working starter (config + scenario + eval suite — see below) and the pre-made AI configuration prompt (`prompts/configure-simwork.md` — see below). The LangGraph demo (`simwork demo` — see below) runs one LLM call against the fake server and one world-API call against a Prism mock, records the trace, and gates it — the end-to-end proof that the whole pipeline works at $0. The scale smoke test (`simwork scale` — see below) repeats that demo 1,000 times against shared mocks: 1000/1000 passed, one trace hash, 42.6s, $0 — the Polygrow pre-launch use case (thousands of runs) is demonstrably feasible. See `docs/` for the spec.

## Quickstart

Install from the repo — under 15 minutes from zero to a passing simulated run, no harness rewrite (see `simwork init` below):

```bash
pip install git+https://github.com/SRogDev/SimWork
simwork --help
simwork init my-app
cd my-app && pytest
```

Or work from a checkout:

```bash
uv sync
uv run simwork --help
uv run pytest
```

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) (uv only for the checkout path; `pip install` works on its own).

## `simwork init` — the starter

Scaffold a working starter in a directory (your project dir, or a fresh one):

```bash
simwork init my-app        # creates my-app/; defaults to the current directory
cd my-app
simwork serve --scenario scenarios/ticket-status.yaml   # fake OpenAI server
pytest                                                 # the eval suite passes
simwork eval --trace evals/ticket-status-trace.json    # the same gate, directly
```

It generates `simwork.yaml` (config: simulate mode, scenario + eval paths), `scenarios/ticket-status.yaml` (scripted LLM turns), `evals/ticket-status-trace.json` (the recorded trace of that run) and `tests/test_simwork_eval.py` (a pytest file that gates the trace on tool correctness + task completion), plus a starter README and the pre-made AI configuration prompt (`prompts/configure-simwork.md` — see below). The scenario parses and the trace passes the $0 gate before anything is written, so `init` can never scaffold a broken starter. Existing files owned by `init` are only overwritten with `--force`; other files in the directory — your harness — are never touched.

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

## Configuration file (`simwork.yaml`)

`simwork init` writes a `simwork.yaml` starter config, and `simwork serve` / `simwork eval` read it — no flags needed inside the project. The file is discovered by walking up from the current directory (or pass `--config FILE`); relative paths resolve against the file's own directory.

```yaml
mode: simulate                          # simulate or live (default live)
scenario: scenarios/ticket-status.yaml  # required in simulate mode
seed: 7                                 # optional run seed
host: 127.0.0.1                         # fake-server bind host
port: 0                                 # fake-server bind port (0 = ephemeral)
eval:
  trace: evals/ticket-status-trace.json # default trace for `simwork eval`
  report: evals/report.json             # default report path for `simwork eval`
```

Precedence: **CLI flags > environment variables > config file > defaults**. So `simwork serve --port 8123` beats `SIMWORK_PORT`, which beats `port:` in the file. Loading is strict: an unknown key, a bad mode, or a malformed file fails closed with a visible error instead of running with wrong settings.

```bash
# Inside a project with simwork.yaml — no flags needed:
simwork serve    # serves the scenario from the file
simwork eval     # evaluates eval.trace, writes eval.report
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

### Scenario families

A thousand runs of one scenario are still one situation. A family is one YAML file that generates many scenarios: named parameters with value lists, `{{param}}` placeholders in the turns (and in the optional `expected:` block), and a base seed. Member `i` gets seed `base + i` and its parameter values from a PRNG seeded with that member seed — the same family + index always yields the same scenario. A whole-string `{{param}}` keeps the value's type (an int stays an int in tool arguments); inside a longer string the value is interpolated as text. Without an `expected:` block it is derived from the member's own turns. Loading is strict: an undeclared placeholder or a bad schema fails closed with `FamilyError`.

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

```bash
simwork serve --family examples/ticket-status-family.yaml --member 2  # serve one member
simwork scale --family examples/ticket-status-family.yaml --runs 100   # one member per run
```

```python
from simwork.families import load_family

family = load_family("family.yaml")
member = family.member(0)  # deterministic: seed 7, parameters picked from the lists
llm = member.scenario.to_llm()
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

A trace is a JSON object with `steps` (assistant turns, with `content` and/or `tool_calls`, plus `tool_result` steps) and `expected` (`tool_calls` the run should have made, `final_answer_contains` facts the final answer should cover). Loading is strict: a bad trace fails closed instead of producing a wrong report. The report carries a `trace_hash` (SHA-256 of the canonical trace JSON), so the same seed + same scenario run twice produces an identical report. DeepEval's own metric classes were verified but are not a dependency of the $0 path — its `ToolCorrectnessMetric` demands an `OPENAI_API_KEY` at construction, which would break the $0 default (see `docs/deepeval-wiring-2026-11-17.md`).

### Opt-in DeepEval judge (`simwork eval --judge`)

The judge path wires DeepEval's own classes (`simwork.deepeval_judge`), off by default. It needs the optional dependency plus a key, and the task-completion judge makes a real, billable model call — the tool-correctness judge metric is deterministic and makes no call:

```bash
uv pip install 'simwork[deepeval]'
export OPENAI_API_KEY=sk-...          # real key: the judge spends real money
simwork eval --trace trace.json --judge
simwork eval --trace trace.json --judge --judge-model gpt-4o-mini --judge-max-calls 1
# ... judge_tool_correctness: 1.00 (threshold 0.50) PASS — ...
# ... judge_task_completion: 1.00 (threshold 0.50) PASS — ...
```

`--judge-max-calls` (default 1) is a per-run budget on real LLM calls: tool correctness costs 0, task completion costs 1, and a run whose judge work exceeds the budget fails closed before any call. `--judge-metrics tool_correctness` runs only the deterministic metric (a dummy key suffices for that one). The metrics come back in the order `--judge-metrics` lists them — an earlier build mislabelled the scores when the order differed (fixed 2026-11-18; both adapters now share one metric-name list in `simwork.eval`). Judge scores are LLM-generated, so a judged report is not reproducible run-to-run — the trace hash is unchanged, only the judge scores vary. In pytest, `trace_to_test_case` + `judge_metrics` let you call DeepEval's own `evaluate()` / `assert_test` directly (see `simwork.deepeval_judge`).

### Recording a trace from a simulated run

Traces need not be hand-written. A `TraceRecorder` captures one from a real simulated run: hand it to the scripted LLM (or the fake server / router) and it records every assistant completion; the harness records each tool result after executing the tool the LLM asked for. The recorded trace feeds straight into `simwork eval`:

```python
from simwork.llm import ScriptedLLM
from simwork.trace import TraceRecorder, completion_to_step

recorder = TraceRecorder(run_id="ticket-status-1", seed=7)
llm = ScriptedLLM(script, seed=7, recorder=recorder)
messages = [{"role": "user", "content": "What's the status of ticket T-123?"}]
for _ in range(len(script)):
    completion = llm.complete(messages)          # assistant step recorded
    for call in completion_to_step(completion).get("tool_calls", []):
        result = lookup_ticket(**call["arguments"])   # the harness executes the tool
        recorder.record_tool_result(call["name"], result)
        messages.append({"role": "tool", "content": json.dumps(result)})
recorder.save("trace.json", expected={...})      # eval-ready, validated
```

```bash
simwork eval --trace trace.json   # same report as for a hand-written trace
```

Recording is deterministic: the same seed + same scenario run twice produces an identical trace hash. A recorder holds one run — use a fresh recorder per run. Recording a malformed completion or a non-JSON tool result fails closed instead of producing a wrong trace.

## The $0 default

In simulate mode SimWork makes zero real calls to LLM providers and zero real calls to world APIs, and fails closed — it errors visibly instead of silently falling back to a real call if a mock is missing.

## Pre-made AI configuration prompt

You don't have to hand-write the setup: `prompts/configure-simwork.md` is a prompt file you hand to an AI assistant (paste it into a chat, or point the assistant at the file, together with your harness code) and it configures SimWork for your app — inspecting the harness, routing LLM calls to the fake server and world APIs to the mocks, writing the scenarios, recording a trace, and gating the run. `simwork init` copies the same prompt into every starter as `prompts/configure-simwork.md`, so it travels with your project.

The prompt teaches the hard gates ($0 by default, no harness rewrite, fail closed, no secrets), the six-step workflow (inspect → route LLM → write scenario → route APIs → record + gate → verify $0 and determinism), scale for thousands of runs (parameterised scenario families, one report per run), and realism (scenario fidelity grounded in real behaviour, small-sample calibration opt-in, failure modes in scenarios) — plus a done checklist and an honest statement of what simulation does *not* prove. The single source of truth is `simwork.prompt.CONFIGURE_SIMWORK_PROMPT`; the repo file and the generated copy are guarded against drift by `tests/test_prompt.py`.

## Roadmap (v0.1)

| Phase | What | Status |
|---|---|---|
| 0 | Repo foundation: package, CLI, licence, CI | ✅ Done |
| 1 | LLM mock (OpenAI-compatible, scripted + deterministic) + routing | ✅ Done — Tenro evaluated, not adopted (see `docs/tenro-evaluation-2026-11-16.md`); scripted LLM + fake server + YAML scenarios + routing (`SIMWORK_MODE` / `simwork serve`) landed |
| 2 | API mock via Prism + APIs.guru, with a stateful stub layer | ✅ Done — `simwork mock --api` (fetch from APIs.guru + Prism serve) and `--stateful` (create-then-read via a proxy in front of Prism, `simwork.stateful`) landed |
| 3 | DeepEval harness + pass/fail report | ✅ Done — `simwork eval` over a recorded trace (tool correctness + task completion, deterministic, $0); trace capture done — `TraceRecorder` records a trace from a real simulated run, feeding straight into `simwork eval`; opt-in DeepEval judge wired — `simwork eval --judge` runs the library's own metrics (`simwork[deepeval]`, budgeted, off by default) |
## LangGraph demo (`simwork demo`)

The end-to-end proof: a small LangGraph agent app that asks about ticket `T-123`, calls one LLM and one world API, and gates the run — all simulated, $0.

```bash
uv sync --group demo   # langgraph + langchain-openai + httpx (demo only)
npm i -g @stoplight/prism-cli   # the API-mock engine (Node 18+)
simwork demo           # prints the eval report + trace hash, exits 0 on PASS
simwork demo --trace evals/demo-trace.json --report evals/demo-report.json
```

The agent (`simwork.demo.build_graph`) is a `ChatOpenAI` pointed at the fake OpenAI server by base-URL swap, with one tool bound: `lookup_ticket` calls `GET /tickets/{id}` on a Prism mock of a tiny ticket API spec bundled with the demo. The scripted LLM calls the tool first, then answers from the result; the run is recorded as a trace (`simwork.demo.messages_to_trace`) and gated on tool correctness + task completion. Same seed + same scenario run twice produces the same trace hash — a test (`tests/test_demo.py`) also guards that the demo opens no non-localhost connection, so no real LLM or world-API call can slip through.

## Scale smoke test (`simwork scale`)

The spec's §7 scale criterion — thousands of simulated runs at $0, one deterministic report per run — as a command:

```bash
simwork scale                 # 1000 runs (default), shared mocks, one report
simwork scale --runs 100       # a smaller batch
simwork scale --report evals/scale-report.json
# SimWork scale report — 1000 runs in 42.6s (23.5 runs/s)
#   passed: 1000/1000
#   distinct trace hashes: 1 (f7af385c722c…)
# Overall: PASS

# One member per run instead of one repeated scenario:
simwork scale --family examples/ticket-status-family.yaml --runs 100
# SimWork scale report — 100 runs in 4.5s (22.0 runs/s)
#   passed: 100/100
#   family: ticket-status-family — one member per run, distinct hashes expected
#   distinct trace hashes: 100
# Overall: PASS
```

The batch starts both mocks once (fake OpenAI server + Prism ticket mock, via `simwork.demo.demo_servers`), builds the graph once, and repeats the demo run — resetting the scripted LLM between runs so every run replays the same scenario from the first turn. The batch passes only when every run passes the $0 gate *and* every run produces the same trace hash; a run that raises is recorded as a failed run with its error instead of aborting the batch. The machine-readable report (`--report`) carries one per-run result each (index, trace hash, verdict). Verified live 2026-11-19: 1000/1000 passed, one hash, 42.6s, $0 — the Polygrow pre-launch use case is demonstrably feasible.

With `--family FILE`, run `i` uses family member `i-1` instead: the scripted LLM's script is swapped per run (same server, same graph), so the batch covers different situations — different ticket ids, different outcomes, different failure modes — and the verdict only requires every run to pass the gate; the trace hashes are expected to differ. Repeat runs are deterministic: the same family + run count produces the same set of trace hashes. Verified live 2026-11-20: 10/10 passed with 10 distinct hashes, and a repeat 5-run batch produced the identical hash set.

## Polygrow pilot (`simwork pilot`)

The first real harness simulated with SimWork — not the toy demo: one real Polygrow flow, a Mind chat turn (`POST /api/v1/chat` → the `ai_mind` LangGraph graph) for a general-chat message, run end-to-end in simulate mode.

```bash
simwork pilot            # prints the eval report, trace hash + the finding
simwork pilot --trace evals/pilot-trace.json --report evals/pilot-report.json
# SimWork eval report — run: polygrow-pilot-mind-chat-1 (seed 7)
# trace: 2f05d6cc3ad4842c…
#   tool_correctness: 1.00 (threshold 1.00) PASS — no tool calls expected and none made
#   task_completion: 1.00 (threshold 1.00) PASS — final answer contains all expected facts
# Overall: PASS
# Pilot: intent general_chat (confidence 0.85) → route response_formatter
# Finding: The real Mind graph returns 'No response generated.' for a confident
# general_chat turn ...
```

The pilot (`simwork.pilot`) mirrors the real graph's node sequence from the Polygrow checkout (`main` @ `7655a65`): `entry → context_gatherer → intent_router → response_formatter → memory_write`, with the route decided by the real `route_after_intent` (confidence threshold 0.6) and the intent-classification prompt verbatim from `nodes.py` (verified byte-identical). The LLM call goes to the scripted fake OpenAI server; the business context comes from a Prism mock; the memory write goes to the stateful stub and is read back. A small calibration sample (`examples/polygrow-pilot/calibration.yaml`) carries real user messages with the intent the real Mind code assigns them, each with its source rule. Verified live 2026-11-20: two runs produce the identical trace hash (`2f05d6cc…`), gate PASS, $0.

The honest finding: for a confident `general_chat` turn the real graph returns "No response generated." — the router sends it straight to `response_formatter`, and no node before it sets `ai_response`. The pilot reproduces this faithfully and the gate passes on it: the simulation surfaces a real gap before launch instead of pretending the chat works. Known limits (see `examples/polygrow-pilot/README.md`): the pilot is a faithful replica of the flow, not the live `ai-services` import, and it covers only the general-chat flow so far.

## Recipes — runnable examples

Short, copyable patterns under `examples/recipes/`, each following the `simwork init` starter layout (config + scenario + recorded trace + pytest suite) plus a `run.py` that runs the pattern live against both mocks:

- **RAG assistant** (`examples/recipes/rag-assistant/`) — the assistant answers by first calling a `retrieve_docs` tool against a Prism mock of a docs-search API, then answering grounded in the retrieved doc; the recipe's test asserts the final answer repeats a phrase from the doc. Raw-HTTP agent loop, no LangGraph — the plain-OpenAI-client pattern.
- **API-backed agent** (`examples/recipes/api-backed-agent/`) — the assistant answers a currency question by calling a `get_exchange_rates` tool, a thin wrapper over one endpoint of the ExchangeRate-API spec fetched from the APIs.guru catalog, then computing the answer from the structured rates (100 USD × 0.92 = 92 EUR). The recipe's test asserts the amounts in the answer equal 100 USD times the rates the tool returned. Raw-HTTP agent loop, no LangGraph.
- **Multi-tool agent** — next recipe.

```bash
cd examples/recipes/rag-assistant
python run.py    # live run: both mocks, gate printed, exits 0 on PASS
pytest           # the recipe's eval suite passes
```

See the [recipes guide](https://simwork.vercel.app/guides/recipes/) for the walkthrough.

| 4 | `simwork init` + pre-made AI configuration prompt + LangGraph demo end-to-end | ✅ Done — `simwork init` scaffolding landed (config + scenario + eval suite); pre-made prompt landed (`prompts/configure-simwork.md`, also generated by `init`); LangGraph demo landed (`simwork demo`: one LLM call + one Prism-mocked world-API call, trace recorded, $0 gate passes, deterministic trace hash); scale smoke test landed (`simwork scale`: 1000/1000 demo runs passed, one trace hash, 42.6s, $0) |

Out of scope for v0.1: a managed/hosted service (not designed before 7 days after start), a Rust rewrite, TypeScript harness support, a real LLM judge by default.

## §7 acceptance check-off (verified 2026-11-19)

- **Install:** `pip install .` in a fresh venv and `pip install git+https://github.com/SRogDev/SimWork` both install; `simwork --help` / `--version` work (0.1.0). PyPI publication is NOT done — `pip install simwork` from PyPI does not resolve yet; that is a release decision for Roger.
- **`simwork init`:** in a fresh directory it scaffolds a working starter (config + scenario + trace + pytest suite + README + prompt); the generated suite passes (`1 passed`) and `simwork eval` on the generated trace exits 0.
- **Demo end-to-end, $0:** `simwork demo` runs the LangGraph agent against both mocks and passes the $0 gate; a test guards that it opens no non-localhost connection (`tests/test_demo.py::test_demo_makes_no_real_network_calls`).
- **Determinism:** two live demo runs produce the identical trace hash (`f7af385c…`); the same trace twice gives an identical eval report; `simwork scale` repeats it 1000 times with one hash.
- **`simwork eval`:** exits 1 with a FAIL report on a failing trace (verified live), 0 on pass; `--report` writes the machine-readable report.
- **`simwork mock --api`:** verified live — `simwork mock --api httpbin.org` fetched the spec from APIs.guru and Prism served it (`GET /get` → 200). The demo's world API is served the same way (bundled ticket spec via Prism).
- **Stateful stub:** create-then-read returns the created record (tests in `tests/test_stateful.py`).
- **pytest green:** 316 passed, 2 skipped (deepeval not installed, by design), `ruff check` clean — verified locally 2026-11-21 (307 passed on 2026-11-20 after the RAG recipe; this run adds 9 API-backed-agent tests). CI was red on three pushes: first an ordering bug in `demo_servers()` (the prism check ran before the demo-deps check, masking the install hint in environments with neither), then two missing-prism tests that were not isolated from the demo deps; both fixed 2026-11-19 — **CI green on `a16c071`**.
- **README:** documents the under-15-minute setup, the pre-made prompt, and the $0 default (see Quickstart, Pre-made AI configuration prompt, The $0 default).
- **No merge without confirmation:** there are no PR merges at all — landings are direct pushes to `main` under the SimWork-only autonomy order (Roger 2026-11-15), one small task per run, each reported in the factory chat for correction.
- **Scale:** `simwork scale` 1000/1000 passed, one trace hash, 42.6s, $0 (verified live 2026-11-19).

## Contributing

SimWork is open source (MIT) and contributions are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md) for the setup, the checks
(`uv run ruff check .`, `uv run pytest`), and the rules that matter
most: the spec is the constitution, $0 by default, no secrets,
determinism, and one small change per PR with a README touch-up.
Issues labelled `good first issue` are the best place to start.

## Adoption roadmap (post-v0.1)

v0.1 is done. The next job is adoption — making SimWork known and used
(target: 1,000 GitHub stars, as open source, not commercialisation):

| Step | What | Status |
|---|---|---|
| 1 | Docs site live (Astro + Starlight, `docs-site/`, Vercel) | ⏳ Blocked — Vercel connection not authorized for the team; needs the maintainer to grant access |
| 2 | Real examples — 2–3 runnable recipes via `simwork init` (RAG assistant, API-backed agent, multi-tool agent) | 🔶 In progress — 2 of 3: RAG assistant recipe done (`examples/recipes/rag-assistant/`, 9 tests); API-backed agent recipe done (`examples/recipes/api-backed-agent/`, 9 tests); multi-tool agent to come |
| 3 | Launch posts (X, Reddit, Hacker News "Show HN") — drafted for the maintainer to post | ⬜ Not started |
| 4 | Community surface — `good first issue` labels, CONTRIBUTING.md, roadmap in README | ✅ Done — this change |
| 5 | Measure — stars + clones + docs visits, reported monthly | ⬜ Not started |

Readiness for Polygrow (the first real user): 3 of 4 criteria pass —
`simwork.yaml` loader, scenario families, and the Polygrow pilot are
all done and verified live. The docs site going live is the last gate;
until then the honest answer is: not yet.

## Licence

MIT — see [LICENSE](LICENSE).
