---
title: Evals & the $0 gate
description: Every simulated run is evaluated — tool correctness + task completion, deterministic, $0.
---

Every simulated run is evaluated. The first slice evaluates a recorded run trace (JSON) with two deterministic metrics — **tool correctness** (share of expected tool calls matched exactly, name + arguments) and **task completion** (the final answer contains the expected facts) — and produces a pass/fail report. No LLM judge, no network, $0. Both metrics default to a strict threshold of 1.0.

## Evaluate a trace

```bash
# Evaluate a recorded trace (see examples/ticket-status-trace.json)
simwork eval --trace trace.json
# SimWork eval report — run: ticket-status-1 (seed 7)
# trace: b0122a56efdfda2a9df27860cb73344c05f1855f6e36622b76b7d1bcca7bd5e0
#   tool_correctness: 1.00 (threshold 1.00) PASS — 1/1 expected tool call(s) matched
#   task_completion: 1.00 (threshold 1.00) PASS — final answer contains all expected facts
# Overall: PASS

# Also write the machine-readable JSON report
simwork eval --trace trace.json --report report.json
```

`simwork eval` exits 0 when the gate passes and 1 when it fails. Loading is strict: a bad trace fails closed instead of producing a wrong report.

## Trace format

A trace is a JSON object with `steps` (assistant turns, with `content` and/or `tool_calls`, plus `tool_result` steps) and `expected` (`tool_calls` the run should have made, `final_answer_contains` facts the final answer should cover). The report carries a `trace_hash` (SHA-256 of the canonical trace JSON), so the same seed + same scenario run twice produces an identical report.

## Recording a trace from a simulated run

Traces need not be hand-written. A `TraceRecorder` captures one from a real simulated run: hand it to the scripted LLM (or the fake server / router) and it records every assistant completion; the harness records each tool result after executing the tool the LLM asked for. The recorded trace feeds straight into `simwork eval`:

```python
from simwork.llm import ScriptedLLM
from simwork.trace import TraceRecorder, completion_to_step

recorder = TraceRecorder(run_id="ticket-status-1", seed=7)
llm = ScriptedLLM(script, seed=7, recorder=recorder)
messages = [{"role": "user", "content": "What's the status of ticket T-123?"}]
for _ in range(len(script)):
    completion = llm.complete(messages)          # assistant step recorded
    for call in completion_to_step(completion).get("tool_calls", []):
        result = lookup_ticket(**call["arguments"])   # the harness executes the tool
        recorder.record_tool_result(call["name"], result)
        messages.append({"role": "tool", "content": json.dumps(result)})
recorder.save("trace.json", expected={...})      # eval-ready, validated
```

```bash
simwork eval --trace trace.json   # same report as for a hand-written trace
```

Recording is deterministic: the same seed + same scenario run twice produces an identical trace hash. A recorder holds one run — use a fresh recorder per run. Recording a malformed completion or a non-JSON tool result fails closed instead of producing a wrong trace.

## Opt-in DeepEval judge

The judge path wires DeepEval's own classes (`simwork.deepeval_judge`), off by default. It needs the optional dependency plus a key, and the task-completion judge makes a real, billable model call — the tool-correctness judge metric is deterministic and makes no call:

```bash
uv pip install 'simwork[deepeval]'
export OPENAI_API_KEY=sk-...          # real key: the judge spends real money
simwork eval --trace trace.json --judge
simwork eval --trace trace.json --judge --judge-model gpt-4o-mini --judge-max-calls 1
# ... judge_tool_correctness: 1.00 (threshold 0.50) PASS — ...
# ... judge_task_completion: 1.00 (threshold 0.50) PASS — ...
```

`--judge-max-calls` (default 1) is a per-run budget on real LLM calls: tool correctness costs 0, task completion costs 1, and a run whose judge work exceeds the budget fails closed before any call. `--judge-metrics tool_correctness` runs only the deterministic metric (a dummy key suffices for that one). Judge thresholds default to DeepEval's 0.50, not the native gate's strict 1.0. Judge scores are LLM-generated, so a judged report is not reproducible run-to-run — the trace hash is unchanged, only the judge scores vary. In pytest, `trace_to_test_case` + `judge_metrics` let you call DeepEval's own `evaluate()` / `assert_test` directly (see `simwork.deepeval_judge`).

Why the $0 gate computes the metrics natively instead of using DeepEval's classes directly: DeepEval's `ToolCorrectnessMetric` constructor demands an `OPENAI_API_KEY`, even though the metric itself never calls a model — that would break the $0 default. See [Design decisions](/reference/decisions/).
