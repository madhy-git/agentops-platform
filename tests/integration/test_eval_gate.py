"""The release gate, and scenario S5: a harmful change must fail it."""

import importlib.util
import pathlib

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agentops import agent
from agentops.service import TriageService

spec = importlib.util.spec_from_file_location("run_evals", pathlib.Path(__file__).parents[2] / "evals" / "run_evals.py")
assert spec and spec.loader
run_evals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_evals)


def test_eval_gate_passes_on_main():
    m = run_evals.run()
    assert run_evals.gate(m) == [], m


def test_paraphrase_gap_stays_visible_offline():
    # If this starts passing, someone taught the offline rules the test's words. Investigate.
    assert run_evals.run()["paraphrase_offline_not_gated"]["escalation_recall"] < 1.0


def lazy_model() -> FunctionModel:
    """A bad 'prompt change': the model labels everything as general and never asks for a human."""
    inner = agent.offline_model()

    def fn(messages, info):
        resp = inner.function(messages, info)
        part = resp.parts[0]
        if isinstance(part, ToolCallPart) and part.tool_name == info.output_tools[0].name:
            args = dict(part.args_as_dict(), needs_human=False, recommended_action="answer", category="general")
            return ModelResponse(parts=[ToolCallPart(part.tool_name, args)])
        return resp

    return FunctionModel(fn)


def test_s5_harmful_change_fails_the_gate(conn):
    # The rules key off the model's *category*, so a model that mislabels fraud as "general" also
    # switches off R1/R5. Defence in depth has limits: the gate is what catches this before release.
    svc = TriageService(conn, model_factory=lambda spec: lazy_model())
    m = run_evals.score(svc, [c for c in run_evals.load() if not c.get("paraphrase")])
    failed = run_evals.gate(
        m | {k: 0.0 if op == "<=" else 1.0 for k, (op, _) in run_evals.THRESHOLDS.items() if k not in m}
    )
    assert {"category_accuracy", "escalation_recall"} <= set(failed), failed
