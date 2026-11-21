"""Tests for the multi-tool-agent recipe (adoption plan v0.2 §3 step 2,
recipe 3 of 3).

The recipe is a self-contained runnable example under
`examples/recipes/multi-tool-agent/`: a `simwork.yaml` config, a YAML
scenario, a Prism-served travel API mock (bundled spec with flights +
hotels operations), a recorded trace, its own pytest suite, and
`run.py` — a raw-HTTP agent loop against the fake OpenAI server (the
plain-OpenAI-client pattern, no LangGraph). The live end-to-end tests
need `httpx` (demo group) and the `prism` binary, so they skip when
either is missing and CI stays green offline; the static tests
(scenario/config/trace parse + gate + chain) run everywhere.
"""

from __future__ import annotations

import importlib.util
import shutil
import socket
import sys
from pathlib import Path

import pytest

from simwork.config import parse_config_text
from simwork.eval import evaluate_run
from simwork.llm import load_scenario
from simwork.trace import final_answer, load_trace, tool_calls, trace_hash

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPE = REPO_ROOT / "examples" / "recipes" / "multi-tool-agent"
RUN_PY = RECIPE / "run.py"
README = REPO_ROOT / "README.md"
DOCS_PAGE = REPO_ROOT / "docs-site" / "src" / "content" / "docs" / "guides" / "recipes.md"
ASTRO_CONFIG = REPO_ROOT / "docs-site" / "astro.config.mjs"


@pytest.fixture(scope="module")
def recipe_trace():
    return load_trace(RECIPE / "evals" / "multi-tool-agent-trace.json")


def test_recipe_scenario_parses():
    scenario = load_scenario(RECIPE / "scenarios" / "multi-tool-agent.yaml")
    assert scenario.name == "multi-tool-agent"
    assert scenario.seed == 21
    assert len(scenario.turns) == 3


def test_recipe_config_parses():
    config = parse_config_text(
        (RECIPE / "simwork.yaml").read_text(encoding="utf-8"),
        base_dir=RECIPE,
        source="simwork.yaml",
    )
    assert config.mode == "simulate"
    assert config.scenario is not None
    assert config.scenario.name == "multi-tool-agent.yaml"
    assert config.seed == 21


def test_recipe_trace_passes_gate(recipe_trace):
    report = evaluate_run(recipe_trace)
    assert report.passed, report.to_text()


def test_recipe_chain_is_derived_from_tool_results(recipe_trace):
    calls = tool_calls(recipe_trace)
    assert [c["name"] for c in calls] == ["search_flights", "search_hotels"]
    results = {s["name"]: s["result"] for s in recipe_trace["steps"] if s["type"] == "tool_result"}
    assert set(results) == {"search_flights", "search_hotels"}
    flights = results["search_flights"]["flights"]
    cheapest = min(flights, key=lambda f: f["price_usd"])
    hotel_call = calls[1]
    assert hotel_call["arguments"]["city"] == cheapest["destination_city"]
    assert hotel_call["arguments"]["checkin"] == cheapest["arrival_date"]
    hotel = results["search_hotels"]["hotels"][0]
    total = cheapest["price_usd"] + hotel["price_per_night_usd"] * hotel_call["arguments"]["nights"]
    answer = final_answer(recipe_trace)
    assert f"${total:.0f}" in answer


def _load_run_recipe():
    spec = importlib.util.spec_from_file_location("multi_tool_agent_run", RUN_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["multi_tool_agent_run"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def run_recipe_module():
    pytest.importorskip("httpx")
    if shutil.which("prism") is None:
        pytest.skip("prism not installed (npm i -g @stoplight/prism-cli)")
    return _load_run_recipe()


def test_recipe_runs_end_to_end_and_passes_gate(run_recipe_module):
    trace, report = run_recipe_module.run_recipe()
    assert report.passed, report.to_text()
    assert trace["run_id"] == "multi-tool-agent-1"
    assert trace["seed"] == 21
    # The recorded trace file is the trace of this same run.
    assert trace == load_trace(RECIPE / "evals" / "multi-tool-agent-trace.json")


def test_recipe_is_deterministic(run_recipe_module):
    trace1, _ = run_recipe_module.run_recipe()
    trace2, _ = run_recipe_module.run_recipe()
    assert trace_hash(trace1) == trace_hash(trace2)


def test_recipe_makes_no_real_network_calls(run_recipe_module, monkeypatch):
    """The recipe talks only to localhost mocks — any other host fails."""
    orig_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"recipe tried a non-local connection to {address!r}")
        return orig_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    trace, report = run_recipe_module.run_recipe()
    assert report.passed, report.to_text()


def test_readme_lists_the_multi_tool_recipe():
    readme = README.read_text(encoding="utf-8")
    assert "multi-tool-agent" in readme
    assert "Multi-tool agent" in readme


def test_docs_site_recipes_page_mentions_the_recipe():
    assert DOCS_PAGE.is_file()
    page = DOCS_PAGE.read_text(encoding="utf-8")
    assert "multi-tool-agent" in page
    config = ASTRO_CONFIG.read_text(encoding="utf-8")
    assert "guides/recipes" in config
