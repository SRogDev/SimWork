"""Tests for `simwork init` (Phase 4, task 1).

`init` scaffolds a working starter in a fresh (or existing) directory:
a `simwork.yaml` config, a YAML scenario, an eval suite (a recorded
trace + a pytest file that gates on it), and a starter README. The
generated files must be valid on their own: the scenario parses and
the trace passes the $0 eval gate.
"""

import json
import subprocess
import sys

import pytest

from simwork import evaluate_run, load_trace
from simwork.cli import main
from simwork.init import InitError, init_project
from simwork.llm import load_scenario

# Files `init` owns, relative to the target directory.
OWNED_FILES = (
    "simwork.yaml",
    "scenarios/ticket-status.yaml",
    "evals/ticket-status-trace.json",
    "tests/test_simwork_eval.py",
    "README.md",
    "prompts/configure-simwork.md",
)


def test_init_creates_all_owned_files(tmp_path):
    created = init_project(tmp_path)
    assert sorted(str(p.relative_to(tmp_path)) for p in created) == sorted(OWNED_FILES)
    for rel in OWNED_FILES:
        assert (tmp_path / rel).is_file()


def test_init_generated_scenario_parses_and_matches_trace(tmp_path):
    init_project(tmp_path)
    scenario = load_scenario(tmp_path / "scenarios" / "ticket-status.yaml")
    assert scenario.seed == 7
    assert len(scenario.turns) == 3
    assert scenario.turns[1]["tool_calls"][0]["name"] == "lookup_ticket"
    trace = load_trace(tmp_path / "evals" / "ticket-status-trace.json")
    assert trace["seed"] == scenario.seed
    assert evaluate_run(trace).passed


def test_init_generated_eval_suite_passes(tmp_path):
    """The generated pytest file must actually run and pass (subprocess)."""
    init_project(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(tmp_path / "tests")],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_init_config_points_at_generated_files(tmp_path):
    init_project(tmp_path)
    config = (tmp_path / "simwork.yaml").read_text(encoding="utf-8")
    assert "scenarios/ticket-status.yaml" in config
    assert "evals/ticket-status-trace.json" in config
    assert "simulate" in config


def test_init_readme_names_the_next_commands(tmp_path):
    init_project(tmp_path)
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "simwork serve" in readme
    assert "simwork eval" in readme
    assert "pytest" in readme


def test_init_into_existing_project_dir_keeps_user_files(tmp_path):
    """Init must work inside a non-empty project dir (the real use case:
    adding SimWork to an existing harness) without touching other files."""
    (tmp_path / "app.py").write_text("print('my harness')\n", encoding="utf-8")
    init_project(tmp_path)
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "print('my harness')\n"
    assert (tmp_path / "simwork.yaml").is_file()


def test_init_refuses_to_overwrite_owned_files_without_force(tmp_path):
    init_project(tmp_path)
    with pytest.raises(InitError, match="already exist"):
        init_project(tmp_path)
    # Nothing was clobbered: the trace still evaluates.
    assert evaluate_run(load_trace(tmp_path / "evals" / "ticket-status-trace.json")).passed


def test_init_force_overwrites_owned_files(tmp_path):
    init_project(tmp_path)
    (tmp_path / "simwork.yaml").write_text("custom: true\n", encoding="utf-8")
    init_project(tmp_path, force=True)
    assert "scenarios/ticket-status.yaml" in (tmp_path / "simwork.yaml").read_text(encoding="utf-8")


def test_init_creates_missing_target_dir(tmp_path):
    target = tmp_path / "new-project"
    init_project(target)
    assert (target / "simwork.yaml").is_file()


def test_init_rejects_a_file_as_target(tmp_path):
    target = tmp_path / "not-a-dir"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(InitError, match="not a directory"):
        init_project(target)


def test_cli_init_exits_zero_and_lists_files(tmp_path, capsys):
    assert main(["init", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "simwork.yaml" in out
    assert "Next steps" in out


def test_cli_init_defaults_to_current_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert (tmp_path / "simwork.yaml").is_file()


def test_cli_init_collision_exits_one(tmp_path, capsys):
    assert main(["init", str(tmp_path)]) == 0
    assert main(["init", str(tmp_path)]) == 1
    assert "already exist" in capsys.readouterr().err


def test_cli_init_help_mentions_init():
    result = subprocess.run(
        [sys.executable, "-m", "simwork.cli", "init", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "simwork.yaml" in result.stdout


def test_init_generated_prompt_matches_repo_prompt(tmp_path):
    """The starter's prompt must be the repo's pre-made prompt, verbatim."""
    from simwork.prompt import CONFIGURE_SIMWORK_PROMPT

    init_project(tmp_path)
    generated = (tmp_path / "prompts" / "configure-simwork.md").read_text(encoding="utf-8")
    assert generated == CONFIGURE_SIMWORK_PROMPT


def test_init_readme_points_at_the_prompt(tmp_path):
    init_project(tmp_path)
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "prompts/configure-simwork.md" in readme


def test_generated_trace_is_the_example_trace(tmp_path):
    """The generated trace must be the repo's own example trace (same hash)."""
    from pathlib import Path

    init_project(tmp_path)
    generated = json.loads(
        (tmp_path / "evals" / "ticket-status-trace.json").read_text(encoding="utf-8")
    )
    example_path = Path(__file__).resolve().parents[1] / "examples" / "ticket-status-trace.json"
    example = json.loads(example_path.read_text(encoding="utf-8"))
    assert generated == example
