"""Write the website's plan cards from the plan catalog (careeros/cloud/plans.py), so they never drift.
Run after changing plan features: python3 scripts/sync_plan_cards.py"""

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from careeros.cloud.plans import catalog, public_config  # noqa: E402

page = ROOT / "website" / "index.html"
text = page.read_text(encoding="utf-8")
cat = {p["id"]: p for p in catalog(public_config())}
for cls, plan in (("", "free"), (" pro", "pro"), (" ultra", "ultra")):
    m = re.search(r'(<article class="price%s reveal">.*?<ul>)(.*?)(</ul>)' % cls, text, re.S)
    items = "".join(f"<li>{html.escape(f, quote=False)}</li>" for f in cat[plan]["features"])
    text = text[:m.start(2)] + items + text[m.end(2):]
page.write_text(text, encoding="utf-8")
print("website plan cards updated")
