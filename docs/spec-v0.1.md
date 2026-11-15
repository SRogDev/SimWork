# Spec: SimWork v0.1

## 1. Intent summary

SimWork lets developers like Roger simulate AI-app functionality first, before spending real LLM API calls or touching production. The user adds SimWork to an existing Python app or harness with minimal setup, ideally configured by an AI assistant from a pre-made prompt, and every AI call routes to an LLM mock and every API call routes to an API mock. All runs are evaluated. [S7–S10]

## 2. Goals

- A Python developer can add SimWork to an existing harness in under 15 minutes of setup work, with no rewrite of the harness. [S9–S10]
- A full simulated run costs $0 in LLM and world-API spend by default, with zero real network calls to LLM providers or real world APIs. [S9–S10]
- Every simulated run produces a DeepEval-based pass/fail report covering the whole run, not only one prompt. [S7, S10]
- v0.1 ships as a working open-source Python package with an end-to-end demo harness that runs fully simulated. [S1, S7]

## 3. Scope

- In: Python package + CLI `simwork`; LLM mock (OpenAI-compatible fake server, scripted + deterministic); API mock via Prism + APIs.guru catalog plus YAML stateful stubs; DeepEval harness + report; `simwork init` + pre-made AI configuration prompt; one end-to-end demo harness (LangGraph-based); docs + README in English; CI with pytest.
- Out: managed/hosted service (deferred — see §9, decided only 7+ days after start); Rust rewrite or Rust runner; TypeScript harness support; real LLM judge by default; a pre-built fake market for arbitrary businesses (that is the Polygrow enterprise simulator, a separate product); production deployment of user apps; billing, auth, or multi-tenancy.

## 4. Requirements

