---
title: 'Scale: 1,000 runs'
description: Repeat the demo 1,000 times against shared mocks at $0 — the pre-launch use case.
---

The spec's scale criterion — thousands of simulated runs at $0, one deterministic report per run — as a command:

```bash
simwork scale                 # 1000 runs (default), shared mocks, one report
simwork scale --runs 100       # a smaller batch
simwork scale --report evals/scale-report.json
# SimWork scale report — 1000 runs in 42.6s (23.5 runs/s)
#   passed: 1000/1000
#   distinct trace hashes: 1 (f7af385c722c…)
# Overall: PASS
```

The batch starts both mocks once (fake OpenAI server + Prism ticket mock, via `simwork.demo.demo_servers`), builds the graph once, and repeats the demo run — resetting the scripted LLM between runs so every run replays the same scenario from the first turn. The batch passes only when every run passes the $0 gate *and* every run produces the same trace hash; a run that raises is recorded as a failed run with its error instead of aborting the batch. The machine-readable report (`--report`) carries one per-run result each (index, trace hash, verdict). Verified live 2026-11-19: 1000/1000 passed, one hash, 42.6s, $0.

## What this proves — and what it does not

A thousand identical-scenario runs prove throughput and determinism at scale: SimWork can run the volume a pre-launch test plan needs, for $0, with every run reproducible. They do **not** prove variety — a thousand copies of one scenario are still one situation. For a thousand *different* situations, write scenario families: parameterise scenarios by seed and by named variations (different user inputs, different tool results, different failure modes). See [Scenario files](/guides/scenarios/) and the [AI configuration prompt](/guides/ai-prompt/).

That is the shape of SimWork's first use case: a whole product tested before launch on a near-zero budget, thousands of simulated runs first, so you know how good the app will be in the real world before spending real API calls or production.
