"""Tests for the `simwork.yaml` config-file loader (adoption, readiness 1).

The loader is the missing piece the starter already assumes: `simwork
init` writes `simwork.yaml`, and now `simwork serve` / `simwork eval`
read it. Precedence is CLI flags > environment variables > config
file > defaults; relative paths in the file resolve against the file's
own directory, not the caller's cwd. Anything malformed fails closed
with `ConfigError` instead of silently running with wrong settings.
"""

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from simwork.config import (
    ConfigError,
    SimWorkFileConfig,
    find_config_file,
    load_config_file,
    parse_config_text,
    resolve_config,
    resolve_eval,
)
from simwork.init import init_project
from simwork.routing import RoutingError, SimWorkConfig

PASS_TRACE = {
    "run_id": "ticket-status-1",
    "seed": 7,
    "steps": [
        {"type": "assistant", "content": "I will check the ticket."},
        {
            "type": "assistant",
            "tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}],
        },
        {"type": "tool_result", "name": "lookup_ticket", "result": {"status": "shipped"}},
        {"type": "assistant", "content": "Your replacement has shipped."},
    ],
    "expected": {
        "tool_calls": [{"name": "lookup_ticket", "arguments": {"ticket_id": "T-123"}}],
        "final_answer_contains": ["shipped"],
    },
}

FAIL_TRACE = {
    **PASS_TRACE,
    "steps": [
        {"type": "assistant", "content": "I will check the ticket."},
        {"type": "assistant", "content": "Nothing to report."},
    ],
}

SCENARIO_YAML = """\
name: ticket-status
seed: 7
turns:
  - content: "I will check the ticket."
"""


def _write_config(tmp_path: Path, text: str, name: str = "simwork.yaml") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- parsing --------------------------------------------------------------


def test_parse_full_config_resolves_relative_paths(tmp_path):
    config = parse_config_text(
        """\
mode: simulate
scenario: scenarios/ticket-status.yaml
seed: 7
host: 127.0.0.1
port: 8123
eval:
  trace: evals/ticket-status-trace.json
  report: evals/report.json
""",
        base_dir=tmp_path,
        source="simwork.yaml",
    )
    assert config == SimWorkFileConfig(
        mode="simulate",
        scenario=tmp_path / "scenarios" / "ticket-status.yaml",
        seed=7,
        host="127.0.0.1",
        port=8123,
        eval_trace=tmp_path / "evals" / "ticket-status-trace.json",
        eval_report=tmp_path / "evals" / "report.json",
        source=Path("simwork.yaml"),
    )


def test_parse_empty_config_is_live_defaults(tmp_path):
    assert parse_config_text("", base_dir=tmp_path, source="simwork.yaml") == SimWorkFileConfig(
        source=Path("simwork.yaml")
    )
    assert (
        parse_config_text("# only a comment\n", base_dir=tmp_path, source="simwork.yaml").mode
        == "live"
    )


def test_parse_mode_is_case_insensitive(tmp_path):
    config = parse_config_text("mode: Simulate\n", base_dir=tmp_path, source="simwork.yaml")
    assert config.mode == "simulate"


def test_parse_absolute_paths_are_kept(tmp_path):
    config = parse_config_text(
        "scenario: /abs/scenario.yaml\n", base_dir=tmp_path, source="simwork.yaml"
    )
    assert config.scenario == Path("/abs/scenario.yaml")


@pytest.mark.parametrize(
    "text",
    [
        "mode: sideways\n",
        "mode: 7\n",
        "seed: fast\n",
        "seed: -1\n",
        "seed: true\n",
        "host: 7\n",
        "port: 70000\n",
        "port: -1\n",
        "port: many\n",
        "port: true\n",
        "scenario: 7\n",
        "scenario: ''\n",
        "eval: just-a-string\n",
        "eval:\n  trace: 7\n",
        "eval:\n  unknown_key: x\n",
        "unknown_key: x\n",
        "- a\n- list\n",
        "just a string\n",
    ],
)
def test_parse_invalid_config_fails_closed(tmp_path, text):
    with pytest.raises(ConfigError):
        parse_config_text(text, base_dir=tmp_path, source="simwork.yaml")


def test_parse_malformed_yaml_fails_closed(tmp_path):
    with pytest.raises(ConfigError, match="simwork.yaml"):
        parse_config_text("mode: [unclosed\n", base_dir=tmp_path, source="simwork.yaml")


def test_load_config_file_missing_raises(tmp_path):
    with pytest.raises(ConfigError, match="nope.yaml"):
        load_config_file(tmp_path / "nope.yaml")


def test_generated_starter_config_loads(tmp_path):
    init_project(tmp_path, force=False)
    config = load_config_file(tmp_path / "simwork.yaml")
    assert config.mode == "simulate"
    assert config.scenario == tmp_path / "scenarios" / "ticket-status.yaml"
    assert config.seed == 7
    assert config.eval_trace == tmp_path / "evals" / "ticket-status-trace.json"
    assert config.eval_report == tmp_path / "evals" / "report.json"


# --- discovery ------------------------------------------------------------


def test_find_config_file_in_cwd(tmp_path, monkeypatch):
    _write_config(tmp_path, "mode: live\n")
    monkeypatch.chdir(tmp_path)
    assert find_config_file() == tmp_path / "simwork.yaml"


