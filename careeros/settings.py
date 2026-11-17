"""Search settings, loaded from TOML. Every field has a safe default."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROLE_KEYWORDS = [
    "ai", "a.i.", "artificial intelligence", "genai", "gen ai", "generative", "llm", "agent", "agentic",
    "machine learning", "ml", "mlops", "applied scientist", "nlp", "computer vision", "prompt",
    "automation", "forward deployed", "data scientist", "ai product", "conversational", "rag",
]


@dataclass
class LocationPolicy:
    south_india: str = "any"  # "any" | "remote" | "never"
    rest_of_india: str = "remote"  # "any" | "remote" | "never"
    abroad: str = "remote"  # "remote" | "never"
    # When a remote role abroad doesn't say who can apply: keep it for a
    # human check (True) or skip it (False).
    keep_unclear_remote: bool = True
    # Where the person lives (ISO code). India uses the rules above; anywhere else, roles fit when
    # they're remote and open to that country or region, or on-site/hybrid in one of `places`.
    home: str = "IN"
    places: list = field(default_factory=list)
    remote_ok: bool = True


@dataclass
class Settings:
    max_required_years: float = 1
    max_posting_age_days: int = 25
    ghost_after_days: int = 60
    priority_within_hours: int = 48
    salary_floor_lpa: float | None = 7.0
    require_stated_pay: bool = False  # True: a role must state pay at or above the floor
    needs_sponsorship: bool = False  # True: on-site roles abroad must be able to sponsor a work visa
    usd_inr: float = 88.0
    role_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_ROLE_KEYWORDS))
    # Job families to keep (see tags.FAMILIES). Empty: decide by role keywords only.
    families: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    dealbreakers: list[str] = field(default_factory=list)
    company_blocklist: list[str] = field(default_factory=list)
    allow_internships: bool = True
    # The person's own years of experience, when they gave it. Experienced people don't see internships
    # or titles marked junior, fresher or trainee; None leaves those decisions to max_required_years alone.
    experience_years: float | None = None
    location: LocationPolicy = field(default_factory=LocationPolicy)
    daily_cap: int = 8
    reapply_cooldown_days: int = 180

    @classmethod
    def load(cls, path: str | Path | None) -> "Settings":
        s = cls()
        if not path or not Path(path).exists():
            return s
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        search = data.get("search", data)
        for key in (
            "max_required_years", "max_posting_age_days", "ghost_after_days", "priority_within_hours",
            "salary_floor_lpa", "usd_inr", "role_keywords", "title_exclude", "dealbreakers",
            "company_blocklist", "allow_internships", "daily_cap", "reapply_cooldown_days", "require_stated_pay", "needs_sponsorship", "families",
            "experience_years",
        ):
            if key in search:
                setattr(s, key, search[key])
        loc = data.get("location", {})
        for key in ("south_india", "rest_of_india", "abroad", "keep_unclear_remote"):
            if key in loc:
                setattr(s.location, key, loc[key])
        if s.salary_floor_lpa in (0, "", None):
            s.salary_floor_lpa = None
        return s
