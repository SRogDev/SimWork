# SimWork

Simulate AI-app functionality first — before spending real LLM or world API calls — with evals on every run.

SimWork lets a Python developer add simulation to an existing app or harness with minimal setup: every AI call routes to an LLM mock and every API call routes to an API mock. A full simulated run costs **$0 by default**, with zero real network calls to LLM providers or real world APIs.

> **Status: Phase 1 — LLM mock + routing complete (v0.1.0).** Tenro 0.2.3 was evaluated and **not** adopted as the interception layer (it requires decorating the harness, which contradicts the spec's no-rewrite rule — see `docs/tenro-evaluation-2026-11-16.md`). SimWork's own scripted, deterministic fake OpenAI server is in place (`simwork.llm`: `ScriptedLLM` + `FakeOpenAIServer`), scripted turns load from YAML scenario files (`simwork.llm.load_scenario`), and routing is wired: `SIMWORK_MODE=simulate` + a scenario file starts the mock server (`simwork serve` or `SimWorkRouter`), 48 tests. The API mock (Phase 2), DeepEval harness (Phase 3) and `simwork init` + demo (Phase 4) are not built yet. See `docs/` for the spec.

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

## The $0 default

In simulate mode SimWork makes zero real calls to LLM providers and zero real calls to world APIs, and fails closed — it errors visibly instead of silently falling back to a real call if a mock is missing.

## Roadmap (v0.1)

| Phase | What | Status |
|---|---|---|
| 0 | Repo foundation: package, CLI, licence, CI | ✅ Done |
| 1 | LLM mock (OpenAI-compatible, scripted + deterministic) + routing | ✅ Done — Tenro evaluated, not adopted (see `docs/tenro-evaluation-2026-11-16.md`); scripted LLM + fake server + YAML scenarios + routing (`SIMWORK_MODE` / `simwork serve`) landed |
| 2 | API mock via Prism + APIs.guru, with a stateful stub layer | Planned |
| 3 | DeepEval harness + pass/fail report | Planned |
| 4 | `simwork init` + pre-made AI configuration prompt + LangGraph demo end-to-end | Planned |

Out of scope for v0.1: a managed/hosted service (not designed before 7 days after start), a Rust rewrite, TypeScript harness support, a real LLM judge by default.

## Licence

MIT — see [LICENSE](LICENSE).
