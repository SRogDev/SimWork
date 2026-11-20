"""RAG assistant recipe — eval suite.

Gates the recorded run trace in evals/ on the $0 DeepEval-based
metrics (tool correctness + task completion) and asserts grounding:
the final answer must contain a phrase that came from the retrieved
doc (the tool result), not from the scripted LLM alone.

Run from the recipe directory: pytest
"""

from pathlib import Path

from simwork import evaluate_run, load_trace
from simwork.trace import final_answer

HERE = Path(__file__).resolve().parent.parent

# A phrase from the retrieved doc (docs-api.yaml) that the final
# answer must repeat — the grounding check. Keep in sync with the
# scenario and the trace.
GROUNDED_PHRASE = "30 days from delivery"


def test_rag_assistant_trace_passes():
    trace = load_trace(HERE / "evals" / "rag-assistant-trace.json")
    report = evaluate_run(trace)
    assert report.passed, report.to_text()


def test_rag_assistant_answer_is_grounded_in_retrieved_docs():
    trace = load_trace(HERE / "evals" / "rag-assistant-trace.json")
    results = [s for s in trace["steps"] if s["type"] == "tool_result"]
    assert len(results) == 1
    retrieved_text = " ".join(
        doc.get("text", "") for doc in results[0]["result"].get("results", [])
    )
    assert GROUNDED_PHRASE in retrieved_text
    assert GROUNDED_PHRASE in final_answer(trace)
