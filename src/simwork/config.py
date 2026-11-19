"""`simwork.yaml` config-file loader (adoption, readiness criterion 1).

`simwork init` has always written a `simwork.yaml` starter config, but
until now nothing read it — routing worked through flags and
environment variables only. This module closes that gap: `simwork
serve` and `simwork eval` read the file, with precedence CLI flags >
environment variables > config file > defaults.

Rules, matching the rest of SimWork's fail-closed posture:

- The file is strict YAML: unknown keys fail (a typo must not silently
  run with the wrong settings), wrong types fail, and a missing
  explicit file fails instead of falling back to defaults.
- Relative paths in the file resolve against the file's own directory,
  so a project can be run from any subdirectory.
- Discovery walks up from the current directory (like most project
  tools), so `simwork serve` in a project subdirectory finds the
  project's config. An explicit `--config` path always wins over
  discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from simwork.routing import SimWorkConfig, load_config

_CONFIG_FILENAME = "simwork.yaml"
_MODES = ("simulate", "live")
_TOP_LEVEL_KEYS = frozenset({"mode", "scenario", "seed", "host", "port", "eval"})
_EVAL_KEYS = frozenset({"trace", "report"})


class ConfigError(ValueError):
    """Raised when a `simwork.yaml` config file is missing or invalid."""


@dataclass(frozen=True)
class SimWorkFileConfig:
    """Parsed `simwork.yaml` (paths resolved against the file's directory)."""

    mode: str = "live"
    scenario: Path | None = None
    seed: int | None = None
    host: str = "127.0.0.1"
    port: int = 0
    eval_trace: Path | None = None
    eval_report: Path | None = None
    source: Path | None = None


def _fail(source: str, message: str) -> ConfigError:
    return ConfigError(f"{source}: {message}")


def _require_str(data: Mapping, key: str, *, source: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise _fail(source, f"{key!r} must be a non-empty string, got {value!r}")
    return value


def _require_int(data: Mapping, key: str, *, source: str, minimum: int = 0) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    # bool is an int subclass — `seed: true` is a typo, not a seed.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _fail(source, f"{key!r} must be an integer >= {minimum}, got {value!r}")
    return value


def parse_config_text(text: str, *, base_dir: str | Path, source: str | Path) -> SimWorkFileConfig:
    """Parse `simwork.yaml` text; paths resolve against `base_dir`.

    `source` is only used in error messages (the file's path or display
    name). An empty file is a valid all-defaults config.
    """
    source_name = str(source)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise _fail(source_name, f"invalid YAML: {e}") from None
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise _fail(source_name, f"top level must be a mapping, got {type(data).__name__}")
    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise _fail(
            source_name,
            f"unknown key(s): {', '.join(sorted(map(str, unknown)))} "
            f"(allowed: {', '.join(sorted(_TOP_LEVEL_KEYS))})",
        )
    mode_raw = data.get("mode", "live")
    if not isinstance(mode_raw, str) or mode_raw.strip().lower() not in _MODES:
        raise _fail(source_name, f"'mode' must be one of {sorted(_MODES)}, got {mode_raw!r}")
    mode = mode_raw.strip().lower()
    base = Path(base_dir)
    scenario_raw = _require_str(data, "scenario", source=source_name)
    seed = _require_int(data, "seed", source=source_name)
    host = _require_str(data, "host", source=source_name) or "127.0.0.1"
    port = _require_int(data, "port", source=source_name, minimum=0)
    if port is not None and port > 65535:
        raise _fail(source_name, f"'port' must be 0-65535, got {port}")
    eval_trace = eval_report = None
    eval_raw = data.get("eval")
    if eval_raw is not None:
        if not isinstance(eval_raw, Mapping):
            raise _fail(source_name, f"'eval' must be a mapping, got {type(eval_raw).__name__}")
        unknown_eval = set(eval_raw) - _EVAL_KEYS
        if unknown_eval:
            raise _fail(
                source_name,
                f"unknown eval key(s): {', '.join(sorted(map(str, unknown_eval)))} "
                f"(allowed: {', '.join(sorted(_EVAL_KEYS))})",
            )
        trace_raw = _require_str(eval_raw, "trace", source=source_name)
        report_raw = _require_str(eval_raw, "report", source=source_name)
        eval_trace = _resolve(trace_raw, base)
        eval_report = _resolve(report_raw, base)
    return SimWorkFileConfig(
        mode=mode,
        scenario=_resolve(scenario_raw, base),
        seed=seed,
        host=host,
        port=port if port is not None else 0,
        eval_trace=eval_trace,
        eval_report=eval_report,
        source=Path(source),
    )


def _resolve(raw: str | None, base: Path) -> Path | None:
    if raw is None:
        return None
    path = Path(raw)
    return path if path.is_absolute() else base / path


def load_config_file(path: str | Path) -> SimWorkFileConfig:
    """Load and parse a `simwork.yaml` file (fail closed if missing)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"cannot read config file {path}: {e}") from None
    return parse_config_text(text, base_dir=path.parent, source=path)


def find_config_file(
    start: str | Path | None = None, *, explicit: str | Path | None = None
) -> Path | None:
    """Locate `simwork.yaml`: explicit path wins, else walk up from `start`.

    Returns `None` when no file is found (callers fall back to flags/env
    only). An explicit path is returned as given — `load_config_file`
    reports it missing.
    """
    if explicit is not None:
        return Path(explicit)
    current = Path(start) if start is not None else Path.cwd()
    for parent in (current, *current.parents):
        candidate = parent / _CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_file_config(explicit: str | Path | None = None) -> SimWorkFileConfig | None:
    """Discover (`find_config_file`) and load the config file, if any."""
    found = find_config_file(explicit=explicit)
    if found is None:
        return None
    return load_config_file(found)


def resolve_config(
    file_config: SimWorkFileConfig | None,
    env: Mapping[str, str],
    *,
    scenario: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> SimWorkConfig:
    """Merge file + env + CLI routing settings into a `SimWorkConfig`.

    Precedence: CLI flags > environment variables > config file >
    defaults. `env` is the process environment (or a test double);
    `SIMWORK_MODE` in it still applies, so a file that says
    `mode: simulate` can be overridden to `live` from the environment.
    Fails closed via `load_config` when simulate mode has no scenario.
    """
    merged: dict[str, str] = {}
    if file_config is not None:
        merged["SIMWORK_MODE"] = file_config.mode
        if file_config.scenario is not None:
            merged["SIMWORK_SCENARIO"] = str(file_config.scenario)
        merged["SIMWORK_HOST"] = file_config.host
        merged["SIMWORK_PORT"] = str(file_config.port)
    for key in ("SIMWORK_MODE", "SIMWORK_SCENARIO", "SIMWORK_HOST", "SIMWORK_PORT"):
        if key in env:
            merged[key] = env[key]
    if scenario is not None:
        merged["SIMWORK_SCENARIO"] = scenario
    if host is not None:
        merged["SIMWORK_HOST"] = host
    if port is not None:
        merged["SIMWORK_PORT"] = str(port)
    # Fails closed via load_config when simulate mode has no scenario.
    return load_config(merged)


def resolve_eval(
    file_config: SimWorkFileConfig | None,
    *,
    trace: str | Path | None = None,
    report: str | Path | None = None,
) -> tuple[Path | None, Path | None]:
    """Merge eval trace/report paths: CLI flags win over the config file."""
    resolved_trace = Path(trace) if trace is not None else None
    resolved_report = Path(report) if report is not None else None
    if resolved_trace is None and file_config is not None:
        resolved_trace = file_config.eval_trace
    if resolved_report is None and file_config is not None:
        resolved_report = file_config.eval_report
    return resolved_trace, resolved_report
