"""Scenario S6: replay every journey; 100% step and suppression correctness is the done-when."""

import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("replay", pathlib.Path(__file__).parents[2] / "evals" / "replay.py")
assert spec and spec.loader
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def test_all_journeys_replay_correctly():
    m = replay.run()
    assert m["failures"] == []
    assert m["step_correctness"] == 1.0 and m["marketing_suppression_correctness"] == 1.0
