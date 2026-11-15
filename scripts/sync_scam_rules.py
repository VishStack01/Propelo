"""Copy careeros/data/scam_rules.json into the dashboard and the website's scam check page.

The Python check, the dashboard and website/check.html must use the same rules; tests compare them.
Run after editing the JSON: python3 scripts/sync_scam_rules.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    rules = json.loads((ROOT / "careeros" / "data" / "scam_rules.json").read_text(encoding="utf-8"))["rules"]
    blob = json.dumps(rules, ensure_ascii=False)
    dash = ROOT / "dashboard" / "app.html"
    s = dash.read_text(encoding="utf-8")
    s, n = re.subn(r"^const SCAM_RULES = .*;$", lambda m: f"const SCAM_RULES = {blob};", s, count=1, flags=re.M)
    assert n == 1, "SCAM_RULES not found in dashboard/app.html"
    dash.write_text(s, encoding="utf-8")
    page = ROOT / "website" / "check.html"
    s = page.read_text(encoding="utf-8")
    safe = blob.replace("</", "<\\/")  # keep the JSON from closing the script tag
    s, n = re.subn(r'(<script id="scam-rules" type="application/json">).*?(</script>)', lambda m: m.group(1) + safe + m.group(2), s, count=1, flags=re.S)
    assert n == 1, "scam-rules block not found in website/check.html"
    page.write_text(s, encoding="utf-8")
    print(f"{len(rules)} rules written to the dashboard and website/check.html")


if __name__ == "__main__":
    main()
