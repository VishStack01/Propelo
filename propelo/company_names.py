"""A company's real name for display: "Hpe" -> "HPE", "Cat (CaterpillarCareers)" -> "Caterpillar".

Hiring systems name boards by tenant codes and site names. The feed shows the company's own name; ids keep the
raw name so a role keeps its id."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_FILE = Path(__file__).resolve().parent / "data" / "company_domains.json"
# "(External)", "(CaterpillarCareers)", "(MarvellCareers2)", "(Only Use This One)": a board's site name, not the company.
_SITE_SUFFIX = re.compile(r"\s*\((?:[^()]*\b(?:careers?\d*|jobs?|external|internal|redeploy\w*|only|apply|production|private|crm|exteu\w*|site|portal)\b[^()]*|[A-Za-z]+\d*)\)\s*$", re.I)


@lru_cache(maxsize=1)
def _names() -> dict[str, str]:
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8")).get("names", {})
    except (OSError, ValueError):
        raw = {}
    return {k.lower(): v for k, v in raw.items()}


def display(company: str) -> str:
    name = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", company or "").strip()
    name = _SITE_SUFFIX.sub("", name).strip() or name
    return _names().get(name.lower(), name)
