"""Command-line entry point for SimWork.

Phase 1: `serve` starts the fake OpenAI server from a scenario file so
an unmodified harness can point at it with a base-URL swap. `mock`
(Phase 2) and `eval` (Phase 3, first slice) are wired; `init` lands in
Phase 4, per the spec.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading

from simwork import __version__
from simwork.api_mock import ApiMockError, PrismMockServer, fetch_api_spec
from simwork.eval import TraceError, evaluate_run, load_trace
from simwork.llm import ScenarioError
from simwork.routing import RoutingError, SimWorkRouter, load_config
from simwork.stateful import StatefulStubServer


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
        help="evaluate a recorded run trace (DeepEval harness, first slice)",
        description=(
            "Evaluate a recorded run trace (JSON, see examples/) with the "
            "deterministic metrics tool correctness + task completion and "
            "print a pass/fail report. Exits 0 when the gate passes, 1 when "
            "it fails. $0 — no LLM judge, no network."
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
    one) so writes are remembered across reads.
    """
    try:
        spec_path = fetch_api_spec(args.api, args.cache_dir)
    except ApiMockError as e:
        print(f"simwork mock: error: {e}", file=sys.stderr)
        return 1
    try:
        prism = PrismMockServer(
            spec_path,
            host=args.host,
            port=0 if args.stateful else args.port,
        )
        prism.start()
        proxy = None
        if args.stateful:
            proxy = StatefulStubServer(prism.base_url, host=args.host, port=args.port)
            proxy.start()
    except ApiMockError as e:
        print(f"simwork mock: error: {e}", file=sys.stderr)
        return 1
    serving = proxy if proxy is not None else prism
    print(f"SimWork API mock running: {args.api} (spec: {spec_path})", flush=True)
    if proxy is not None:
        print("Stateful stubs on: writes are remembered (create-then-read works).", flush=True)
    print(f"API_BASE_URL={serving.base_url}", flush=True)
    print("Press Ctrl-C to stop.", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nStopping API mock.")
    finally:
        if proxy is not None:
            proxy.stop()
        prism.stop()
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    """Evaluate a recorded trace; exit 0 on pass, 1 on fail (or bad trace)."""
    try:
        trace = load_trace(args.trace)
        report = evaluate_run(trace)
    except TraceError as e:
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "mock":
        return cmd_mock(args)
    if args.command == "eval":
        return cmd_eval(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
