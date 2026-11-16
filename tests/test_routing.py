"""Tests for routing (Phase 1, task 3).

Routing wires `SIMWORK_MODE` + a scenario file to the fake OpenAI
server: in simulate mode every AI call goes to the mock (fail closed
if the scenario is missing or invalid); in live mode SimWork does
nothing and the harness talks to its real provider.
"""

import json
import urllib.error
import urllib.request

import pytest

from simwork.llm import ScenarioError
from simwork.routing import RoutingError, SimWorkConfig, SimWorkRouter, load_config

SCENARIO_YAML = """\
name: ticket-status
seed: 7
model: simwork-mock
turns:
  - content: "I will check the ticket."
  - tool_calls:
      - name: lookup_ticket
        arguments: {ticket_id: "T-123"}
  - content: "Your replacement has shipped."
"""

MESSAGES = [{"role": "user", "content": "What's the status of ticket T-123?"}]


def _post_chat(base_url: str, messages: list[dict]) -> dict:
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps({"model": "simwork-mock", "messages": messages}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


@pytest.fixture
def scenario_file(tmp_path):
    path = tmp_path / "scenario.yaml"
    path.write_text(SCENARIO_YAML, encoding="utf-8")
    return path


# --- load_config ---------------------------------------------------------


def test_default_config_is_live_with_no_scenario():
    config = load_config(env={})
    assert config == SimWorkConfig(mode="live", scenario_path=None, host="127.0.0.1", port=0)


def test_simulate_mode_requires_a_scenario():
    with pytest.raises(RoutingError, match="SIMWORK_SCENARIO"):
        load_config(env={"SIMWORK_MODE": "simulate"})


def test_simulate_mode_accepts_a_scenario_path(scenario_file):
    config = load_config(env={"SIMWORK_MODE": "simulate", "SIMWORK_SCENARIO": str(scenario_file)})
    assert config.mode == "simulate"
    assert config.scenario_path == scenario_file


def test_mode_is_case_insensitive(scenario_file):
    config = load_config(env={"SIMWORK_MODE": "Simulate", "SIMWORK_SCENARIO": str(scenario_file)})
    assert config.mode == "simulate"


def test_unknown_mode_fails_closed():
    with pytest.raises(RoutingError, match="SIMWORK_MODE"):
        load_config(env={"SIMWORK_MODE": "staging"})


def test_bad_port_fails_closed():
    with pytest.raises(RoutingError, match="SIMWORK_PORT"):
        load_config(env={"SIMWORK_PORT": "not-a-port"})
    with pytest.raises(RoutingError, match="SIMWORK_PORT"):
        load_config(env={"SIMWORK_PORT": "70000"})


def test_host_and_port_overrides(scenario_file):
    config = load_config(
        env={
            "SIMWORK_MODE": "simulate",
            "SIMWORK_SCENARIO": str(scenario_file),
            "SIMWORK_HOST": "127.0.0.1",
            "SIMWORK_PORT": "8123",
        }
    )
    assert config.host == "127.0.0.1"
    assert config.port == 8123


# --- SimWorkRouter -------------------------------------------------------


def test_live_router_is_a_noop():
    with SimWorkRouter(SimWorkConfig(mode="live")) as router:
        assert router.base_url is None
        assert router.env_overrides == {}


def test_simulate_router_serves_the_scenario(scenario_file):
    config = SimWorkConfig(mode="simulate", scenario_path=scenario_file)
    with SimWorkRouter(config) as router:
        assert router.base_url is not None
        assert router.base_url.startswith("http://127.0.0.1:")
        assert router.base_url.endswith("/v1")
        assert router.env_overrides == {
            "OPENAI_BASE_URL": router.base_url,
            "OPENAI_API_KEY": "simwork-simulated",
        }
        first = _post_chat(router.base_url, MESSAGES)
        assert first["choices"][0]["message"]["content"] == "I will check the ticket."
        assert first["model"] == "simwork-mock"
        second = _post_chat(router.base_url, MESSAGES)
        assert second["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == (
            "lookup_ticket"
        )


def test_simulate_router_is_deterministic(scenario_file):
    config = SimWorkConfig(mode="simulate", scenario_path=scenario_file)
    with SimWorkRouter(config) as first:
        first_run = _post_chat(first.base_url, MESSAGES)
    with SimWorkRouter(config) as second:
        second_run = _post_chat(second.base_url, MESSAGES)
    assert first_run == second_run


def test_simulate_router_stops_the_server_on_exit(scenario_file):
    config = SimWorkConfig(mode="simulate", scenario_path=scenario_file)
    with SimWorkRouter(config) as router:
        base_url = router.base_url
    with pytest.raises(urllib.error.URLError):
        _post_chat(base_url, MESSAGES)


def test_simulate_router_fails_closed_on_bad_scenario(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("turns: []\n", encoding="utf-8")
    router = SimWorkRouter(SimWorkConfig(mode="simulate", scenario_path=bad))
    with pytest.raises(ScenarioError):
        router.__enter__()
    assert router.base_url is None


def test_simulate_router_fails_closed_on_missing_scenario(tmp_path):
    router = SimWorkRouter(SimWorkConfig(mode="simulate", scenario_path=tmp_path / "nope.yaml"))
    with pytest.raises(ScenarioError):
        router.__enter__()
    assert router.base_url is None


def test_router_from_env(scenario_file, monkeypatch):
    monkeypatch.setenv("SIMWORK_MODE", "simulate")
    monkeypatch.setenv("SIMWORK_SCENARIO", str(scenario_file))
    with SimWorkRouter.from_env() as router:
        assert router.base_url is not None
        reply = _post_chat(router.base_url, MESSAGES)
        assert reply["choices"][0]["message"]["content"] == "I will check the ticket."
