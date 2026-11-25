"""Copy propelo/data/sponsor_brief.json into the dashboard's sponsor brief.

The Python brief (propelo/sponsorbrief.py) and the dashboard must read the same facts; tests compare them.
Run after editing the JSON: python3 scripts/sync_sponsor_brief.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    rules = json.loads((ROOT / "propelo" / "data" / "sponsor_brief.json").read_text(encoding="utf-8"))
    rules.pop("_about", None)
    blob = json.dumps(rules, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    dash = ROOT / "dashboard" / "app.html"
    s = dash.read_text(encoding="utf-8")
    s, n = re.subn(r"^const SPONSOR_BRIEF = .*;$", lambda m: f"const SPONSOR_BRIEF = {blob};", s, count=1, flags=re.M)
    assert n == 1, "SPONSOR_BRIEF not found in dashboard/app.html"
    dash.write_text(s, encoding="utf-8")
    print(f"{len(rules['briefs'])} briefs and {len(rules['abroad'])} countries written to the dashboard")


if __name__ == "__main__":
    main()
