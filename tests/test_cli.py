"""CLI smoke tests for the SimWork foundation (Phase 0)."""

import subprocess
import sys


def test_cli_help_exits_zero_and_names_simwork():
    result = subprocess.run(
        [sys.executable, "-m", "simwork.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "SimWork" in result.stdout


def test_cli_version_reports_package_version():
    from simwork import __version__

    result = subprocess.run(
        [sys.executable, "-m", "simwork.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout
