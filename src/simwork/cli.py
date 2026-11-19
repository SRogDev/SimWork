"""Command-line entry point for SimWork.

Phase 1: `serve` starts the fake OpenAI server from a scenario file so
an unmodified harness can point at it with a base-URL swap. `mock`
(Phase 2) and `eval` (Phase 3) are wired — `eval --judge` adds the
opt-in DeepEval judge path; `init` lands in Phase 4, per the spec.
`demo` (Phase 4, task 3) runs the LangGraph demo end-to-end. `scale`
(§7 check-off) repeats the demo N times against shared mocks and
checks every run is identical and passes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from simwork import __version__
from simwork.api_mock import ApiMockError, ApiMockStack
from simwork.config import ConfigError, load_file_config, resolve_config, resolve_eval
from simwork.deepeval_judge import JudgeError, check_judge_ready, evaluate_run_with_judge
from simwork.demo import DemoError, run_demo
from simwork.eval import evaluate_run
from simwork.trace import TraceError, load_trace, trace_hash
from simwork.init import InitError, init_project
from simwork.llm import ScenarioError
from simwork.routing import RoutingError, SimWorkRouter
from simwork.scale import DEFAULT_RUNS, ScaleError, run_scale
from simwork.serving import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simwork",
        description=(
            "SimWork — simulate AI-app functionality first, before spending "
            "real LLM or world API calls. Every simulated run costs $0 by default."
        ),
    )
    parser.add_argument("--version", action="version", version=f"simwork {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser(
        "serve",
        help="serve the fake OpenAI server from a scenario file (simulate mode)",
        description=(
            "Start the scripted, deterministic fake OpenAI server from a YAML "
            "scenario file and print the env vars a harness needs to point at "
            "it. Runs until Ctrl-C. $0 — no real LLM calls."
        ),
    )
    serve.add_argument(
        "--scenario",
        metavar="FILE",
        help="YAML scenario file (overrides SIMWORK_SCENARIO)",
    )
    serve.add_argument(
        "--config",
        metavar="FILE",
        default=None,
        help="simwork.yaml config file (default: auto-discovered from the current directory up)",
    )
    serve.add_argument(
        "--host",
        default=None,
        help="bind host (overrides SIMWORK_HOST, default 127.0.0.1)",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=None,
        help="bind port (overrides SIMWORK_PORT, default 0 = ephemeral)",
    )

    mock = sub.add_parser(
        "mock",
        help="serve a Prism mock for an API from the APIs.guru catalog",
        description=(
            "Fetch an API's OpenAPI spec from APIs.guru (cached under "
            "~/.cache/simwork) and serve it as a mock with Prism, so a harness "
            "can call the API without touching the real one. Runs until Ctrl-C. "
            "$0 — no real world-API calls."
        ),
    )
    mock.add_argument(
        "--api",
        metavar="NAME",
        required=True,
        help="APIs.guru API name, e.g. github.com (its preferred version is used)",
    )
    mock.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind host (default 127.0.0.1)",
    )
    mock.add_argument(
        "--port",
        type=int,
        default=0,
        help="bind port (default 0 = ephemeral)",
    )
    mock.add_argument(
        "--cache-dir",
        default=None,
        help="cache directory for the catalog + specs (default ~/.cache/simwork)",
    )
    mock.add_argument(
        "--stateful",
        action="store_true",
        help=(
            "add the stateful stub layer in front of Prism: writes are "
            "remembered, so create-then-read returns the created record"
        ),
    )

    eval_cmd = sub.add_parser(
        "eval",
        help="evaluate a recorded run trace (DeepEval harness)",
        description=(
            "Evaluate a recorded run trace (JSON, see examples/) with the "
            "deterministic metrics tool correctness + task completion and "
            "print a pass/fail report. Exits 0 when the gate passes, 1 when "
            "it fails. $0 — no LLM judge, no network. With --judge, also run "
            "DeepEval's own metric classes (opt-in: needs deepeval installed "
            "and OPENAI_API_KEY; the task-completion judge makes a real, "
            "billable model call)."
        ),
    )
    eval_cmd.add_argument(
        "--trace",
        metavar="FILE",
        default=None,
        help="JSON trace file of a recorded run (default: eval.trace from simwork.yaml)",
    )
    eval_cmd.add_argument(
        "--config",
        metavar="FILE",
        default=None,
        help="simwork.yaml config file (default: auto-discovered from the current directory up)",
    )
    eval_cmd.add_argument(
        "--report",
        metavar="FILE",
        default=None,
        help="also write the machine-readable JSON report to this file",
    )
    eval_cmd.add_argument(
        "--judge",
        action="store_true",
        help=(
            "also run DeepEval's own judge metrics (opt-in, costs real LLM "
            "calls for task completion; needs 'simwork[deepeval]' + "
            "OPENAI_API_KEY)"
        ),
    )
    eval_cmd.add_argument(
        "--judge-model",
        metavar="MODEL",
        default=None,
        help="model for the DeepEval judge (default: DeepEval's default)",
    )
    eval_cmd.add_argument(
        "--judge-max-calls",
        metavar="N",
        type=int,
        default=1,
        help="max real LLM calls the judge may make (default 1)",
    )
    eval_cmd.add_argument(
        "--judge-metrics",
        metavar="NAMES",
        default="tool_correctness,task_completion",
        help=("comma-separated judge metrics to run (default: tool_correctness,task_completion)"),
    )

    init_cmd = sub.add_parser(
        "init",
        help="scaffold a working SimWork starter in a directory",
        description=(
            "Generate a working starter in a directory: simwork.yaml config, "
            "a YAML scenario for the scripted LLM, and an eval suite (a "
            "recorded trace + a pytest file that gates on it), plus a starter "
            "README and the pre-made AI configuration prompt "
            "(prompts/configure-simwork.md). The generated scenario parses "
            "and the trace passes the $0 eval gate before anything is "
            "written. Existing files owned by init are only overwritten "
            "with --force; other files in the directory are never touched."
        ),
    )
    init_cmd.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="target directory (default: current directory; created if missing)",
    )
    init_cmd.add_argument(
        "--force",
        action="store_true",
        help="overwrite files owned by init if they already exist",
    )

    demo_cmd = sub.add_parser(
        "demo",
        help="run the LangGraph demo end-to-end (simulate mode)",
        description=(
            "Run the LangGraph demo agent end-to-end in simulate mode: "
            "one LLM call to the scripted fake OpenAI server, one world-API "
            "call to a Prism mock of the bundled ticket API, then the $0 eval "
            "gate on the recorded trace. Prints the pass/fail report and the "
            "trace hash; exits 0 when the gate passes, 1 when it fails. "
            "Needs the demo dependencies (`uv sync --group demo`) and the "
            "`prism` binary. $0 — no real LLM or world-API calls."
        ),
    )
    demo_cmd.add_argument(
        "--trace",
        metavar="FILE",
        default=None,
        help="also write the recorded trace as JSON to this file",
    )
    demo_cmd.add_argument(
        "--report",
        metavar="FILE",
        default=None,
        help="also write the machine-readable JSON report to this file",
    )

    scale_cmd = sub.add_parser(
        "scale",
        help="repeat the LangGraph demo N times and check every run is identical and passes",
        description=(
            "Repeat the LangGraph demo N times (default 1000) against the "
            "same already-running mocks — one fake OpenAI server + one Prism "
            "mock, the graph built once — and check every run passes the $0 "
            "gate with the same trace hash. This is the spec's scale smoke "
            "test (§7): thousands of simulated runs at $0 before launch, one "
            "deterministic per-run result each. Prints a summary; exits 0 "
            "when every run passed and all hashes are identical, 1 otherwise. "
            "Needs the demo dependencies (`uv sync --group demo`) and the "
            "`prism` binary. $0 — no real LLM or world-API calls."
        ),
    )
    scale_cmd.add_argument(
        "--runs",
        metavar="N",
        type=int,
        default=DEFAULT_RUNS,
        help=f"number of runs (default {DEFAULT_RUNS})",
    )
    scale_cmd.add_argument(
        "--report",
        metavar="FILE",
        default=None,
        help="also write the machine-readable JSON report to this file",
    )
    return parser


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the fake server from a scenario; block until Ctrl-C."""
    try:
        file_config = load_file_config(args.config)
        env = dict(os.environ)
        # `serve` is inherently simulate mode; flags override env vars,
        # env vars override the config file, the file overrides defaults.
        env["SIMWORK_MODE"] = "simulate"
        config = resolve_config(
            file_config,
            env,
            scenario=args.scenario,
            host=args.host,
            port=args.port,
        )
    except (RoutingError, ConfigError, ValueError) as e:
        print(f"simwork serve: error: {e}", file=sys.stderr)
        return 1

    def banner(router: SimWorkRouter) -> list[str]:
        return [
            f"SimWork fake OpenAI server running (scenario: {config.scenario_path})",
            *(f"{key}={value}" for key, value in router.env_overrides.items()),
        ]

    try:
        serve(SimWorkRouter(config), banner=banner, stopping="Stopping fake OpenAI server.")
    except ScenarioError as e:
        print(f"simwork serve: error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_mock(args: argparse.Namespace) -> int:
    """Fetch an API spec from APIs.guru and serve its Prism mock until Ctrl-C.

    With ``--stateful`` a `StatefulStubServer` proxy is layered in front of
    Prism (Prism takes an ephemeral port; the proxy takes the requested
    one) so writes are remembered across reads. The whole stack is one
    `ApiMockStack` — the CLI only prints the banner and waits.
    """

    def banner(stack: ApiMockStack) -> list[str]:
        lines = [f"SimWork API mock running: {args.api} (spec: {stack.spec_path})"]
        if args.stateful:
            lines.append("Stateful stubs on: writes are remembered (create-then-read works).")
        lines.append(f"API_BASE_URL={stack.base_url}")
        return lines

    try:
        serve(
            ApiMockStack(
                args.api,
                host=args.host,
                port=args.port,
                cache_dir=args.cache_dir,
                stateful=args.stateful,
            ),
            banner=banner,
            stopping="Stopping API mock.",
        )
    except ApiMockError as e:
        print(f"simwork mock: error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    """Evaluate a recorded trace; exit 0 on pass, 1 on fail (or bad trace).

    With --judge, readiness (deepeval installed, key set, budget covers
    the work) is checked before the native gate runs, so a judge that
    cannot run fails fast instead of printing a partial report.
    """
    include = tuple(name.strip() for name in (args.judge_metrics or "").split(",") if name.strip())
    if args.judge:
        try:
            check_judge_ready(max_llm_calls=args.judge_max_calls, include=include)
        except JudgeError as e:
            print(f"simwork eval: error: {e}", file=sys.stderr)
            return 1
    try:
        file_config = load_file_config(args.config)
    except ConfigError as e:
        print(f"simwork eval: error: {e}", file=sys.stderr)
        return 1
    trace_path, report_path = resolve_eval(file_config, trace=args.trace, report=args.report)
    if trace_path is None:
        print(
            "simwork eval: error: no trace given (--trace) and no eval.trace in simwork.yaml",
            file=sys.stderr,
        )
        return 1
    try:
        trace = load_trace(trace_path)
        if args.judge:
            report = evaluate_run_with_judge(
                trace,
                model=args.judge_model,
                max_llm_calls=args.judge_max_calls,
                include=include,
            )
        else:
            report = evaluate_run(trace)
    except TraceError as e:
        print(f"simwork eval: error: {e}", file=sys.stderr)
        return 1
    except JudgeError as e:
        print(f"simwork eval: error: {e}", file=sys.stderr)
        return 1
    print(report.to_text(), end="")
    if report_path:
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report.to_json())
        except OSError as e:
            print(f"simwork eval: error: cannot write report: {e}", file=sys.stderr)
            return 1
        print(f"Report written to {report_path}")
    return 0 if report.passed else 1


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold the starter; print the files created and the next steps."""
    try:
        created = init_project(args.directory, force=args.force)
    except InitError as e:
        print(f"simwork init: error: {e}", file=sys.stderr)
        return 1
    print("SimWork starter created:")
    for path in created:
        print(f"  {path}")
    print("Next steps:")
    print("  # hand prompts/configure-simwork.md to your AI assistant to wire")
    print("  # SimWork into your harness, or follow the starter README:")
    print("  simwork serve --scenario scenarios/ticket-status.yaml")
    print("  pytest")
    print("  simwork eval --trace evals/ticket-status-trace.json")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Run the LangGraph demo; print the report; exit on the gate."""
    try:
        trace, report = run_demo()
    except DemoError as e:
        print(f"simwork demo: error: {e}", file=sys.stderr)
        return 1
    print(report.to_text(), end="")
    print(f"Trace hash: {trace_hash(trace)}")
    if args.trace:
        try:
            with open(args.trace, "w", encoding="utf-8") as f:
                json.dump(trace, f, indent=2, sort_keys=True)
                f.write("\n")
        except OSError as e:
            print(f"simwork demo: error: cannot write trace: {e}", file=sys.stderr)
            return 1
        print(f"Trace written to {args.trace}")
    if args.report:
        try:
            with open(args.report, "w", encoding="utf-8") as f:
                f.write(report.to_json())
        except OSError as e:
            print(f"simwork demo: error: cannot write report: {e}", file=sys.stderr)
            return 1
        print(f"Report written to {args.report}")
    return 0 if report.passed else 1


def cmd_scale(args: argparse.Namespace) -> int:
    """Repeat the demo; print the batch summary; exit on the verdict."""
    print(f"Running the demo {args.runs} time(s) against shared mocks ($0)…")
    try:
        report = run_scale(runs=args.runs)
    except ScaleError as e:
        print(f"simwork scale: error: {e}", file=sys.stderr)
        return 1
    print(report.to_text(), end="")
    if args.report:
        try:
            with open(args.report, "w", encoding="utf-8") as f:
                f.write(report.to_json())
        except OSError as e:
            print(f"simwork scale: error: cannot write report: {e}", file=sys.stderr)
            return 1
        print(f"Report written to {args.report}")
    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "mock":
        return cmd_mock(args)
    if args.command == "eval":
        return cmd_eval(args)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "demo":
        return cmd_demo(args)
    if args.command == "scale":
        return cmd_scale(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
