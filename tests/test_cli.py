"""CLI smoke tests for the SimWork foundation (Phase 0)."""

import json
import subprocess
import sys
import time
import urllib.request

from simwork.cli import main

SCENARIO_YAML = """\
name: ticket-status
seed: 7
turns:
  - content: "I will check the ticket."
"""


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


def test_serve_without_scenario_fails_closed(monkeypatch, capsys):
    monkeypatch.delenv("SIMWORK_SCENARIO", raising=False)
    assert main(["serve"]) == 1
    assert "SIMWORK_SCENARIO" in capsys.readouterr().err


def test_serve_with_missing_scenario_fails_closed(tmp_path, capsys):
    assert main(["serve", "--scenario", str(tmp_path / "nope.yaml")]) == 1
    assert "cannot read scenario" in capsys.readouterr().err


def test_serve_end_to_end(tmp_path):
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(SCENARIO_YAML, encoding="utf-8")
    port = 18765
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "simwork.cli",
            "serve",
            "--scenario",
            str(scenario),
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}/v1"
        deadline = time.time() + 15
        reply = None
        while time.time() < deadline:
            try:
                req = urllib.request.Request(
                    f"{base_url}/chat/completions",
                    data=json.dumps(
                        {
                            "model": "simwork-mock",
                            "messages": [{"role": "user", "content": "hi"}],
                        }
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=2) as resp:
                    reply = json.loads(resp.read())
                break
            except Exception:
                time.sleep(0.2)
        assert reply is not None, "fake server did not answer in time"
        assert reply["choices"][0]["message"]["content"] == "I will check the ticket."
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    assert f"OPENAI_BASE_URL={base_url}" in proc.stdout.read()
