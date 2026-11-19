---
title: Routing & simulate mode
description: How SimWork decides where AI calls go — configuration only, no harness rewrite.
---

Routing decides where AI calls go. In simulate mode every AI call routes to the mock LLM server; in live mode SimWork does nothing and the harness talks to its real provider. Anything misconfigured fails closed instead of silently falling back to a real call.

## Serve the mock

```bash
# Serve the mock from a scenario file (prints the env vars to point at it)
simwork serve --scenario scenario.yaml --port 8123
# OPENAI_BASE_URL=http://127.0.0.1:8123/v1
# OPENAI_API_KEY=simwork-simulated
```

`simwork serve` starts the scripted, deterministic fake OpenAI server from a YAML scenario file and runs until Ctrl-C. See [Scenario files](/guides/scenarios/) for the format.

## Environment variables

| Variable | Meaning |
|---|---|
| `SIMWORK_MODE` | `simulate` or `live` (default `live` — simulate is explicit opt-in, so an unset variable never silently intercepts a harness) |
| `SIMWORK_SCENARIO` | Path to the YAML scenario file; required in simulate mode |
| `SIMWORK_HOST` | Bind host for the fake server (default `127.0.0.1`) |
| `SIMWORK_PORT` | Bind port (default `0` = ephemeral) |

Command-line flags override the variables: `simwork serve --scenario FILE --host HOST --port PORT`.

## From Python

The same routing is available as a context manager — the harness only needs a base-URL swap:

```python
import os
from simwork import SimWorkRouter

with SimWorkRouter.from_env() as router:  # reads SIMWORK_MODE / SIMWORK_SCENARIO
    os.environ.update(router.env_overrides)  # OPENAI_BASE_URL + dummy OPENAI_API_KEY
    run_harness()  # $0, no real LLM calls
```

## Fail closed

Simulate mode makes zero real calls to LLM providers, and fails closed — it errors visibly instead of silently falling back to a real call if a mock is missing or misconfigured. The default mode is `live` when `SIMWORK_MODE` is unset, so simulation is always an explicit opt-in, never silent interception.

Note: `simwork.yaml` exists as the starter config, but no config-file loader reads it yet — today routing works through flags and environment variables only.
