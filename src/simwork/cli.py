"""Command-line entry point for SimWork.

Phase 1: `serve` starts the fake OpenAI server from a scenario file so
an unmodified harness can point at it with a base-URL swap. `mock`
(Phase 2) and `eval` (Phase 3) are wired — `eval --judge` adds the
opt-in DeepEval judge path; `init` lands in Phase 4, per the spec.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading

from simwork import __version__
from simwork.api_mock import ApiMockError, ApiMockStack
from simwork.deepeval_judge import JudgeError, check_judge_ready, evaluate_run_with_judge
from simwork.eval import evaluate_run
from simwork.trace import TraceError, load_trace
from simwork.init import InitError, init_project
from simwork.llm import ScenarioError
from simwork.routing import RoutingError, SimWorkRouter, load_config


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
        required=True,
        help="JSON trace file of a recorded run",
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
            "README. The generated scenario parses and the trace passes the "
            "$0 eval gate before anything is written. Existing files owned "
            "by init are only overwritten with --force; other files in the "
            "directory are never touched."
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
    return parser


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the fake server from a scenario; block until Ctrl-C."""
    try:
        env = dict(os.environ)
        # `serve` is inherently simulate mode; flags override env vars.
        env["SIMWORK_MODE"] = "simulate"
        if args.scenario:
            env["SIMWORK_SCENARIO"] = args.scenario
        if args.host:
            env["SIMWORK_HOST"] = args.host
        if args.port is not None:
            env["SIMWORK_PORT"] = str(args.port)
        config = load_config(env)
    except (RoutingError, ValueError) as e:
        print(f"simwork serve: error: {e}", file=sys.stderr)
        return 1
    try:
        router = SimWorkRouter(config)
        router.__enter__()
    except ScenarioError as e:
        print(f"simwork serve: error: {e}", file=sys.stderr)
        return 1
    assert router.base_url is not None
    print(f"SimWork fake OpenAI server running (scenario: {config.scenario_path})", flush=True)
    for key, value in router.env_overrides.items():
        print(f"{key}={value}", flush=True)
    print("Press Ctrl-C to stop.", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nStopping fake OpenAI server.")
    finally:
        router.stop()
    return 0


def cmd_mock(args: argparse.Namespace) -> int:
    """Fetch an API spec from APIs.guru and serve its Prism mock until Ctrl-C.

    With ``--stateful`` a `StatefulStubServer` proxy is layered in front of
    Prism (Prism takes an ephemeral port; the proxy takes the requested
    one) so writes are remembered across reads. The whole stack is one
    `ApiMockStack` — the CLI only prints the banner and waits.
    """
    stack = ApiMockStack(
        args.api,
        host=args.host,
        port=args.port,
        cache_dir=args.cache_dir,
        stateful=args.stateful,
    )
    try:
        with stack:
            print(f"SimWork API mock running: {args.api} (spec: {stack.spec_path})", flush=True)
            if args.stateful:
                print(
                    "Stateful stubs on: writes are remembered (create-then-read works).",
                    flush=True,
                )
            print(f"API_BASE_URL={stack.base_url}", flush=True)
            print("Press Ctrl-C to stop.", flush=True)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                print("\nStopping API mock.")
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
        trace = load_trace(args.trace)
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
    if args.report:
        try:
            with open(args.report, "w", encoding="utf-8") as f:
                f.write(report.to_json())
        except OSError as e:
            print(f"simwork eval: error: cannot write report: {e}", file=sys.stderr)
            return 1
        print(f"Report written to {args.report}")
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
    print("  simwork serve --scenario scenarios/ticket-status.yaml")
    print("  pytest")
    print("  simwork eval --trace evals/ticket-status-trace.json")
    return 0


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
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
