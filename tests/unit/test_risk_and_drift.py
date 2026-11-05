import json

from agentops.config import REPO_ROOT
from agentops.decision import drift, risk


def test_risk_model_beats_chance_on_held_out_data():
    m = risk.default_model()
    assert m.auc > 0.65, m.auc  # the generator has a real signal; the model must find it


def test_risk_model_learns_the_right_direction():
    coef = risk.default_model().coefficients()
    assert coef["low_logins"] > 0 and coef["complaints_12m"] > 0 and coef["many_products"] < 0


def test_psi_flags_the_drifted_population_but_not_a_resample():
    def col(path, f):
        rows = [json.loads(line) for line in (REPO_ROOT / "data" / "generated" / path).read_text().splitlines()]
        return [r[f] for r in rows]

    base = col("customers.jsonl", "monthly_logins")
    assert drift.psi(base[:300], base[300:]) < 0.1  # same population, two halves: stable
    assert drift.psi(base, col("customers_drifted.jsonl", "monthly_logins")) > 0.25  # shifted: investigate
