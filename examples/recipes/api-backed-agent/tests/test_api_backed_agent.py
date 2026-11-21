"""API-backed-agent recipe — eval suite.

Gates the recorded run trace in evals/ on the $0 DeepEval-based
metrics (tool correctness + task completion) and asserts the answer
is computed from the API data: the euro/pound amounts in the final
answer must equal 100 USD multiplied by the rates the tool result
returned — not a number the scripted LLM invented on its own.

Run from the recipe directory: pytest
"""

from pathlib import Path

from simwork import evaluate_run, load_trace
from simwork.trace import final_answer

HERE = Path(__file__).resolve().parent.parent

# The amount the user asked about (USD), in run.py's USER_QUESTION.
AMOUNT_USD = 100


def test_api_backed_agent_trace_passes():
    trace = load_trace(HERE / "evals" / "api-backed-agent-trace.json")
    report = evaluate_run(trace)
    assert report.passed, report.to_text()


def test_api_backed_agent_answer_is_computed_from_api_rates():
    trace = load_trace(HERE / "evals" / "api-backed-agent-trace.json")
    results = [s for s in trace["steps"] if s["type"] == "tool_result"]
    assert len(results) == 1
    assert results[0]["name"] == "get_exchange_rates"
    rates = results[0]["result"]["rates"]
    answer = final_answer(trace)
    for currency in ("EUR", "GBP"):
        expected = f"{AMOUNT_USD * rates[currency]:.0f} {currency}"
        assert expected in answer, f"expected {expected!r} in final answer {answer!r}"
