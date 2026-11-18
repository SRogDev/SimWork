# Configure SimWork for this app

You are configuring **SimWork** for an existing Python AI app (or
harness) so it can be simulated before spending real LLM or world API
calls. Follow this prompt exactly. If a step below contradicts
something you think is a better idea, follow the step and say what
you would change afterwards — do not improvise silently.

## What SimWork is

SimWork routes every AI call to a scripted, deterministic LLM mock
and every world-API call to an API mock, then evaluates every run
with a pass/fail gate. A full simulated run costs **$0 by default**:
zero real calls to LLM providers, zero real calls to world APIs.

Three rules govern everything below — they are hard gates, never
negotiable:

1. **$0 by default.** No real LLM calls, no real world-API calls in
   simulate mode. An LLM judge (`simwork eval --judge`) is opt-in
   only, off by default, and budgeted per run.
2. **No rewrite of the harness.** Routing happens by configuration —
   environment variables and a base-URL swap — never by editing the
   app's logic.
3. **Fail closed.** If a mock is missing or misconfigured, error
   visibly. Never silently fall back to a real call, and never invent
   a key, a URL, or a result to make a step pass.

Also: no real API keys or secrets anywhere in scenarios, fixtures,
or config — simulated credentials only (`simwork-simulated` is the
dummy key in simulate mode). Do not design a managed/hosted service;
that is out of scope.

## What to read first

- The SimWork README (`README.md` in the SimWork repo, or the starter
  README in this project) — the commands and the routing table.
- `simwork.yaml` in this project, if it exists — the starter config.
- `scenarios/*.yaml` — the scripted LLM turns already written.
- `evals/*.json` — recorded run traces and what the gate expects.

Starting from scratch? Run `simwork init` first — it scaffolds
`simwork.yaml`, a starter scenario, an eval suite, and a copy of this
very prompt (`prompts/configure-simwork.md`) in the project
directory. Then follow the steps below, replacing the starter
scenario with one for your own app.

## The workflow

### Step 1 — Inspect the harness

Find every place the app calls an LLM and every place it calls a
world API. List them: file, line, client (OpenAI client, LangChain,
LangGraph, `httpx`/`requests` to a REST API, ...). Do not change any
of this code — you only need the list to know what to route.

### Step 2 — Route the LLM calls to the mock

Point the harness at the fake OpenAI server with a base-URL swap:

```bash
simwork serve --scenario scenarios/<your-scenario>.yaml --port 8123
# OPENAI_BASE_URL=http://127.0.0.1:8123/v1
# OPENAI_API_KEY=simwork-simulated
```

Or set the two env vars and let the router pick them up:

```bash
SIMWORK_MODE=simulate SIMWORK_SCENARIO=scenarios/<your-scenario>.yaml
```

Or from Python, with the context manager (reads the env vars, so
the harness only needs the base-URL swap):

```python
import os
from simwork import SimWorkRouter

with SimWorkRouter.from_env() as router:  # SIMWORK_MODE + SIMWORK_SCENARIO
    os.environ.update(router.env_overrides)
    run_harness()
```

Environment variables:

| Variable | Meaning |
|---|---|
| `SIMWORK_MODE` | `simulate` or `live` (default `live`; simulate is explicit opt-in) |
| `SIMWORK_SCENARIO` | Path to the YAML scenario file; required in simulate mode |
| `SIMWORK_HOST` / `SIMWORK_PORT` | Bind host/port for the fake server |

Verify the harness actually hits the mock: run it once and confirm
the fake server logs the request. If the harness ignores the
base URL, stop — do not patch the harness to force it; report the
exact call site instead.

### Step 3 — Write the scenario

A scenario is a YAML file that scripts what the mock LLM says, turn
by turn — no code needed. Loading is strict: a bad schema fails
closed instead of silently producing a wrong script.

```yaml
name: my-app-run
seed: 7
turns:
  - content: "I will check the ticket."
  - tool_calls:
      - name: lookup_ticket
        arguments: {ticket_id: "T-123"}
  - content: "Your replacement has shipped."
```

Rules:

- One scenario per behaviour you want to test. Script the tool
  calls the harness should make, in order, with the exact arguments
  you expect — the eval gate checks them.
- Keep `seed` fixed per scenario. Same seed + same scenario must
  produce the same trace, every time.
- Ground the turns in real behaviour: copy the shape of real LLM
  replies and real tool results from the app's own logs or docs.
  A scenario that could never happen in production tests nothing.

### Step 4 — Route the world APIs to the mock

For each API from Step 1 that is in the APIs.guru catalog:

```bash
simwork mock --api <name> --port 8124
# API_BASE_URL=http://127.0.0.1:8124
```

Add `--stateful` when the harness writes and then reads back
(`POST` a record, then `GET` it): Prism alone is stateless, so the
stateful stub layer remembers writes in memory per process.
Restarting the mock resets the world, which keeps runs
deterministic. Point the harness at `API_BASE_URL` the same way you
pointed it at the fake LLM server — configuration only, no code.

