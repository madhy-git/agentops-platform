"""Oversight drill: a rubber-stamping approver is detected; a careful one catches seeded bad proposals."""

import importlib.util
import pathlib

from agentops.service import TriageService

spec = importlib.util.spec_from_file_location("oversight", pathlib.Path(__file__).parents[2] / "evals" / "oversight.py")
oversight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oversight)


def test_rubber_stamping_is_flagged(conn):
    svc = TriageService(conn)
    for aid in oversight.seed(conn, n=6, bad=2):
        svc.decide(aid, True, "manager-2", {"manager"})  # approves everything, instantly
    m = oversight.report(conn)
    assert m["seeded_bad_caught"] == 0.0
    assert any("rubber-stamping" in w for w in m["warnings"]) and any("deliberately wrong" in w for w in m["warnings"])


def test_careful_approver_catches_seeded_bad(conn):
    svc = TriageService(conn)
    for aid in oversight.seed(conn, n=6, bad=2):
        bad = svc.approvals.get(aid)["seeded_bad"]  # stands in for a human reading the case properly
        svc.decide(aid, not bad, "manager-2", {"manager"}, reason="action doesn't fit the message" if bad else "")
    m = oversight.report(conn)
    assert m["seeded_bad_caught"] == 1.0
    assert not any("deliberately wrong" in w for w in m["warnings"])
