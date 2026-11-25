"""The dashboard's five places: every screen belongs to exactly one, and phones and the sidebar agree."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "dashboard" / "app.html").read_text(encoding="utf-8")


def _js_obj(name):
    src = re.search(r"const %s = (\{.*?\});" % name, HTML, re.S).group(1)
    return json.loads(re.sub(r"([{,]\s*)(\w+):", r'\1"\2":', src).replace("'", '"'))


def test_every_screen_lives_in_exactly_one_place():
    tabs = json.loads(re.search(r"const TABS = (\[.*?\]);", HTML).group(1).replace("'", '"'))
    pillars = _js_obj("PILLARS")
    assert list(pillars) == ["today", "discover", "pipeline", "prep", "brain"]
    placed = [t for ts in pillars.values() for t in ts]
    assert sorted(placed) == sorted(tabs) and len(placed) == len(set(placed))
    labels = _js_obj("SUBTAB")
    assert set(labels) == set(placed) - {"app"}


def test_sidebar_and_dock_show_the_same_five_places():
    side = re.findall(r'class="tab pbtn" data-act="pillar" data-pil="(\w+)"', HTML)
    dock = re.findall(r'data-act="pillar" data-pil="(\w+)" data-dock="\1"', HTML)
    assert side == dock == ["today", "discover", "pipeline", "prep", "brain"]
    assert 'id="sheet-more"' not in HTML and 'id="sheet-add"' not in HTML and 'id="dk-inbox"' not in HTML
    # a new reply marks Pipeline, where the inbox is, not Applications
    assert "need = {today: nQueue, discover: ready, pipeline: nInbox, prep: todos" in HTML
    for tid in ("t-home", "t-queue", "t-today", "t-new", "t-skipped", "t-pipeline", "t-auto", "t-inbox", "t-calendar",
                "t-outreach", "t-contacts", "t-tools", "t-profile", "t-resume", "t-guarantee", "t-ask", "t-setup"):
        assert f'id="{tid}"' in HTML, tid