If an API is not in the catalog, write a small stateful stub for it
in the scenario instead of calling the real API. Never let a
simulated run touch the real API "just this once".

### Step 5 — Record a trace and gate it

Record the run with `simwork.trace.TraceRecorder` — assistant steps
from the scripted LLM, tool-result steps from the harness executing
the tools — and declare what the run should have done:

```json
{
  "run_id": "my-app-run-1",
  "seed": 7,
  "steps": [ "..." ],
  "expected": {
    "tool_calls": [{ "name": "lookup_ticket", "arguments": { "ticket_id": "T-123" } }],
    "final_answer_contains": ["shipped"]
  }
}
```

Then run the gate:

```bash
simwork eval --trace evals/my-app-run-1.json
# simwork eval --trace evals/my-app-run-1.json --report evals/report.json
```

The $0 gate checks two deterministic metrics, both with a default
threshold of 1.0: **tool correctness** (share of expected tool calls
matched exactly, name + arguments) and **task completion** (the
final answer contains the expected facts). Add the trace to the
pytest suite (`tests/test_simwork_eval.py`) so CI gates on it:

```python
from simwork import evaluate_run, load_trace

def test_my_app_run_passes():
    report = evaluate_run(load_trace("evals/my-app-run-1.json"))
    assert report.passed, report.to_text()
```

### Step 6 — Verify $0 and determinism

Before you call the configuration done:

1. Run the harness in simulate mode and confirm no real host is
   contacted (no LLM provider, no real world API). If you cannot
   prove it, the configuration is not done.
2. Run the same seed + same scenario twice and confirm the trace
   hash is identical (`simwork eval` prints it). If it differs,
   find the nondeterminism (unseeded RNG, wall-clock time, dict
   ordering) and fix it — do not loosen the gate.
3. Run `pytest` — the eval suite must pass, and the gate must fail
   when you deliberately break a scenario (change an expected tool
   argument and watch it go red, then revert).

## Scale: thousands of runs, not one

The first use case for SimWork is an app that needs thousands of
pre-launch simulated runs at $0 (for example, testing a whole
product before launch on a near-zero budget). Configure for that:

- **Scenario families, not copies.** Parameterise scenarios by seed
  and by a small set of named variations (different user inputs,
  different tool results, different failure modes) so a thousand
  runs are not a thousand copies of one hand-written scenario.
- **Cheap, deterministic, bulk-evaluable.** Runs start cheap, are
  deterministic per seed, and each produces its own report
  (trace hash + per-metric pass/fail + overall gate). Keep the
  per-run artefacts (scenario, trace, report) so a failing run can
  be replayed exactly.
- **Failures are data.** A run that fails the gate is a finding
  about the app, not a broken simulation — report which metric
  failed and on which scenario variation.

## Realism: as close to reality as $0 allows

Scripted mocks verify logic and behaviour, not real reasoning
quality — say that plainly, never claim a simulation proves the
real model would behave the same way. Maximise realism within the
$0 constraint:

- **Scenario fidelity first.** Base scenarios on real traces and
  real behaviour (real tool results, real error shapes, real
  latencies as scripted delays). The closer the script is to what
  production actually does, the more a passing gate means.
- **Small-sample calibration (opt-in).** Where the user approves,
  run a small real sample (a handful of real LLM calls) and compare
  its outcomes against the simulated ones; use the gap to fix the
  scenarios, not to adjust the gate. The judge path
  (`simwork eval --judge`) is the opt-in tool for this and stays
  off by default, budgeted per run.
- **Simulate failures too.** Timeouts, 500s, empty results, and
  malformed tool arguments belong in scenarios — an app that only
  passes on the happy path is not launch-ready.

## What NOT to do

- Do not rewrite harness logic to "make simulation easier".
- Do not set `SIMWORK_MODE=live` (or unset it) to work around a
  failing mock — fix the mock.
- Do not put real keys, tokens, or production URLs in any file you
  create. Simulated credentials only.
- Do not add a managed service, billing, auth, or multi-tenancy.
- Do not claim a simulated run proves real-world performance.
  Report the gate result, the scenario, and the seed — nothing more.

## Done checklist

- [ ] Every LLM call routes to the fake server; every world-API
      call routes to an API mock. Verified: no real host contacted.
- [ ] A scenario exists per behaviour under test, with a fixed seed.
- [ ] A recorded trace + eval suite gate the run
      (`pytest` green, `simwork eval` PASS).
- [ ] Same seed + same scenario run twice gives the same trace hash.
- [ ] The gate goes red when a scenario is deliberately broken.
- [ ] Scenario families cover the main variations (including at
      least one failure mode), not just the happy path.
- [ ] No secrets in any file created; no harness logic rewritten.

When all boxes are checked, report: which files you created or
changed, the exact commands to run the simulation and the gate, and
one honest sentence about what the simulation does *not* prove.