def test_find_config_file_walks_up(tmp_path, monkeypatch):
    _write_config(tmp_path, "mode: live\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert find_config_file() == tmp_path / "simwork.yaml"


def test_find_config_file_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert find_config_file() is None


def test_find_config_file_explicit_path(tmp_path):
    path = _write_config(tmp_path, "mode: live\n", name="custom.yaml")
    assert find_config_file(explicit=path) == path


# --- merging / precedence -------------------------------------------------


def _file_config(tmp_path: Path) -> SimWorkFileConfig:
    return parse_config_text(
        "mode: simulate\nscenario: scenarios/s.yaml\nhost: 127.0.0.2\nport: 8001\nseed: 3\n",
        base_dir=tmp_path,
        source="simwork.yaml",
    )


def test_resolve_config_file_only(tmp_path):
    config = resolve_config(_file_config(tmp_path), env={})
    assert config == SimWorkConfig(
        mode="simulate",
        scenario_path=tmp_path / "scenarios" / "s.yaml",
        host="127.0.0.2",
        port=8001,
    )


def test_resolve_config_env_overrides_file(tmp_path):
    config = resolve_config(
        _file_config(tmp_path),
        env={"SIMWORK_PORT": "8002", "SIMWORK_SCENARIO": "/env/s.yaml"},
    )
    assert config.port == 8002
    assert config.scenario_path == Path("/env/s.yaml")
    assert config.host == "127.0.0.2"  # untouched by env, stays from file


def test_resolve_config_cli_overrides_env_and_file(tmp_path):
    config = resolve_config(
        _file_config(tmp_path),
        env={"SIMWORK_PORT": "8002"},
        scenario="/cli/s.yaml",
        host="127.0.0.3",
        port=8003,
    )
    assert config == SimWorkConfig(
        mode="simulate",
        scenario_path=Path("/cli/s.yaml"),
        host="127.0.0.3",
        port=8003,
    )


def test_resolve_config_no_file_no_env_is_live_defaults():
    assert resolve_config(None, env={}) == SimWorkConfig()


def test_resolve_config_simulate_without_scenario_fails_closed(tmp_path):
    file_config = parse_config_text("mode: simulate\n", base_dir=tmp_path, source="simwork.yaml")
    with pytest.raises(RoutingError, match="SIMWORK_SCENARIO"):
        resolve_config(file_config, env={})


def test_resolve_eval_prefers_flags_over_file(tmp_path):
    file_config = parse_config_text(
        "eval:\n  trace: evals/a.json\n  report: evals/r.json\n",
        base_dir=tmp_path,
        source="simwork.yaml",
    )
    trace, report = resolve_eval(file_config)
    assert trace == tmp_path / "evals" / "a.json"
    assert report == tmp_path / "evals" / "r.json"
    trace, report = resolve_eval(file_config, trace="/flag/t.json", report="/flag/r.json")
    assert trace == Path("/flag/t.json")
    assert report == Path("/flag/r.json")
    assert resolve_eval(None) == (None, None)


# --- CLI: eval reads the config -------------------------------------------


def _write_trace(path: Path, trace: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace), encoding="utf-8")
    return path


def test_cli_eval_reads_trace_from_config(tmp_path, monkeypatch, capsys):
    from simwork.cli import main

    _write_trace(tmp_path / "evals" / "t.json", PASS_TRACE)
    _write_config(tmp_path, "eval:\n  trace: evals/t.json\n  report: evals/report.json\n")
    monkeypatch.chdir(tmp_path)
    assert main(["eval"]) == 0
    assert "PASS" in capsys.readouterr().out
    assert (tmp_path / "evals" / "report.json").is_file()


def test_cli_eval_flag_overrides_config_trace(tmp_path, monkeypatch, capsys):
    from simwork.cli import main

    _write_trace(tmp_path / "evals" / "bad.json", FAIL_TRACE)
    good = _write_trace(tmp_path / "good.json", PASS_TRACE)
    _write_config(tmp_path, "eval:\n  trace: evals/bad.json\n")
    monkeypatch.chdir(tmp_path)
    assert main(["eval", "--trace", str(good)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_eval_without_trace_anywhere_fails_closed(tmp_path, monkeypatch, capsys):
    from simwork.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["eval"]) == 1
    assert "no trace" in capsys.readouterr().err


def test_cli_eval_explicit_missing_config_fails_closed(tmp_path, capsys):
    from simwork.cli import main

    assert main(["eval", "--config", str(tmp_path / "nope.yaml")]) == 1
    assert "nope.yaml" in capsys.readouterr().err


# --- CLI: serve reads the config ------------------------------------------


def test_cli_serve_explicit_missing_config_fails_closed(tmp_path, capsys):
    from simwork.cli import main

    assert main(["serve", "--config", str(tmp_path / "nope.yaml")]) == 1
    assert "nope.yaml" in capsys.readouterr().err


def test_cli_serve_from_config_file_end_to_end(tmp_path, monkeypatch):
    from simwork.cli import main  # noqa: F401  (main is exercised via subprocess)

    scenario = tmp_path / "scenarios" / "s.yaml"
    scenario.parent.mkdir(parents=True)
    scenario.write_text(SCENARIO_YAML, encoding="utf-8")
    _write_config(tmp_path, "mode: simulate\nscenario: scenarios/s.yaml\nport: 18766\n")
    proc = subprocess.Popen(
        [sys.executable, "-m", "simwork.cli", "serve", "--config", str(tmp_path / "simwork.yaml")],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=tmp_path,
    )
    try:
        base_url = "http://127.0.0.1:18766/v1"
        deadline = time.time() + 15
        reply = None
        while time.time() < deadline:
            try:
                req = urllib.request.Request(
                    f"{base_url}/chat/completions",
                    data=json.dumps(
                        {"model": "simwork-mock", "messages": [{"role": "user", "content": "hi"}]}
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
