"""Where is a role? Classifies location strings into south India, the rest of India, or abroad.

The default policy (configurable in settings.toml) is:
  * south India: any work mode
  * rest of India: remote only
  * abroad: remote only, and only when people based in India may apply
"""

from __future__ import annotations

import re
from functools import lru_cache

SOUTH_STATES = {"karnataka", "telangana", "andhra pradesh", "tamil nadu", "kerala", "puducherry", "pondicherry"}

SOUTH_CITIES = {
    # Karnataka
    "bengaluru", "bangalore", "banglore", "mysuru", "mysore", "mangaluru", "mangalore", "hubli", "hubballi", "dharwad",
    "belagavi", "belgaum", "udupi", "manipal", "electronic city", "whitefield", "koramangala", "hsr layout",
    # Telangana
    "hyderabad", "secunderabad", "warangal", "shamshabad", "gachibowli", "hitec city", "hitech city", "madhapur",
    # Tamil Nadu
    "chennai", "madras", "coimbatore", "madurai", "tiruchirappalli", "trichy", "salem", "tiruppur", "vellore",
    "erode", "hosur",
    # Kerala
    "kochi", "cochin", "ernakulam", "thiruvananthapuram", "trivandrum", "kozhikode", "calicut", "thrissur",
    "kannur", "palakkad", "technopark", "infopark",
    # Andhra Pradesh
    "visakhapatnam", "vizag", "vijayawada", "guntur", "tirupati", "nellore", "kakinada", "rajahmundry",
    "anantapur", "kurnool", "amaravati",
    # Puducherry
    "puducherry", "pondicherry",
}

OTHER_INDIA = {
    "delhi", "new delhi", "ncr", "delhi ncr", "gurgaon", "gurugram", "noida", "greater noida", "ghaziabad",
    "faridabad", "mumbai", "navi mumbai", "thane", "pune", "kolkata", "ahmedabad", "gandhinagar", "jaipur",
    "chandigarh", "mohali", "panchkula", "indore", "bhopal", "lucknow", "kanpur", "nagpur", "surat", "vadodara",
    "bhubaneswar", "patna", "dehradun", "goa", "panaji", "guwahati", "ranchi", "raipur", "amritsar", "ludhiana",
    "jalandhar", "varanasi", "nashik", "aurangabad", "maharashtra", "gujarat", "punjab", "haryana",
    "uttar pradesh", "rajasthan", "west bengal", "madhya pradesh", "bihar", "odisha", "assam",
    "ranjangaon", "sanand", "gift city", "morinda",
}

ABROAD_HINTS = re.compile(
    r"\b(united states|usa|u\.s\.|canada|united kingdom|uk|london|berlin|germany|france|paris|spain|netherlands|"
    r"amsterdam|ireland|dublin|poland|singapore|dubai|uae|australia|sydney|japan|tokyo|new york|nyc|san francisco|"
    r"sf|bay area|seattle|austin|boston|toronto|vancouver|remote[- ]us|emea|europe)\b",
    re.I,
)


@lru_cache(maxsize=16)
def _any(words: frozenset) -> re.Pattern:
    """One pattern for a whole word list: most locations name none of them, and one search says so."""
    return re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")(?![a-z])")


@lru_cache(maxsize=4096)
def _word(w: str) -> re.Pattern:
    return re.compile(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])")


def _has(words: set[str], text: str) -> str:
    """The longest word of `words` that stands alone in `text`, or ""."""
    if not _any(frozenset(words)).search(text):
        return ""
    for w in sorted(words, key=len, reverse=True):
        if _word(w).search(text):
            return w
    return ""


_SOUTH = frozenset(SOUTH_CITIES | SOUTH_STATES)
_OTHER = frozenset(OTHER_INDIA)
_INDIA = re.compile(r"\bindia\b")


@lru_cache(maxsize=65536)
def _classify(location: str) -> tuple[str, str, bool, bool]:
    # Boards repeat the same few thousand location strings across a hundred thousand roles.
    loc = location.lower()
    south = _has(_SOUTH, loc)
    other = _has(_OTHER, loc)
    india = bool(south or other or _INDIA.search(loc))
    abroad = bool(ABROAD_HINTS.search(location)) and not india
    return south, other, india, abroad


def classify(location: str) -> dict:
    """Which buckets does a location string touch?

    Multi-city postings ("Bengaluru, Delhi or Mumbai") touch several; the role
    passes the south-India rule if any listed city is in the south.
    """
    south, other, india, abroad = _classify(location or "")
    return {"south": south, "other_india": other, "india": india, "abroad": abroad}
