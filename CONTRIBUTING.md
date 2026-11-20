# Contributing to SimWork

Thanks for considering a contribution. SimWork is an open-source tool for
simulating AI apps before spending real LLM or world-API calls — every
simulated run costs $0 by default, and every change should keep it that
way.

## The rules that matter most

1. **The spec is the constitution.** `docs/spec-v0.1.md` is the design
   source of truth. Code that contradicts the spec is drift,
   not an improvement. If a change needs the spec to change, say so in
   the PR — don't silently rewrite behaviour.
2. **$0 by default.** Simulate mode makes zero real calls to LLM
   providers and zero real calls to world APIs, and fails closed
   (errors visibly) instead of silently falling back to a real call.
   A change that lets a real call slip through is a bug, however
   small.
3. **No secrets in the repo.** No real API keys in fixtures, scenarios,
   or docs — simulated credentials only.
4. **Determinism.** Same seed + same scenario = same trace and same
   eval report. Don't introduce wall-clock time, unseeded randomness,
   or dict-order dependence into a simulated run.
5. **Small changes, one at a time.** One logical change per PR, with
   tests. The factory lands in small batches at human pace; your PR
   should read the same way.
6. **Every significant change ships a README touch-up in the same PR.**
   READMEs are in English and kept current — a stale README is a bug.

## Development setup

SimWork is Python 3.11+, managed with `uv` only. Never `pip` +
`requirements.txt` as the source of truth.

```bash
git clone https://github.com/SRogDev/SimWork.git
cd SimWork
uv sync --group dev        # dev dependencies: pytest, ruff
uv sync --group demo       # demo only: langgraph + langchain-openai + httpx
npm i -g @stoplight/prism-cli   # the API-mock engine (Node 18+)
```

## Running the checks

```bash
uv run ruff check .        # lint — must be clean
uv run pytest              # full suite (demo tests skip without the demo group)
```

The demo and scale tests need both the demo group and Prism installed;
without them those tests skip by design, so CI stays green offline.
Before opening a PR, run the full suite with both installed if you can.

## How to contribute

- **Good first issues** are labelled `good first issue` on GitHub —
  small, well-scoped tasks such as a new scenario example, a docs
  fix, or a missing edge-case test. Pick one, comment that you're
  taking it, and open a PR.
- **Bigger ideas first as an issue.** A new mock type, a new eval
  metric, or a new command deserves a short issue describing the
  problem and the proposed shape before code — the spec may need to
  move with it.
- **Recipes welcome.** Short runnable examples (`simwork init`-based:
  a RAG assistant, an API-backed agent, a multi-tool agent) are one
  of the most useful contributions — see the adoption roadmap in the
  README.

## What a good PR looks like

- One logical change, with tests (`pytest`, following the existing
  test style — new behaviour gets a new test file or new tests in the
  matching file).
- `ruff check` clean; the full test suite green.
- README touched up in the same PR when behaviour or usage changed.
- The PR body says what changed, the test evidence (counts), and any
  decision you made that a maintainer could correct afterwards.
- No new dependency without a reason in the PR body — SimWork stays
  light on purpose.

## Where to look

- `README.md` — the 15-minute setup, the $0 default, the roadmap.
- `docs/` — design notes (Tenro evaluation, decisions).
- `docs-site/` — the docs site (Astro + Starlight), deployed to
  Vercel; content mirrors the README and `docs/`.
- `examples/` — runnable scenarios, scenario families, and the
  Polygrow pilot.
- `prompts/configure-simwork.md` — the pre-made prompt an AI
  assistant follows to configure SimWork for a new app.

## Code of conduct

Be kind and concrete. Disagree with the idea, not the person, and
back claims with evidence — a test, a trace, or a number. That's how
this project works.
