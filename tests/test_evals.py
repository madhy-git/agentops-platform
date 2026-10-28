import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("run_evals", pathlib.Path(__file__).parents[1] / "evals" / "run_evals.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_eval_gate_thresholds_met():
    m = mod.run()
    for k, v in mod.THRESHOLDS.items():
        assert m[k] >= v, (k, m)
