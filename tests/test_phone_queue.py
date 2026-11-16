"""The review queue and apply kit: the phone way to work through roles. They change a role's stage and
never submit anything; the kit shows only what the person saved, never private numbers."""

import re
from pathlib import Path

APP = (Path(__file__).resolve().parent.parent / "dashboard" / "app.html").read_text()


def _fn(name: str) -> str:
    i = APP.index(f"function {name}(")
    return APP[i:APP.index("\nfunction ", i + 10)]


def test_queue_is_a_tab_on_phone_and_desktop():
    assert "'queue'" in APP[APP.index("const TABS"):APP.index("];", APP.index("const TABS"))]
    assert 'data-tab="queue"' in APP and 'id="p-queue"' in APP


def test_below_the_apply_line_needs_apply_anyway():
    q = _fn("renderQueue")
    assert "belowLine(j) ?" in q and "q-anyway" in q and "Apply anyway" in q
    assert "!belowLine(j)" in _fn("queueItems")  # fresh roles below the line aren't offered at all
    handler = APP[APP.index("act === 'q-anyway'"):APP.index("\n", APP.index("act === 'q-anyway'"))]
    assert "scoreOverride: true" in handler


def test_nothing_submits_from_the_queue():
    for name in ("renderQueue", "openKit", "queueItems"):
        body = _fn(name)
        assert "submit" not in re.sub(r"Nothing is submitted from this screen|submitted from here", "", body).lower(), name


def test_kit_never_shows_private_numbers():
    kit = _fn("openKit")
    for k in ("aadhaar", "pan", "passport", "dob", "dateOfBirth", "bank", "password"):
        assert f"a.{k}" not in kit
    assert "prefer not" in kit  # "Prefer not to say" isn't offered as an answer to copy
