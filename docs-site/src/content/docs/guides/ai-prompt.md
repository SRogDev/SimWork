---
title: AI configuration prompt
description: A pre-made prompt that configures SimWork for a new app — hand it to an AI assistant and it does the setup.
---

You don't have to hand-write the setup: `prompts/configure-simwork.md` is a prompt file you hand to an AI assistant (paste it into a chat, or point the assistant at the file, together with your harness code) and it configures SimWork for your app — inspecting the harness, routing LLM calls to the fake server and world APIs to the mocks, writing the scenarios, recording a trace, and gating the run. `simwork init` copies the same prompt into every starter as `prompts/configure-simwork.md`, so it travels with your project.

The single source of truth is `simwork.prompt.CONFIGURE_SIMWORK_PROMPT`; the repo file and the generated copy are guarded against drift by tests.

## What the prompt teaches

The hard gates ($0 by default, no harness rewrite, fail closed, no secrets), the six-step workflow below, scale for thousands of runs (parameterised scenario families, one report per run), and realism (scenario fidelity grounded in real behaviour, small-sample calibration opt-in, failure modes in scenarios) — plus a done checklist and an honest statement of what simulation does *not* prove.

## The six-step workflow

1. **Inspect the harness** — find every place the app calls an LLM and every place it calls a world API. List them; change none of the code.
2. **Route the LLM calls to the mock** — point the harness at the fake OpenAI server with a base-URL swap (`simwork serve` or `SimWorkRouter`).
3. **Write the scenario** — one YAML scenario per behaviour, with a fixed seed, grounded in real behaviour.
4. **Route the world APIs to the mock** — `simwork mock --api <name>`, with `--stateful` when the harness writes and then reads back.
5. **Record a trace and gate it** — `TraceRecorder` captures the run; `simwork eval` gates it; add the trace to the pytest suite so CI gates on it.
6. **Verify $0 and determinism** — confirm no real host is contacted, the same seed + scenario twice gives the same trace hash, and the gate goes red when a scenario is deliberately broken.

## Scale and realism

The first use case for SimWork is an app that needs thousands of pre-launch simulated runs at $0. The prompt configures for that: scenario families, not copies; cheap, deterministic, bulk-evaluable runs; failures treated as data about the app, not broken simulations.

On realism, the prompt is explicit: scripted mocks verify logic and behaviour, not real reasoning quality — never claim a simulation proves the real model would behave the same way. Maximise realism within the $0 constraint through scenario fidelity and, where the user approves, a small real calibration sample.

## Done checklist

The prompt ends with a checklist: every LLM call routed to the fake server, every world-API call to a mock, a scenario per behaviour with a fixed seed, a recorded trace + eval suite gating the run, identical trace hash on repeat runs, the gate going red on a deliberately broken scenario, scenario families covering the main variations including at least one failure mode, and no secrets in any file created.
