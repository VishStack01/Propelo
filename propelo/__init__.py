"""Propelo: an evidence-first job application agent.

The Python package holds the deterministic, testable parts of the system:
board scouts, requirement extraction, filter gates, dedupe, durable state,
the claims checker and the form-answer resolver. Judgement work (research,
tailoring, review) is done by the agent skills in `.claude/skills/`.
"""

__version__ = "2.16.1"


def _alias_env() -> None:
    """Settings can be written PROPELO_X or, as they always were, CAREEROS_X. The code reads the old spelling,
    so a PROPELO_X without a CAREEROS_X of its own is copied across once, when the package is first imported."""
    import os
    for k, v in list(os.environ.items()):
        if k.startswith("PROPELO_"):
            os.environ.setdefault("CAREEROS_" + k[len("PROPELO_"):], v)


_alias_env()
