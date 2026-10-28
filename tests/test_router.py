from agentops.router import fallback_chain, route


def test_simple_goes_cheap():
    d = route("What are your fees?")
    assert d.model.tier == 1


def test_tools_need_mid_tier():
    assert route("Look up my case", needs_tools=True).model.tier == 2


def test_high_risk_goes_frontier():
    assert route("I want to lodge a hardship complaint").model.tier == 3


def test_budget_cap_and_fallback():
    d = route("fraud on my card", budget_tier=2)
    assert d.model.tier == 2
    assert [m.tier for m in fallback_chain(d)] == [2, 3]
