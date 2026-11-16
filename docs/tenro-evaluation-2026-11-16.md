# Tenro evaluation — Phase 1, task 1 (2026-11-16)

## Question (spec §9, OPEN)

Adopt Tenro as SimWork's LLM-interception layer, or build SimWork's own
fake OpenAI server from the start? Under the SimWork autonomy order
(Roger 2026-11-15) the factory decides this in Phase 1 and implements it.

## What was checked

- **Tenro 0.2.3** (Apache 2.0, Python 3.11+), installed 2026-11-16 in a
  scratch venv with the `openai` client. PyPI docs read the same day.
- Tenro's documented quick start, step 1: decorate the harness with
  `@link_tool` / `@link_agent` / `@link_llm`, then simulate inside a
  `Construct` (pytest `construct` fixture or `with Construct() as c:`).
  LangGraph is listed as a supported framework.
- Two empirical experiments against a local recording HTTP server
  standing in for the real provider, with the OpenAI client pointed at
  it via `base_url` (the routing SimWork's spec requires):

  **A — undecorated raw OpenAI client call** inside a `Construct` with
  `simulate_llm(Provider.OPENAI, responses=["SIMULATED-REPLY"])`:
  the request reached the local server (1 hit) and returned the
  server's reply. Tenro did **not** intercept it.

  **B — `@link_llm`-decorated call** to the same local base URL:
  also **not** intercepted (1 hit on the local server), and Tenro then
  raised `TenroMissingLLMCallError` — it never observed an LLM HTTP
  request, because its interception registry matches provider base URLs
  (e.g. `https://api.openai.com`), not an arbitrary local base URL.

- A third experiment (decorated call at the default `api.openai.com`
  base URL, Tenro's documented path) was interrupted by a VM service
  restart and is inconclusive; it is not needed for the decision below.

## Decision: DO NOT adopt Tenro as the interception layer in v0.1

1. **It requires editing the harness.** Simulation only activates inside
   functions decorated with `@link_llm` / `@link_tool` / `@link_agent`.
   That contradicts the spec §4 MUST: routing happens by configuration
   (base-URL swap / provider override), "not by editing app logic".
2. **It is test-scoped, not a runnable server.** Simulation lives inside
   a pytest `Construct`; there is no endpoint an unmodified harness can
   point at with a base-URL swap.
3. **It cannot see a base-URL swap.** Interception is keyed to provider
   base URLs, so a client pointed at a local fake server is invisible
   to it (experiment B) — the exact routing SimWork is built on.
4. **Early-stage dependency risk.** The API is still stabilizing and
   pull requests are not being accepted (PyPI, 2026-11-16).

## What was built instead

SimWork's own OpenAI-compatible fake server — the layer the spec
already describes (§4 MUST: `/v1/chat/completions`, including tool
calling; scripted + deterministic; fails closed):

- `simwork.llm.ScriptedLLM` — replays a script of turns in order;
  same seed + same script = same responses; raises
  `ScriptExhaustedError` when the script runs out.
- `simwork.llm.FakeOpenAIServer` — stdlib-only HTTP server exposing
  `POST /v1/chat/completions` with OpenAI-shaped JSON (incl.
  `tool_calls`); unknown paths 404, exhausted script is a visible 500.
- Tests: `tests/test_llm_scripted.py` (10 tests, incl. determinism,
  tool-call shape, fail-closed, and live-server checks via stdlib
  `urllib`). No new dependencies.

## Future

Tenro stays a documented optional alternative for pytest-native users
who are willing to decorate their harness; revisit in v0.2+ if Tenro
adds transport-level interception that works without decorators and
with arbitrary base URLs. Nothing in this decision blocks Phase 2
(API mocks) or Phase 3 (DeepEval harness).
