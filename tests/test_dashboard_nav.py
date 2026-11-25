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


def test_a_lost_connection_is_shown_and_a_refused_request_is_not(tmp_path):
    import shutil
    import subprocess
    import pytest
    if not shutil.which("node"):
        pytest.skip("needs Node")
    block = HTML[HTML.index("const net = {fails: 0"):HTML.index("function makeLocalDB(opts){")]
    js = ("const el = {hidden: true, textContent: ''}; const toasts = []; const $ = () => el; const toast = m => toasts.push(m);\n"
          "global.navigator = {onLine: true};\n" + block +
          "\nconst out = [];\n"
          "netFail({code: 'permission_denied', status: 403}); out.push(el.hidden);\n"
          "netFail(new TypeError('x is undefined')); out.push(el.hidden);\n"
          "netFail({code: 'unavailable', status: 503}); out.push(el.hidden);\n"
          "netFail({code: 'unavailable', status: 503}); out.push(el.hidden, el.textContent);\n"
          "netFail({code: 'unavailable', network: true}); out.push(el.textContent);\n"
          "netOk(); out.push(el.hidden, toasts.slice());\n"
          "clearTimeout(net.retry); console.log(JSON.stringify(out));")
    f = tmp_path / "net.js"
    f.write_text(js, encoding="utf-8")
    got = json.loads(subprocess.run(["node", str(f)], capture_output=True, text=True, check=True).stdout)
    assert got[0] is True and got[1] is True and got[2] is True  # refused, a drawing bug, one blip: nothing shown
    assert got[3] is False and "waking up" in got[4]
    assert "Can't reach Propelo" in got[5]
    assert got[6] is True and got[7] == ["Connected again."]
