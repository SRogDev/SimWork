"""SimWork — simulate AI apps in a fake world before spending real API calls."""

from simwork.api_mock import ApiMockError, PrismMockServer, fetch_api_spec
from simwork.eval import EvalReport, MetricResult, TraceError, evaluate_run, load_trace
from simwork.routing import RoutingError, SimWorkConfig, SimWorkRouter, load_config

__version__ = "0.1.0"

__all__ = [
    "ApiMockError",
    "EvalReport",
    "MetricResult",
    "PrismMockServer",
    "RoutingError",
    "SimWorkConfig",
    "SimWorkRouter",
    "TraceError",
    "__version__",
    "evaluate_run",
    "fetch_api_spec",
    "load_config",
    "load_trace",
]
