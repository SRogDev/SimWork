"""Command-line entry point for SimWork.

Phase 1: `serve` starts the fake OpenAI server from a scenario file so
an unmodified harness can point at it with a base-URL swap. Subcommands
(`init`, `mock`, `eval`) land in later phases, per the spec.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading

from simwork import __version__
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return cmd_serve(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
