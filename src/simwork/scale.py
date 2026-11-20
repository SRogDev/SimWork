"""The thousand-run scale smoke test (§7 check-off).

Repeats the LangGraph demo N times (default 1000) against the same
already-running mocks — one fake OpenAI server + one Prism mock, the
graph built once — and reports one deterministic per-run result each.
The batch passes only when every run passes the $0 gate AND every run
produces the same trace hash: that is what makes the Polygrow
pre-launch use case (thousands of simulated runs at $0, spec §4/S16)
demonstrably feasible.

Why the mocks are shared: starting a Prism process per run would
dominate the batch (a run itself is ~60 ms — two local HTTP calls plus
the eval). The scripted LLM is reset before each run
(`ScriptedLLM.reset()`), so every run replays the same scenario from
the first turn. Every run keeps the demo's `run_id`, so the trace
hashes are comparable across runs; the per-run identity is the run
index, recorded in the report.

A run that raises (exhausted script, mock down, ...) is recorded as a
failed run with its error instead of aborting the batch, so the report
shows the full picture; a setup failure (missing `prism`, missing demo
dependencies) still fails fast as `ScaleError` before any run.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simwork.demo import (
    EXPECTED,
    RUN_ID,
    SEED,
    USER_MESSAGE,
    DemoError,
    build_graph,
    demo_servers,
    messages_to_trace,
)
from simwork.eval import evaluate_run
from simwork.families import FamilyError, ScenarioFamily, load_family
from simwork.trace import trace_hash

DEFAULT_RUNS = 1000
# How many failed runs the human-readable report lists in full.
_MAX_FAILURES_SHOWN = 5


class ScaleError(Exception):
    """Raised when the scale batch cannot run (bad input, missing mocks)."""


@dataclass(frozen=True)
class ScaleRunResult:
    """One run's outcome: its trace hash, gate verdict, or its error."""

    index: int  # 1-based
    trace_hash: str | None  # None when the run raised before a trace existed
    passed: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "trace_hash": self.trace_hash,
            "passed": self.passed,
            "error": self.error,
        }


@dataclass(frozen=True)
class ScaleReport:
    """The batch report: one per-run result each, plus the verdict.

    `passed` is true only when every run passed the $0 gate and — in
    single-scenario mode — every run produced the same trace hash: a
    batch of identical runs that all pass is the scale criterion; a
    batch that diverges is not. In family mode (`hashes_must_match`
    false) the runs are *meant* to differ — one member per run — so
    the verdict only requires every run to pass the gate.
    """

    runs: int
    results: tuple[ScaleRunResult, ...] = field(default_factory=tuple)
    elapsed_seconds: float = 0.0
    family: str | None = None
    hashes_must_match: bool = True

    @property
    def passed_runs(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_runs(self) -> int:
        return self.runs - self.passed_runs

    @property
    def distinct_hashes(self) -> tuple[str, ...]:
        return tuple(sorted({r.trace_hash for r in self.results if r.trace_hash}))

    @property
    def passed(self) -> bool:
        return self.failed_runs == 0 and (
            not self.hashes_must_match or len(self.distinct_hashes) == 1
        )

    @property
    def runs_per_second(self) -> float:
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.runs / self.elapsed_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "passed": self.passed,
            "passed_runs": self.passed_runs,
            "failed_runs": self.failed_runs,
            "family": self.family,
            "hashes_must_match": self.hashes_must_match,
            "distinct_hashes": list(self.distinct_hashes),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "runs_per_second": round(self.runs_per_second, 2),
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self) -> str:
        """Machine-readable report (stable key order, deterministic)."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def to_text(self) -> str:
        """Human-readable report."""
        lines = [
            f"SimWork scale report — {self.runs} runs in {self.elapsed_seconds:.1f}s "
            f"({self.runs_per_second:.1f} runs/s)",
            f"  passed: {self.passed_runs}/{self.runs}",
        ]
        if self.family is not None:
            lines.append(f"  family: {self.family} — one member per run, distinct hashes expected")
        lines.append(
            f"  distinct trace hashes: {len(self.distinct_hashes)}"
            + (f" ({self.distinct_hashes[0][:12]}…)" if self.distinct_hashes else "")
        )
        failures = [r for r in self.results if not r.passed]
        for failure in failures[:_MAX_FAILURES_SHOWN]:
            lines.append(f"  run {failure.index}: FAILED — {failure.error or 'gate failed'}")
        if len(failures) > _MAX_FAILURES_SHOWN:
            lines.append(f"  … and {len(failures) - _MAX_FAILURES_SHOWN} more failed run(s)")
        lines.append(f"Overall: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines) + "\n"


def run_scale(
    runs: int = DEFAULT_RUNS,
    family: ScenarioFamily | str | Path | None = None,
) -> ScaleReport:
    """Run the demo `runs` times against shared mocks; return the report.

    Fails closed (`ScaleError`) on a non-positive run count or on a
    missing mock/dependency; per-run failures are recorded in the
    report instead of aborting the batch.

    With `family` (a `ScenarioFamily`, or a path to a family YAML
    file), run `i` uses family member `i-1`: the scripted LLM's script
    is swapped per run, so the batch covers a thousand different
    situations instead of one repeated scenario. The verdict then
    requires every run to pass the gate; the trace hashes are expected
    to differ.
    """
    if runs < 1:
        raise ScaleError(f"runs must be a positive integer, got {runs}")
    family_obj: ScenarioFamily | None = None
    if family is not None:
        try:
            family_obj = family if isinstance(family, ScenarioFamily) else load_family(family)
        except FamilyError as e:
            raise ScaleError(str(e)) from None
    try:
        with demo_servers() as (llm, llm_server, api_server):
            app = build_graph(api_server.base_url, llm_server.base_url)
            results: list[ScaleRunResult] = []
            start = time.monotonic()
            for index in range(1, runs + 1):
                try:
                    if family_obj is not None:
                        member = family_obj.member(index - 1)
                        llm.replace_script(member.scenario.turns, seed=member.seed)
                        expected: dict[str, Any] | None = member.expected
                        seed = member.seed
                    else:
                        llm.reset()
                        expected = EXPECTED
                        seed = SEED
                    result = app.invoke({"messages": [{"role": "user", "content": USER_MESSAGE}]})
                    trace = messages_to_trace(
                        result["messages"], run_id=RUN_ID, seed=seed, expected=expected
                    )
                    report = evaluate_run(trace)
                    results.append(
                        ScaleRunResult(
                            index=index, trace_hash=trace_hash(trace), passed=report.passed
                        )
                    )
                except Exception as e:  # noqa: BLE001 — one bad run must not kill the batch
                    results.append(
                        ScaleRunResult(index=index, trace_hash=None, passed=False, error=str(e))
                    )
            return ScaleReport(
                runs=runs,
                results=tuple(results),
                elapsed_seconds=time.monotonic() - start,
                family=family_obj.name if family_obj is not None else None,
                hashes_must_match=family_obj is None,
            )
    except DemoError as e:
        raise ScaleError(str(e)) from e
