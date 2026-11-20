---
title: CLI reference
description: Every SimWork command and flag — serve, mock, eval, init, demo, scale.
---

SimWork 0.1.0. Top level:

```text
usage: simwork [-h] [--version] {serve,mock,eval,init,demo,scale} ...

SimWork — simulate AI-app functionality first, before spending real LLM or
world API calls. Every simulated run costs $0 by default.
```

## `simwork serve`

Serve the fake OpenAI server from a scenario file (simulate mode).

```text
usage: simwork serve [-h] [--scenario FILE] [--family FILE] [--member N]
                     [--config FILE] [--host HOST] [--port PORT]

Start the scripted, deterministic fake OpenAI server from a YAML scenario file
and print the env vars a harness needs to point at it. Runs until Ctrl-C. $0 —
no real LLM calls.
```

| Flag | Meaning |
|---|---|
| `--scenario FILE` | YAML scenario file (overrides `SIMWORK_SCENARIO`) |
| `--family FILE` | YAML scenario family file: serve one member of it instead of a plain scenario (mutually exclusive with `--scenario`) |
| `--member N` | Family member to serve (default `0`; needs `--family`) |
| `--config FILE` | `simwork.yaml` config file (default: auto-discovered from the current directory up) |
| `--host HOST` | Bind host (overrides `SIMWORK_HOST`, default `127.0.0.1`) |
| `--port PORT` | Bind port (overrides `SIMWORK_PORT`, default `0` = ephemeral) |

See [Routing & simulate mode](/guides/routing/).

## `simwork mock`

Serve a Prism mock for an API from the APIs.guru catalog.

```text
usage: simwork mock [-h] --api NAME [--host HOST] [--port PORT]
                    [--cache-dir CACHE_DIR] [--stateful]

Fetch an API's OpenAPI spec from APIs.guru (cached under ~/.cache/simwork) and
serve it as a mock with Prism, so a harness can call the API without touching
the real one. Runs until Ctrl-C. $0 — no real world-API calls.
```

| Flag | Meaning |
|---|---|
| `--api NAME` | APIs.guru API name, e.g. `github.com` (its preferred version is used) |
| `--host HOST` | Bind host (default `127.0.0.1`) |
| `--port PORT` | Bind port (default `0` = ephemeral) |
| `--cache-dir CACHE_DIR` | Cache directory for the catalog + specs (default `~/.cache/simwork`) |
| `--stateful` | Add the stateful stub layer in front of Prism: writes are remembered, so create-then-read returns the created record |

See [API mocks](/guides/api-mocks/).

## `simwork eval`

Evaluate a recorded run trace (DeepEval harness).

```text
usage: simwork eval [-h] [--trace FILE] [--config FILE] [--report FILE]
                    [--judge] [--judge-model MODEL] [--judge-max-calls N]
                    [--judge-metrics NAMES]

Evaluate a recorded run trace (JSON, see examples/) with the deterministic
metrics tool correctness + task completion and print a pass/fail report. Exits
0 when the gate passes, 1 when it fails. $0 — no LLM judge, no network. With
--judge, also run DeepEval's own metric classes (opt-in: needs deepeval
installed and OPENAI_API_KEY; the task-completion judge makes a real, billable
model call).
```

| Flag | Meaning |
|---|---|
| `--trace FILE` | JSON trace file of a recorded run (default: `eval.trace` from `simwork.yaml`) |
| `--config FILE` | `simwork.yaml` config file (default: auto-discovered from the current directory up) |
| `--report FILE` | Also write the machine-readable JSON report to this file |
| `--judge` | Also run DeepEval's own judge metrics (opt-in, costs real LLM calls for task completion; needs `simwork[deepeval]` + `OPENAI_API_KEY`) |
| `--judge-model MODEL` | Model for the DeepEval judge (default: DeepEval's default) |
| `--judge-max-calls N` | Max real LLM calls the judge may make (default 1) |
| `--judge-metrics NAMES` | Comma-separated judge metrics to run (default: `tool_correctness,task_completion`) |

See [Evals & the $0 gate](/guides/evals/).

## `simwork init`

Scaffold a working SimWork starter in a directory.

```text
usage: simwork init [-h] [--force] [directory]

Generate a working starter in a directory: simwork.yaml config, a YAML
scenario for the scripted LLM, and an eval suite (a recorded trace + a pytest
file that gates on it), plus a starter README and the pre-made AI
configuration prompt (prompts/configure-simwork.md). The generated scenario
parses and the trace passes the $0 eval gate before anything is written.
Existing files owned by init are only overwritten with --force; other files in
the directory are never touched.
```

| Argument / flag | Meaning |
|---|---|
| `directory` | Target directory (default: current directory; created if missing) |
| `--force` | Overwrite files owned by `init` if they already exist |

See [Getting Started](/getting-started/).

## `simwork demo`

Run the LangGraph demo end-to-end (simulate mode).

```text
usage: simwork demo [-h] [--trace FILE] [--report FILE]

Run the LangGraph demo agent end-to-end in simulate mode: one LLM call to the
scripted fake OpenAI server, one world-API call to a Prism mock of the bundled
ticket API, then the $0 eval gate on the recorded trace. Prints the pass/fail
report and the trace hash; exits 0 when the gate passes, 1 when it fails.
Needs the demo dependencies (`uv sync --group demo`) and the `prism` binary.
$0 — no real LLM or world-API calls.
```

| Flag | Meaning |
|---|---|
| `--trace FILE` | Also write the recorded trace as JSON to this file |
| `--report FILE` | Also write the machine-readable JSON report to this file |

## `simwork scale`

Repeat the LangGraph demo N times and check every run is identical and passes.

```text
usage: simwork scale [-h] [--runs N] [--family FILE] [--report FILE]

Repeat the LangGraph demo N times (default 1000) against the same already-
running mocks — one fake OpenAI server + one Prism mock, the graph built once
— and check every run passes the $0 gate with the same trace hash. With
--family, run i uses family member i-1 instead, so the batch covers different
situations and the verdict only requires every run to pass. This is the spec's
scale smoke test (§7): thousands of simulated runs at $0 before launch, one
deterministic per-run result each. Prints a summary; exits 0 when every run
passed (and all hashes are identical, in single-scenario mode), 1 otherwise.
Needs the demo dependencies (`uv sync --group demo`) and the `prism` binary.
$0 — no real LLM or world-API calls.
```

| Flag | Meaning |
|---|---|
| `--runs N` | Number of runs (default 1000) |
| `--family FILE` | YAML scenario family file: run `i` uses family member `i-1`, so the batch covers different situations instead of one repeated scenario (the verdict then only requires every run to pass the gate) |
| `--report FILE` | Also write the machine-readable JSON report to this file |

See [Scale: 1,000 runs](/guides/scale/).
