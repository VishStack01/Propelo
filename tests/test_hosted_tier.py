"""The service's own model: quick tasks on the quick model, application writing on the main one."""

from careeros.cloud.plans import hosted_tier


def test_hosted_tier():
    assert hosted_tier("default", "") == "quick"
    assert hosted_tier("default", "copilot") == "quick"
    assert hosted_tier("quick", "mock") == "quick"
    assert hosted_tier("complex", "") == "complex"
    assert hosted_tier("default", "refine") == "default"
    assert hosted_tier("default", "regen") == "default"
