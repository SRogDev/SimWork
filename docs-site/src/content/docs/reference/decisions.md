---
title: Design decisions
description: Why SimWork is built the way it is — Tenro, DeepEval, Prism — and the honest limits.
---

## Why not Tenro?

Tenro 0.2.3 (Apache 2.0) was evaluated in Phase 1 and deliberately **not** adopted as the LLM-interception layer. The full record is in [`docs/tenro-evaluation-2026-11-16.md`](https://github.com/SRogDev/SimWork/blob/main/docs/tenro-evaluation-2026-11-16.md).

1. **It requires editing the harness.** Simulation only activates inside functions decorated with `@link_llm` / `@link_tool` / `@link_agent`. That contradicts the spec's MUST: routing happens by configuration (base-URL swap), "not by editing app logic".
2. **It is test-scoped, not a runnable server.** Simulation lives inside a pytest `Construct`; there is no endpoint an unmodified harness can point at with a base-URL swap.
3. **It cannot see a base-URL swap.** Interception is keyed to provider base URLs, so a client pointed at a local fake server is invisible to it — verified empirically: an undecorated raw OpenAI client inside a `Construct` was not intercepted, and neither was a `@link_llm`-decorated call to a local base URL.
4. **Early-stage dependency risk.** The API was still stabilising and pull requests were not being accepted (PyPI, 2026-11-16).

What was built instead: SimWork's own OpenAI-compatible fake server (`ScriptedLLM` + `FakeOpenAIServer`) — scripted, deterministic, and runnable, so any OpenAI-compatible client works unchanged.

## Why the $0 gate computes metrics natively

DeepEval 4.3.4 was verified before any wiring (full record in [`docs/deepeval-wiring-2026-11-17.md`](https://github.com/SRogDev/SimWork/blob/main/docs/deepeval-wiring-2026-11-17.md)):

- `ToolCorrectnessMetric` is deterministic and works offline — but its constructor demands an `OPENAI_API_KEY`, even though the metric itself never calls a model. Requiring a key for a $0 gate would be a footgun that contradicts the $0 default and the no-secrets rule.
- `TaskCompletionMetric` is an LLM judge (G-Eval style) — it needs a real model call, so it cannot be part of the $0 default gate.

So the v0.1 gate computes tool correctness and task completion natively in `simwork/eval.py`, with the same names and semantics as DeepEval's metrics, and `simwork eval` reads a recorded trace and prints a pass/fail report. No `deepeval` dependency in the $0 path, no API key anywhere.

The opt-in judge path (`simwork eval --judge`) wires DeepEval's own classes — off by default, budgeted per run (`--judge-max-calls`), via the optional `simwork[deepeval]` dependency.

## Why Prism needs a state layer

Prism (Stoplight, Apache 2.0) mocks an API's *shape* from its OpenAPI spec, but it is stateless: a `POST` followed by a `GET` does not return the created record. SimWork adds a small stateful proxy in front of Prism (`simwork.stateful`) that remembers JSON writes per collection path, so create-then-read works in tests. State is in-memory per process — restarting the mock resets the world, which keeps runs deterministic.

## Honest limits

- Scripted mocks verify logic and behaviour, not real reasoning quality. A passing gate never proves the real model would behave the same way.
- Prism mocks shape, not real behaviour — no auth, no rate limits, no business logic — and catalog specs can be outdated.
- `simwork mock` serves APIs from the APIs.guru catalog by name only; there is no `--spec` flag yet for a user's own OpenAPI file.
- Scenario families (parameterised, seeded variations for a thousand *different* runs) are the next step for the scale story; today `simwork scale` repeats one scenario deterministically.
