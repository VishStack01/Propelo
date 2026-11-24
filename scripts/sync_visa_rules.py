"""Copy propelo/data/visa_rules.json into the dashboard's Visa-Clock.

The Python clock (propelo/visaclock.py) and the dashboard must read the same rules; tests compare them.
Run after editing the JSON: python3 scripts/sync_visa_rules.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    rules = json.loads((ROOT / "propelo" / "data" / "visa_rules.json").read_text(encoding="utf-8"))
    rules.pop("_about", None)
    blob = json.dumps(rules, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    dash = ROOT / "dashboard" / "app.html"
    s = dash.read_text(encoding="utf-8")
    s, n = re.subn(r"^const VISA_RULES = .*;$", lambda m: f"const VISA_RULES = {blob};", s, count=1, flags=re.M)
    assert n == 1, "VISA_RULES not found in dashboard/app.html"
    dash.write_text(s, encoding="utf-8")
    print(f"{len(rules['statuses'])} visa statuses written to the dashboard")


if __name__ == "__main__":
    main()
