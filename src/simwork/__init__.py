"""SimWork — simulate AI apps in a fake world before spending real API calls."""

from simwork.api_mock import ApiMockError, ApiMockStack, PrismMockServer, fetch_api_spec
from simwork.deepeval_judge import (
    JudgeError,
    check_judge_ready,
    deepeval_available,
    evaluate_run_with_judge,
    judge_metrics,
    run_judge,
    trace_to_test_case,
)
from simwork.demo import DemoError, run_demo
from simwork.eval import EvalReport, MetricResult, evaluate_run
from simwork.trace import TraceError, load_trace
from simwork.init import InitError, init_project
from simwork.prompt import CONFIGURE_SIMWORK_PROMPT, prompt_text
from simwork.routing import RoutingError, SimWorkConfig, SimWorkRouter, load_config
from simwork.trace import TraceRecorder, completion_to_step

__version__ = "0.1.0"

__all__ = [
    "ApiMockError",
    "ApiMockStack",
    "CONFIGURE_SIMWORK_PROMPT",
    "DemoError",
    "EvalReport",
    "InitError",
    "JudgeError",
    "MetricResult",
    "PrismMockServer",
    "RoutingError",
    "SimWorkConfig",
    "SimWorkRouter",
    "TraceError",
    "TraceRecorder",
    "__version__",
    "check_judge_ready",
    "completion_to_step",
    "deepeval_available",
    "evaluate_run",
    "evaluate_run_with_judge",
    "fetch_api_spec",
    "init_project",
    "judge_metrics",
    "load_config",
    "load_trace",
    "prompt_text",
    "run_demo",
    "run_judge",
    "trace_to_test_case",
]
