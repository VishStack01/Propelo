"""Copy propelo/data/slop_rules.json into the dashboard's wording check.

propelo/writing.py and the dashboard must read the same rules; tests compare them.
Run after editing the JSON: python3 scripts/sync_slop_rules.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    rules = json.loads((ROOT / "propelo" / "data" / "slop_rules.json").read_text(encoding="utf-8"))["rules"]
    blob = json.dumps(rules, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    dash = ROOT / "dashboard" / "app.html"
    s = dash.read_text(encoding="utf-8")
    s, n = re.subn(r"^const SLOP_RULES = .*;$", lambda m: f"const SLOP_RULES = {blob};", s, count=1, flags=re.M)
    assert n == 1, "SLOP_RULES not found in dashboard/app.html"
    dash.write_text(s, encoding="utf-8")
    print(f"{len(rules)} wording rules written to the dashboard")


if __name__ == "__main__":
    main()
