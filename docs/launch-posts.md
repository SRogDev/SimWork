# Launch posts — SimWork v0.1

Drafts for the maintainer to post. **One launch, not a drip:** post all four
on the same day, in this order: Hacker News → X → Reddit.

## Posting notes

- **Links point to GitHub only** (`https://github.com/SRogDev/SimWork`).
  The docs site is not live yet — do not link `simwork.vercel.app` until
  the Vercel deploy is unblocked. Update these drafts when it goes live.
- **Install is from git, not PyPI.** `pip install simwork` does not resolve
  yet (publication is a release decision). Every draft says so honestly.
- **No invented numbers.** Every claim below is verified: 325 tests,
  `simwork scale` 1000/1000 passed with one trace hash in 42.6s at $0,
  CI green. Do not add stars, users, or traction figures that do not exist.
- **Honest limit, stated in each draft:** scripted mocks verify logic and
  behaviour, not real reasoning quality. SimWork tells you whether your
  app behaves correctly — not how smart a real model would be.
- X posts are each ≤ 280 characters (checked by `tests/test_launch_posts.py`).

---

## 1. X — thread (6 posts)

**Post 1:**
I built SimWork to test AI apps before spending a cent on real LLM or API calls. Every AI call goes to a scripted mock. Every API call goes to a mock. Every run gets a DeepEval pass/fail gate. $0 by default. 🧵

**Post 2:**
The problem: testing an AI app means paying for every LLM call and every world API call. 1,000 pre-launch runs = a real bill — or you ship untested. SimWork makes those 1,000 runs cost $0.

**Post 3:**
How it works: a scripted, deterministic fake OpenAI server (/v1/chat/completions, tool calling included) plus Prism mocks of real APIs from the APIs.guru catalog — with a stateful layer, so create-then-read works.

**Post 4:**
Setup: pip install git+https://github.com/SRogDev/SimWork, then `simwork init my-app`. A pre-made prompt lets an AI assistant configure it for your harness. No rewrite of your code — routing happens by config.

**Post 5:**
Every run is gated on tool correctness + task completion. Same seed + same scenario = the same trace hash. We ran the demo 1,000 times: 1000/1000 passed, one hash, 42.6s, $0.

**Post 6:**
Open source (MIT), Python, 325 tests, CI green. Three runnable recipes: a RAG assistant, an API-backed agent, a multi-tool trip planner. Try it: github.com/SRogDev/SimWork — run `simwork demo` and tell me what breaks.

---

## 2. Reddit — r/LocalLLaMA

**Title:**
SimWork: test your AI app against scripted LLM + API mocks before spending a cent on real calls (open source, Python)

**Body:**
I kept hitting the same wall building AI apps: every test run costs real LLM
calls and real API calls, so either you pay to test properly or you ship
half-tested. I built SimWork to remove that bill.

What it does:

- Routes every AI call to a scripted, deterministic fake OpenAI server
  (`/v1/chat/completions`, tool calling included). Same seed + same scenario
  file = same trace, every time.
- Routes every world API call to a mock: it fetches the API's OpenAPI spec
  from the APIs.guru catalog and serves it with Prism, plus a stateful layer
  so a created record can be read back.
- Gates every run with DeepEval metrics (tool correctness + task
  completion) and prints a pass/fail report. An LLM judge is opt-in only —
  the default gate costs $0 and makes zero real network calls.
- `simwork init` scaffolds a starter, and a pre-made prompt lets an AI
  assistant configure SimWork for your existing harness — no rewrite, routing
  by config.

Proof it works at scale: `simwork scale` repeats the LangGraph demo 1,000
times — 1000/1000 passed, one trace hash, 42.6s, $0. There are three runnable
recipes too (RAG assistant, API-backed agent, multi-tool trip planner).

Honest limit: scripted mocks verify your app's logic and behaviour, not real
reasoning quality. SimWork tells you whether your app behaves correctly — not
how smart a real model would be.

MIT licensed, Python 3.11+, 325 tests, CI green:
https://github.com/SRogDev/SimWork

Install from git for now (`pip install git+https://github.com/SRogDev/SimWork`)
— PyPI publication is still to come. Try `simwork demo` and tell me what
breaks.

---

## 3. Reddit — r/Python

**Title:**
SimWork: simulate your AI app's LLM and API calls for $0 before launch (fake OpenAI server, Prism mocks, DeepEval gate)

**Posting note:** r/Python removes standalone self-promotion. Safest is the
monthly "What Are You Working On" megathread; if posting standalone, keep it
a text post about the technique (below) and be ready to answer in the
comments. Do not post the same text to both places.

**Body:**
I build AI apps on a near-zero testing budget, so I wrote SimWork: a Python
package that lets you simulate your harness end-to-end before any real LLM or
world API call.

The pieces:

- A scripted, deterministic fake OpenAI server (`/v1/chat/completions`,
  tool calling included). Scenarios live in YAML files; the agent loop
  terminates instead of looping forever.
- API mocks on demand: give it an API name, it fetches the OpenAPI spec
  from APIs.guru and serves it with Prism (sidecar subprocess). A stateful
  stub layer sits on top, so create-then-read works.
- A DeepEval-based gate: tool correctness + task completion, pass/fail per
  metric, exit code to match. The default gate is computed natively with the
  same semantics (DeepEval's metric constructor demands an API key), and the
  real DeepEval judge path is opt-in and budgeted.
- Determinism as a feature: seeded RNG + virtual clock, same seed + same
  scenario = same trace hash. `simwork scale` runs the demo 1,000 times:
  1000/1000 passed, one hash, 42.6s, $0.
- `simwork init` + a pre-made prompt file so an AI assistant can configure
  SimWork for an existing harness without the user hand-writing config.

MIT, Python 3.11+, uv, pytest, 325 tests, CI green:
https://github.com/SRogDev/SimWork

`pip install git+https://github.com/SRogDev/SimWork` (PyPI not published
yet), then `simwork demo`. Feedback welcome — especially on the scenario
format and on what a second harness family (plain LangChain / raw OpenAI
client) should look like.

---

## 4. Hacker News — Show HN

**Title:**
Show HN: SimWork – simulate your AI app's LLM and API calls for $0

**First comment:**
Hi HN — I built SimWork because testing AI apps kept costing real money:
every test run burns LLM calls and world API calls, so a thousand pre-launch
runs is either a real bill or a launch you half-tested.

SimWork routes every AI call to a scripted, deterministic fake OpenAI server
and every API call to a mock (OpenAPI spec fetched from APIs.guru, served by
Prism, with a stateful layer so create-then-read works). Every run is gated
with DeepEval metrics — tool correctness + task completion — and the default
gate makes zero real network calls. `simwork init` scaffolds a starter, and a
pre-made prompt lets an AI assistant configure it for your harness with no
rewrite.

Scale check: `simwork scale` repeats the LangGraph demo 1,000 times —
1000/1000 passed, one trace hash, 42.6s, $0.

Honest limit: scripted mocks verify logic and behaviour, not real reasoning
quality. This tells you whether your app behaves correctly, not how smart a
real model would be.

Open source (MIT), Python: https://github.com/SRogDev/SimWork

Install from git for now — PyPI is not published yet. Happy to answer
questions, especially about the scenario format and what would make this
useful for your harness.
