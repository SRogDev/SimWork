"""Routing: `SIMWORK_MODE` + scenario path -> fake server or live passthrough.

In simulate mode every AI call routes to the LLM mock: the router loads
the scenario file and starts a `FakeOpenAIServer` from it, exposing the
`OPENAI_BASE_URL` / `OPENAI_API_KEY` overrides an unmodified harness
needs for a base-URL swap. In live mode the router is a no-op — the
harness talks to its real provider. Anything misconfigured fails
closed (`RoutingError` / `ScenarioError`) before any server starts.

Environment variables (see also `load_config`):

- ``SIMWORK_MODE``: ``simulate`` or ``live`` (default ``live`` — simulate
  is explicit opt-in, so an unset variable never silently intercepts a
  harness). Case-insensitive.
- ``SIMWORK_SCENARIO``: path to the YAML scenario file. Required in
  simulate mode; ignored in live mode.
- ``SIMWORK_HOST``: bind host for the fake server (default ``127.0.0.1``).
- ``SIMWORK_PORT``: bind port (default ``0`` = ephemeral).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from simwork.llm import FakeOpenAIServer, load_scenario

_MODES = ("simulate", "live")
_SIMULATED_API_KEY = "simwork-simulated"


class RoutingError(ValueError):
    """Raised when the simulate/live routing configuration is invalid."""


@dataclass(frozen=True)
class SimWorkConfig:
    """Resolved routing configuration (see `load_config`)."""

    mode: str = "live"
    scenario_path: Path | None = None
    host: str = "127.0.0.1"
    port: int = 0


def load_config(env: Mapping[str, str] | None = None) -> SimWorkConfig:
    """Resolve routing config from environment variables (or `env`).

    Fails closed: an unknown `SIMWORK_MODE`, a missing scenario path in
    simulate mode, or an invalid `SIMWORK_PORT` raises `RoutingError`.
    """
    env = os.environ if env is None else env
    mode = env.get("SIMWORK_MODE", "live").strip().lower()
    if mode not in _MODES:
        raise RoutingError(f"SIMWORK_MODE must be one of {sorted(_MODES)}, got {mode!r}")
    scenario_raw = env.get("SIMWORK_SCENARIO")
    scenario_path = Path(scenario_raw) if scenario_raw else None
    if mode == "simulate" and scenario_path is None:
        raise RoutingError(
            "SIMWORK_MODE=simulate requires SIMWORK_SCENARIO (path to a YAML scenario file)"
        )
    return SimWorkConfig(
        mode=mode,
        scenario_path=scenario_path,
        host=env.get("SIMWORK_HOST", "127.0.0.1"),
        port=_parse_port(env.get("SIMWORK_PORT", "0")),
    )


def _parse_port(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError:
        raise RoutingError(f"SIMWORK_PORT must be an integer, got {raw!r}") from None
    if not 0 <= port <= 65535:
        raise RoutingError(f"SIMWORK_PORT must be 0-65535, got {port}")
    return port


class SimWorkRouter:
    """Starts the fake OpenAI server in simulate mode; no-op in live mode.

    Usage::

        with SimWorkRouter.from_env() as router:
            os.environ.update(router.env_overrides)  # harness points at the mock
            run_harness()                            # $0, no real LLM calls
    """

    def __init__(self, config: SimWorkConfig):
        self.config = config
        self._server: FakeOpenAIServer | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SimWorkRouter":
        return cls(load_config(env))

    def __enter__(self) -> "SimWorkRouter":
        if self.config.mode == "live":
            return self
        assert self.config.scenario_path is not None  # guaranteed by load_config
        scenario = load_scenario(self.config.scenario_path)
        self._server = FakeOpenAIServer(
            scenario.turns,
            seed=scenario.seed,
            model=scenario.model,
            host=self.config.host,
            port=self.config.port,
        ).start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def stop(self) -> None:
        if self._server is not None:
            self._server.stop()
            self._server = None

    @property
    def base_url(self) -> str | None:
        """Fake server base URL in simulate mode, else `None`."""
        return self._server.base_url if self._server is not None else None

    @property
    def env_overrides(self) -> Mapping[str, str]:
        """Env vars that point an OpenAI-compatible client at the mock.

        Empty in live mode. The dummy API key keeps clients that require
        a key from failing before they ever reach the mock.
        """
        if self._server is None:
            return MappingProxyType({})
        return MappingProxyType(
            {
                "OPENAI_BASE_URL": self._server.base_url,
                "OPENAI_API_KEY": _SIMULATED_API_KEY,
            }
        )
