"""Phase 3 eval tooling: guard metrics and judge calibration must keep measuring what they claim."""

import importlib.util
import pathlib

import yaml

EVALS = pathlib.Path(__file__).parents[2] / "evals"


def load(name):
    spec = importlib.util.spec_from_file_location(name, EVALS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_guards_meet_recall_and_false_positive_targets():
    m = load("guard_metrics").run()
    for g in ("direct_injection", "indirect_injection"):
        assert m[g]["recall"] == 1.0 and m[g]["fpr"] <= 0.05, (g, m[g])
    assert m["pii"]["exact_match"] == 1.0 and not m["pii"]["over_redacted"]


def test_calibration_detects_a_length_biased_judge():
    jc = load("judge_calibration")
    cases = yaml.safe_load((EVALS / "judge_cases.yaml").read_text())["cases"]
    naive = jc.calibrate(jc.length_judge, cases)
    assert naive["pass_rate_on_bad_long"] - naive["pass_rate_on_bad_short"] >= 0.5  # bias is visible
    assert naive["kappa"] < 0.2  # and kappa exposes it, whatever the raw agreement


def test_kappa_is_zero_for_chance_agreement():
    jc = load("judge_calibration")
    assert jc.kappa([True, True, False, False], [True, False, True, False]) == 0.0
