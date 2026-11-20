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


FAMILY_YAML = """\
name: ticket-status-family
seed: 7
parameters:
  ticket_id: ["T-101"]
  status: ["shipped"]
turns:
  - content: "Ticket {{ticket_id}} has {{status}}."
"""


def _serve_and_ask(args, port):
    proc = subprocess.Popen(
        [sys.executable, "-m", "simwork.cli", *args, "--port", str(port)],
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
        return reply, proc
    except Exception:
        proc.terminate()
        proc.wait(timeout=10)
        raise


def test_serve_family_member_end_to_end(tmp_path):
    family = tmp_path / "family.yaml"
    family.write_text(FAMILY_YAML, encoding="utf-8")
    proc = None
    try:
        reply, proc = _serve_and_ask(["serve", "--family", str(family), "--member", "0"], 18766)
        assert reply["choices"][0]["message"]["content"] == "Ticket T-101 has shipped."
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
            assert "ticket-status-family" in proc.stdout.read()


def test_serve_family_and_scenario_are_mutually_exclusive(tmp_path, capsys):
    family = tmp_path / "family.yaml"
    family.write_text(FAMILY_YAML, encoding="utf-8")
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(SCENARIO_YAML, encoding="utf-8")
    assert main(["serve", "--family", str(family), "--scenario", str(scenario)]) == 1
    assert "mutually exclusive" in capsys.readouterr().err


def test_serve_member_without_family_fails_closed(capsys):
    assert main(["serve", "--member", "2"]) == 1
    assert "--member needs --family" in capsys.readouterr().err


def test_serve_family_missing_file_fails_closed(tmp_path, capsys):
    assert main(["serve", "--family", str(tmp_path / "nope.yaml")]) == 1
    assert "cannot read family file" in capsys.readouterr().err


def test_serve_family_negative_member_fails_closed(tmp_path, capsys):
    family = tmp_path / "family.yaml"
    family.write_text(FAMILY_YAML, encoding="utf-8")
    assert main(["serve", "--family", str(family), "--member", "-1"]) == 1
    assert "non-negative" in capsys.readouterr().err
