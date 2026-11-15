"""Command-line entry point for SimWork.

Phase 0 foundation: `--help` and `--version` only. Subcommands
(`init`, `mock`, `eval`) land in later phases, per the spec.
"""

import argparse
import sys

from simwork import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simwork",
        description=(
            "SimWork — simulate AI-app functionality first, before spending "
            "real LLM or world API calls. Every simulated run costs $0 by default."
        ),
    )
    parser.add_argument("--version", action="version", version=f"simwork {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