- [MUST] SimWork runs in Python, with DeepEval for evals. [S7]
- [MUST] Adding SimWork to an existing Python app/harness requires no rewrite of the harness: routing happens by configuration — environment variables / base-URL swap and/or provider override — not by editing app logic. [S4, S10]
- [MUST] In simulate mode, every AI call routes to the LLM mock and every API call routes to the API mock, by default. [S10]
- [MUST] Simulate mode makes zero real calls to LLM providers and zero real calls to world APIs, and fails closed (errors visibly) instead of silently falling back to a real call if a mock is missing. [S9–S10]
- [MUST] The LLM mock is OpenAI-compatible (`/v1/chat/completions`, including tool calling) so existing OpenAI-compatible clients work unchanged. [S10]
- [MUST] The LLM mock is scripted and deterministic: same seed + same scenario file produces the same trace, and an agent loop terminates (tool-result detection) instead of looping forever. [S4, S10]
- [MUST] Scenarios are defined in files, not code: YAML scenario files define scripted LLM responses, API stubs, and world rules. [S4, S10]
- [MUST] API mocks come from the APIs.guru catalog on demand: given an API name, SimWork fetches its OpenAPI spec and serves it as a mock (Prism as the mock engine). Only the APIs actually touched run; the hundreds stay in the catalog. [S4]
- [MUST] API mocks include stateful behaviour for at least the v0.1 demo: a stub that remembers what was written can be read back (e.g. a created record appears in a later list/get). Prism alone is stateless, so SimWork must add the state layer. [S4]
- [MUST] Every run is evaluated with DeepEval, pytest-native, and produces a machine-readable + human-readable report with per-metric pass/fail and an overall gate. [S7, S10]
- [MUST] `simwork init` generates a working starter config, scenario, and eval suite for the user's harness, and ships a pre-made prompt file an AI assistant can follow to configure SimWork for a new app without the user hand-writing config. [S10]
- [MUST] The factory builds SimWork in small batches, one plan task at a time, with tests, landing on `main` without asking permission per task (SimWork-only autonomy, Roger 2026-11-15). [S1, S8, S15]
- [SHOULD] Reuse Tenro where it fits for LLM interception, instead of rebuilding that layer from scratch; fall back to SimWork's own fake OpenAI server when Tenro does not fit the user's harness (e.g. harness Tenro does not support). [S4]
- [SHOULD] Reuse Mesa + SimPy for the world engine (rule-based agent population + discrete-event clock) rather than inventing a new engine, starting with one decision type in the demo. [S4]
- [SHOULD] Support LangGraph harnesses first (LangGraph is the harness family in Roger's own backends), then plain LangChain / raw OpenAI clients. [S4]
- [SHOULD] Ship the demo as a small LangGraph agent app that calls one LLM and one world API, so the end-to-end simulated run exercises both mocks and the eval gate. [S9–S10]

## 5. Constraints

- [MUST] Stack is Python 3.11+, managed with `uv` only (`uv venv`, deps in `pyproject.toml`, `uv.lock` committed); never `pip` + `requirements.txt` as source of truth. [S7]
- [MUST] Default run cost is $0: no paid LLM calls, no paid API calls, deterministic mocks only. Any LLM-judge evaluation is opt-in, off by default, and budgeted per run. [S9–S10]
- [MUST] Determinism: seeded RNG and a virtual clock; same seed + same scenario = same trace and same eval report. [S10]
- [MUST] No secrets in the repo, no real API keys in fixtures or scenarios; simulated credentials only. [S9]
- [MUST] Open-source repo `SRogDev/SimWork`, public; licence decision is OPEN (MIT is Roger's usual for dev tools, not yet decided). [S2]
- [MUST] The managed service is NOT in v0.1 and is NOT designed in v0.1; it is invented by Muse only 7+ days after starting, if Roger then wants it. [S2]
- [MUST] Factory cadence is about every 6 hours, one small task per run, with a report in this chat (the SimWork factory chat); nothing merges without Roger. [S1, S3, S8]
- [MUST] Repo vs factory separation: only SimWork product code/docs go to the `SRogDev/SimWork` repo; factory machinery around it (run state, factory notes, factory improvements) stays local in Muse (this chat + `workspace/goals/simwork-build/`), never in the repo. [S13]
- [MUST] Full factory autonomy in this chat (Roger 2026-11-15, SimWork-only): in this chat Muse IS the factory — it invents the spec and implements it without asking Roger for permission, and leaves nothing merely noted. Invented decisions are implemented, reported in this chat, and correctable by Roger afterwards. This does not suspend the $0 default, the no-secrets rule, or the managed-service deferral. [S14, S15]
- [MUST] Work lands on `main` in small batches, at human pace (one small task per 6h run, no bursts), with a report in this chat after each landing; Roger corrects afterwards if anything is wrong. [S15]
- [MUST] Every significant change ships a README touch-up in the same PR; READMEs in English and current. [S1]
- [MUST] The spec is the constitution: code that contradicts this spec is drift by definition, not an improvement; evals + acceptance criteria are the gate. [S1]

## 6. Dependencies

- Python 3.11+ + `uv` — package and test runtime. [S7]
- DeepEval (Apache 2.0, pytest-native) — eval metrics and CI gate. [S7]
- Tenro (Apache 2.0, 0.2.3, Python 3.11+) — candidate LLM-interception layer, to be evaluated in Phase 1 before adopting or replacing. [S4]
- Prism (Apache 2.0, Node 18+) + APIs.guru REST catalog (2,529 APIs) — API-mock shape on demand; Prism runs as a sidecar subprocess, not as a Python dependency. [S4]
- Mesa (Apache 2.0) + SimPy (MIT) — world engine (agents + discrete-event clock), Phase 2+. [S4]
- LangGraph (for the demo harness) + `openai` Python client (for the OpenAI-compatible surface) — demo + compatibility targets. [S4]
- GitHub repo `SRogDev/SimWork` (public, empty, no licence yet, no `main` branch yet — verified 2026-11-15 via API: size 0) — delivery target; first commit via contents API, then `push_repo.py` pattern. [S1]

## 7. Acceptance criteria

- [ ] `pip install simwork` / `uv add simwork` installs, `simwork --help` works, and `simwork init` generates a runnable starter in a fresh directory. [S10]
- [ ] Demo LangGraph harness runs end-to-end with `SIMWORK_MODE=simulate` and makes zero real HTTP calls to any LLM provider or real world API (verified by a test that asserts no real host is contacted). [S9–S10]
- [ ] Same seed + same scenario run twice produces an identical trace hash and identical eval report. [S10]
- [ ] `simwork eval` runs DeepEval metrics (at minimum: tool correctness, task completion) and exits non-zero when the gate fails, with a report file. [S7, S10]
- [ ] `simwork mock --api <name>` fetches the spec from APIs.guru and serves a Prism mock for it; the demo's world API is served this way. [S4]
- [ ] A stateful stub test passes: create-then-read returns the created record. [S4]
- [ ] `pytest` suite green in CI; README documents the 15-minute setup, the pre-made prompt, and the $0 default. [S1, S10]
- [ ] No merge to `main` has happened without Roger's explicit confirmation for that series. [S1, S8]

## 8. Assumptions

- [ASSUMES] The user's harness is Python and OpenAI-compatible (OpenAI client, LangChain, or LangGraph); non-Python harnesses are out of v0.1. — confirm with user [S4, S10]
- [ASSUMES] Prism as a Node sidecar subprocess is acceptable for v0.1 (requires Node 18+ on the dev machine); a pure-Python OpenAPI mock generator is a later optimisation, not v0.1. — confirm with user [S4]
- [ASSUMES] DeepEval's deterministic / rule-based metrics suffice for the v0.1 gate; LLM-judge metrics (e.g. G-Eval) stay opt-in and off by default. — confirm with user [S7]
- [ASSUMES] The v0.1 demo uses one LLM call chain + one world API, not a full multi-agent system; multi-agent simulation is v0.2+. — confirm with user [S9]
- [ASSUMES] Licence will be MIT (Roger's usual for dev tools) unless Roger decides otherwise. — confirm with user [S2]

## 9. Open questions

- [OPEN] Licence: MIT or another licence? Blocks: first commit / public release. [S2] — Under the 2026-11-15 autonomy order this does NOT block: the factory decides MIT (Roger's usual for dev tools) and implements it; Roger corrects afterwards if he wants another licence.
- [OPEN] Which harness is the v0.1 demo: LangGraph (Roger's backends) or a minimal raw-OpenAI app for maximum generality? Blocks: Phase 1 demo design. [S4, S9] — Under autonomy this does NOT block: the factory decides (LangGraph first) and implements it.
- [OPEN] Which DeepEval metrics are mandatory in the v0.1 gate beyond tool correctness + task completion? Blocks: eval suite design. [S7, S10] — Under autonomy this does NOT block: the factory decides and implements the gate.
- [OPEN] Tenro: adopt as the LLM-interception layer, or build SimWork's own fake OpenAI server from the start? Blocks: Phase 1 implementation. [S4] — Under autonomy this does NOT block: the factory decides in Phase 1 and implements it.
- [OPEN] Managed service (7+ days later): what is it — hosted sim runs, hosted mocks, eval CI? Not to be decided or designed in v0.1. Blocks: nothing in v0.1. [S2]

## 10. Source index

- S1: "a partir de ahora este chat es la software factory de SimWork, tu harás esa app, no yo, a veces te daré inputs de que hacer y mi opinión es la que mas vale, pero la idea es que dia tras dia tu construyas la app, pero como una software factory real" + "SimWork sera un proyecto opensource vez, muy necesario"
- S2: "un servicio managed de ello quiza, que tu mismo inventarias no yo, pero solo 7 días después de empezar"
- S3: "trabajaras en esto cada 6 horas un poco o algo asi"
- S4: "El stack pues, quiza rust? Sería mejor el simulador? Un binario rust ultra potente que corra la simulación, mientras esta se puede definir en rust, python o typescript segun?, pero de alguna forma que un user tiene su harness y sin reescribir nada pueda simularlo completamente como si fuera real sin usar apis de llm reales o de apis de mundo (reutilicemos cosas para esto)"
- S5: "No pero, rust no tiene herramientas para crear esta simulación?"
- S6: "Entonces el ecosistema de simulación para ias y api esta mas potente en python?"
- S7: "Si usaremos deep eval si. Bien pues en python pues vamos."
- S8: "Ahora esto debe funcionar como una software factory real, debes arreglartelas tu."
- S9: "Mi objetivo es: Que gente como yo, pueda simular primero funcionalidades de ia, antes de gastar apis reales o produccion."
- S10: "Que simplemente agregue eso a mi app o harness, y no tenga que hacer nada complicado, que venga pensado para configurar se con ias, quiza un prompt prehecho, y que simplemente se enrute a llm mock cada ai call y a api mock cada api call. Y listo, con Evals de todo vamos."
- S11: Factory gates agreed in this chat: goals with acceptance criteria, spec as constitution, evals as gate, small batches + human checkpoints, reversibility, no merge without Roger.
- S12: Verified research 2026-11-15: Python ecosystem more mature for AI/API simulation (Mesa 3.5.2, SimPy 4.1.2, Tenro 0.2.3, Inspect AI, DeepEval, Ragas, tau-bench); Rust has krABMaga, odem-rs, wiremock-rs, Rig, but no Tenro/Prism equivalent; APIs.guru 2,529 APIs + Prism for mock shape.
- S13: "Al repo Sim work van las cosas de Sim work, la factory alrededor de el no, permanece en local en ti."
- S14: "Ojo, si pasan 6 horas y no te pido nada mas, tu mismo te inventas la spec y eso, o sea ejecutas el proceso normal de factory y asi sigues avanzando el proyecto solo"
- S15: "No dejas anotado nada, en éste chat eres la factory, te inventas la spec y la implementas sin pedirme permiso"
