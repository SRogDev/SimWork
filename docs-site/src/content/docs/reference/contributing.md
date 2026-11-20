---
title: 'Contributing'
description: How to contribute to SimWork — setup, checks, small PRs, and good first issues.
---

SimWork is open source (MIT) and contributions are welcome — especially
small, well-scoped ones. The full guide lives in
[CONTRIBUTING.md](https://github.com/SRogDev/SimWork/blob/main/CONTRIBUTING.md)
at the repo root; this page is the short version.

## The rules that matter most

- **The spec is the constitution** (`docs/spec-v0.1.md`). Code that
  contradicts it is drift, not an improvement.
- **$0 by default.** Simulate mode makes zero real calls to LLM
  providers or world APIs, and fails closed instead of silently
  falling back to a real call.
- **No secrets in the repo** — simulated credentials only.
- **Determinism.** Same seed + same scenario = same trace and same
  eval report.
- **Small changes, one at a time.** One logical change per PR, with
  tests — and a README touch-up in the same PR when behaviour or
  usage changed.

## Setup and checks

```bash
uv sync --group dev        # pytest, ruff
uv sync --group demo       # demo only: langgraph + langchain-openai + httpx
npm i -g @stoplight/prism-cli   # the API-mock engine (Node 18+)

uv run ruff check .        # lint — must be clean
uv run pytest              # full suite
```

## Where to start

Issues labelled `good first issue` are small, well-scoped tasks — a new
scenario example, a docs fix, a missing edge-case test. Bigger ideas
(a new mock type, a new eval metric, a new command) start as an issue
first, so the design can be discussed before code. Runnable recipes
(`simwork init`-based: a RAG assistant, an API-backed agent, a
multi-tool agent) are among the most useful contributions.
