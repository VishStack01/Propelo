"""The product docs in docs/product/ stay in step with the code (see docs/product/README.md)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_product_docs_are_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "product_docs.py"), "--check"], cwd=ROOT,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


def test_register_and_test_log_are_well_formed():
    import csv
    reg = list(csv.DictReader(open(ROOT / "docs/product/register.csv", encoding="utf-8")))
    assert reg and len({r["ID"] for r in reg}) == len(reg)
    for r in reg:
        assert r["Priority"] in {"P0", "P1", "P2", "P3"}, r["ID"]
        assert r["Status"] in {"Open", "Fixed", "Verified", "Partial", "Not verified", "Won't do", "Owner action"}, r["ID"]
    qa = list(csv.DictReader(open(ROOT / "docs/product/qa-tests.csv", encoding="utf-8")))
    assert qa and len({r["ID"] for r in qa}) == len(qa)
    for r in qa:
        assert r["Status"] in {"Pass", "Fail", "Fixed", "Not run", "Blocked"}, r["ID"]
        if r["Status"] in {"Pass", "Fixed"}:
            assert r["Evidence"].strip(), r["ID"]
