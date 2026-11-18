"""Tests for the pre-made AI configuration prompt (Phase 4, task 2).

The prompt is the file an AI assistant follows to configure SimWork
for a new app without the user hand-writing config (spec §4). It lives
as one source of truth in `simwork.prompt` and ships twice: as
`prompts/configure-simwork.md` in this repo, and as a file generated
by `simwork init` into every starter.
"""

from pathlib import Path

from simwork.prompt import CONFIGURE_SIMWORK_PROMPT

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_PROMPT = REPO_ROOT / "prompts" / "configure-simwork.md"


def test_prompt_is_nonempty_markdown():
    assert len(CONFIGURE_SIMWORK_PROMPT) > 2000
    assert CONFIGURE_SIMWORK_PROMPT.startswith("# ")
    assert "## " in CONFIGURE_SIMWORK_PROMPT


def test_prompt_names_the_routing_surface():
    """An AI following the prompt must find the exact env vars + commands."""
    for token in (
        "SIMWORK_MODE=simulate",
        "SIMWORK_SCENARIO",
        "simwork serve",
        "simwork mock",
        "simwork eval",
        "simwork init",
        "OPENAI_BASE_URL",
    ):
        assert token in CONFIGURE_SIMWORK_PROMPT, token


def test_prompt_teaches_the_workflow_steps():
    for token in (
        "scenario",
        "TraceRecorder",
        "tool correctness",
        "task completion",
    ):
        assert token in CONFIGURE_SIMWORK_PROMPT, token


def test_prompt_states_the_hard_gates():
    """$0 default, no real calls, fail-closed, no secrets — the gates
    an AI must never talk its way around (spec §4–§5)."""
    lowered = CONFIGURE_SIMWORK_PROMPT.lower()
    assert "$0" in CONFIGURE_SIMWORK_PROMPT
    assert "no real" in lowered
    assert "fail closed" in lowered
    assert "no secrets" in lowered or "no real api keys" in lowered
    assert "do not rewrite" in lowered or "without rewriting" in lowered


def test_prompt_covers_scale_and_realism():
    """The Polygrow first use case (spec S16): thousands of runs at $0,
    scenario families for variation, realism via fidelity + calibration."""
    lowered = CONFIGURE_SIMWORK_PROMPT.lower()
    assert "scenario famil" in lowered
    assert "thousand" in lowered
    assert "calibrat" in lowered
    assert "deterministic" in lowered


def test_prompt_has_a_verification_checklist():
    lowered = CONFIGURE_SIMWORK_PROMPT.lower()
    assert "checklist" in lowered or "verify" in lowered
    assert "trace hash" in lowered or "same seed" in lowered


def test_repo_prompt_file_matches_the_module_constant():
    """The repo copy must never drift from the single source of truth."""
    assert REPO_PROMPT.is_file()
    assert REPO_PROMPT.read_text(encoding="utf-8") == CONFIGURE_SIMWORK_PROMPT


def test_repo_prompt_ends_with_newline():
    assert CONFIGURE_SIMWORK_PROMPT.endswith("\n")
