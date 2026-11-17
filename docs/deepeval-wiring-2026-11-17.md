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
