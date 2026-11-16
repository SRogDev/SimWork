"""SimWork — simulate AI apps in a fake world before spending real API calls."""

from simwork.routing import RoutingError, SimWorkConfig, SimWorkRouter, load_config

__version__ = "0.1.0"

__all__ = ["RoutingError", "SimWorkConfig", "SimWorkRouter", "__version__", "load_config"]
