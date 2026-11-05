from agentops.resilience import CircuitBreaker


def test_breaker_opens_after_threshold_then_half_opens_after_cooldown():
    now = [0.0]
    b = CircuitBreaker(threshold=3, cooldown_s=30, clock=lambda: now[0])
    for _ in range(2):
        b.record_failure("tier2")
    assert b.allow("tier2")  # 2 failures: still closed
    b.record_failure("tier2")
    assert not b.allow("tier2")  # 3rd failure: open
    now[0] = 31
    assert b.allow("tier2")  # cooldown over: one probe allowed (half-open)
    b.record_failure("tier2")
    assert not b.allow("tier2")  # probe failed: open again
    now[0] = 62
    b.record_success("tier2")
    assert b.allow("tier2") and not b.is_open("tier2")  # probe succeeded: closed
