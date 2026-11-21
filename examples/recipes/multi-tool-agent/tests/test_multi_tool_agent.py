"""Multi-tool-agent recipe — eval suite.

Gates the recorded run trace in evals/ on the $0 DeepEval-based
metrics (tool correctness + task completion) and asserts the chain:
the hotel call's arguments must come from the flight result (the
destination city and arrival date of the cheapest flight), and the
total in the final answer must equal the cheapest flight price plus
the hotel price per night times the nights — not numbers the
scripted LLM invented on its own.

Run from the recipe directory: pytest
"""

from pathlib import Path

from simwork import evaluate_run, load_trace
from simwork.trace import final_answer, tool_calls

HERE = Path(__file__).resolve().parent.parent


def test_multi_tool_agent_trace_passes():
    trace = load_trace(HERE / "evals" / "multi-tool-agent-trace.json")
    report = evaluate_run(trace)
    assert report.passed, report.to_text()


def test_multi_tool_agent_chain_is_derived_from_tool_results():
    trace = load_trace(HERE / "evals" / "multi-tool-agent-trace.json")
    calls = tool_calls(trace)
    assert [c["name"] for c in calls] == ["search_flights", "search_hotels"]
    results = {s["name"]: s["result"] for s in trace["steps"] if s["type"] == "tool_result"}
    assert set(results) == {"search_flights", "search_hotels"}

    # The hotel call's arguments come from the flight result: the
    # cheapest flight's destination city and arrival date.
    flights = results["search_flights"]["flights"]
    cheapest = min(flights, key=lambda f: f["price_usd"])
    hotel_call = calls[1]
    assert hotel_call["arguments"]["city"] == cheapest["destination_city"], (
        f"hotel city {hotel_call['arguments']['city']!r} does not match "
        f"cheapest flight destination {cheapest['destination_city']!r}"
    )
    assert hotel_call["arguments"]["checkin"] == cheapest["arrival_date"], (
        f"hotel checkin {hotel_call['arguments']['checkin']!r} does not match "
        f"cheapest flight arrival {cheapest['arrival_date']!r}"
    )

    # The total in the final answer is computed from the chained
    # results: cheapest flight + hotel price per night x nights.
    hotel = results["search_hotels"]["hotels"][0]
    nights = hotel_call["arguments"]["nights"]
    total = cheapest["price_usd"] + hotel["price_per_night_usd"] * nights
    answer = final_answer(trace)
    assert f"${total:.0f}" in answer, f"expected ${total:.0f} in final answer {answer!r}"
    assert f"${cheapest['price_usd']:.0f}" in answer
    assert f"${hotel['price_per_night_usd']:.0f}" in answer
