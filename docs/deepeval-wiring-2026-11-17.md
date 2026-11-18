# DeepEval wiring — verification note (2026-11-17)

Phase 3, task 1: the first slice of the DeepEval harness. This note records
what was verified about the DeepEval library itself, and the decision that
followed, so a later run does not re-litigate it.

## What was checked

- **DeepEval 4.3.4** installs cleanly from PyPI (`uv pip install deepeval`
  into a scratch venv, Python 3.12).
- **`ToolCorrectnessMetric` is deterministic and works offline** — with a
  dummy `OPENAI_API_KEY` set, `measure()` on an exact-match test case
  returned score `1.0` with no network call. The computation is exact
  name + arguments matching, as SimWork's native metric implements it.
- **But its constructor demands an API key**: `ToolCorrectnessMetric()`
  with no `OPENAI_API_KEY` in the environment raises
  `DeepEvalError: OpenAI API key is not configured`, before any
  measurement happens. The metric class eagerly builds an OpenAI model
  even though the metric itself never calls it.
- **`TaskCompletionMetric` is an LLM judge** (G-Eval style) — it needs a
  real model call, so it cannot be part of the $0 default gate.

## Decision (invented under SimWork-only autonomy)

The v0.1 gate computes **tool correctness** and **task completion**
natively in `simwork/eval.py`, with the same names and semantics as
DeepEval's metrics, and `simwork eval` reads a recorded trace JSON and
prints/writes a pass/fail report. No `deepeval` dependency is added in
this slice, and no API key is required anywhere in the $0 path.

Rationale:

- Adding `deepeval` now would force every `$0` eval run to carry an
  `OPENAI_API_KEY` (real or dummy) just to construct a metric that never
  calls the model — a footgun that contradicts the spec's $0 default and
  no-secrets rule.
- The deterministic metrics are small, exact, and fully tested (27 tests
  in `tests/test_eval.py`); the library adds a large dependency tree for
  no behavioural gain in this slice.

## Later Phase 3 work

- Wire DeepEval's own classes (pytest-native `evaluate()` /
  `assert_test`) when the harness needs LLM-judge metrics — opt-in, off
  by default, budgeted per run, per the spec.
- Re-check the constructor behaviour on a newer DeepEval version before
  wiring: if a future version makes the model lazy, the native metrics
  can delegate to the library classes without changing the report shape.

## Phase 3, task 3 — wiring done (2026-11-18)

Re-checked before wiring: **DeepEval 4.3.4 is still the latest release**
(installed fresh 2026-11-18; no newer version). The constructor still
demands `OPENAI_API_KEY`, so the native $0 gate stays the default and
the library is an optional dependency (`simwork[deepeval]`).

Two things the first verification missed, found by reading the library
source after a wrong-arguments case scored 1.0:

- `ToolCorrectnessMetric(should_exact_match=True)` compares tool
  **names only** unless `ToolCallParams.INPUT_PARAMETERS` is in
  `evaluation_params`. With that flag, plus `async_mode=False`, the
  library metric matches SimWork's native metric exactly (name +
  arguments, order-sensitive, same empty-case behaviour), works offline
  with a dummy key, and makes no network call (a real call with a dummy
  key would fail auth — a returned score proves no call happened).
- `TaskCompletionMetric` is an LLM judge (default model `gpt-5.4` in
  4.3.4); `task=None` falls back to the test case's `input`, so SimWork
  passes the run's task text (run id + expected facts) as `input`.

Wiring (`simwork/deepeval_judge.py`, `simwork eval --judge`):

- `trace_to_test_case` converts a SimWork trace to a DeepEval
  `LLMTestCase`; `judge_metrics` builds the library metric objects,
  so a pytest file can call DeepEval's own `evaluate()` /
  `assert_test` directly.
- `run_judge` / `evaluate_run_with_judge` append
  `judge_tool_correctness` / `judge_task_completion` to SimWork's
  report shape; the trace hash is unchanged, so a judged report stays
  comparable to a $0 report of the same trace.
- Budget: `max_llm_calls` counts real model calls (tool correctness 0,
  task completion 1; default 1). A run whose judge work exceeds the
  budget fails closed before any call. Missing deepeval, missing key,
  or unknown metric name all fail closed with a clear error.
- Judge thresholds default to DeepEval's own 0.5 (the native gate's
  strict 1.0 does not apply to fuzzy judge scores).

Evidence: pytest 150/150 in the project venv (2 real-library tests
skipped — deepeval not installed, by design); with deepeval 4.3.4
installed in a scratch venv the same file runs 25 passed / 2 skipped,
including the real-library checks that the library tool-correctness
metric scores 1.0 on the example trace and 0.0 on wrong arguments,
offline, dummy key. Live CLI: `simwork eval --judge` without deepeval
exits 1 with install guidance; with deepeval + dummy key and
`--judge-metrics tool_correctness` it reports
`judge_tool_correctness: 1.00 PASS` with the same trace hash
`b0122a56…` as the $0 report.
