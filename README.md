# SimWork

Simulate AI-app functionality first — before spending real LLM or world API calls — with evals on every run.

SimWork lets a Python developer add simulation to an existing app or harness with minimal setup: every AI call routes to an LLM mock and every API call routes to an API mock. A full simulated run costs **$0 by default**, with zero real network calls to LLM providers or real world APIs.

> **Status: Phase 0 — repo foundation (v0.1.0).** The package skeleton, CLI entry point, MIT licence and CI are in place. The LLM mock (Phase 1), API mock (Phase 2), DeepEval harness (Phase 3) and `simwork init` + demo (Phase 4) are not built yet. See `docs/` for the spec.

## Quickstart

```bash
uv sync
uv run simwork --help
uv run pytest
```

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

## The $0 default

In simulate mode SimWork makes zero real calls to LLM providers and zero real calls to world APIs, and fails closed — it errors visibly instead of silently falling back to a real call if a mock is missing.

## Roadmap (v0.1)

| Phase | What | Status |
|---|---|---|
| 0 | Repo foundation: package, CLI, licence, CI | ✅ Done |
| 1 | LLM mock (OpenAI-compatible, scripted + deterministic) + routing | Planned |
| 2 | API mock via Prism + APIs.guru, with a stateful stub layer | Planned |
| 3 | DeepEval harness + pass/fail report | Planned |
| 4 | `simwork init` + pre-made AI configuration prompt + LangGraph demo end-to-end | Planned |

Out of scope for v0.1: a managed/hosted service (not designed before 7 days after start), a Rust rewrite, TypeScript harness support, a real LLM judge by default.

## Licence

MIT — see [LICENSE](LICENSE).
