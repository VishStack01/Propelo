"""Countries and regions, for people searching from outside India.

Matching for someone in India keeps its own, richer rules (south India, the rest of India, remote
roles open to India). For everyone else, a role fits when it's remote and open to their country or
region, or on-site or hybrid in a place they listed.
"""

from __future__ import annotations

import re

# ISO code -> names and common spellings in job locations. Ordered roughly by how often they appear.
NAMES: dict[str, list[str]] = {
    "US": ["United States", "USA", "U.S.", "US", "America"], "CA": ["Canada"], "GB": ["United Kingdom", "UK", "U.K.", "England", "Scotland", "Wales", "Great Britain"],
    "DE": ["Germany", "Deutschland"], "PL": ["Poland"], "NL": ["Netherlands", "Holland"], "ES": ["Spain"], "FR": ["France"], "PT": ["Portugal"],
    "IE": ["Ireland"], "IT": ["Italy"], "SE": ["Sweden"], "DK": ["Denmark"], "FI": ["Finland"], "NO": ["Norway"], "CH": ["Switzerland"],
    "AT": ["Austria"], "BE": ["Belgium"], "CZ": ["Czech Republic", "Czechia"], "RO": ["Romania"], "HU": ["Hungary"], "GR": ["Greece"],
    "UA": ["Ukraine"], "EE": ["Estonia"], "LT": ["Lithuania"], "LV": ["Latvia"], "BG": ["Bulgaria"], "HR": ["Croatia"], "RS": ["Serbia"],
    "TR": ["Turkey", "Türkiye"], "IL": ["Israel"], "AE": ["United Arab Emirates", "UAE", "Dubai", "Abu Dhabi"], "SA": ["Saudi Arabia"],
    "EG": ["Egypt"], "ZA": ["South Africa"], "NG": ["Nigeria"], "KE": ["Kenya"],
    "IN": ["India"], "SG": ["Singapore"], "AU": ["Australia"], "NZ": ["New Zealand"], "JP": ["Japan"], "KR": ["South Korea", "Korea"],
    "PH": ["Philippines"], "MY": ["Malaysia"], "ID": ["Indonesia"], "VN": ["Vietnam"], "TH": ["Thailand"], "HK": ["Hong Kong"], "TW": ["Taiwan"],
    "PK": ["Pakistan"], "BD": ["Bangladesh"], "LK": ["Sri Lanka"], "NP": ["Nepal"], "CN": ["China"],
    "MX": ["Mexico"], "BR": ["Brazil"], "AR": ["Argentina"], "CO": ["Colombia"], "CL": ["Chile"], "PE": ["Peru"], "UY": ["Uruguay"], "CR": ["Costa Rica"],
}

EUROPE = {"GB", "DE", "PL", "NL", "ES", "FR", "PT", "IE", "IT", "SE", "DK", "FI", "NO", "CH", "AT", "BE", "CZ", "RO", "HU", "GR", "UA", "EE", "LT", "LV", "BG", "HR", "RS"}
AMERICAS = {"US", "CA", "MX", "BR", "AR", "CO", "CL", "PE", "UY", "CR"}
APAC = {"IN", "SG", "AU", "NZ", "JP", "KR", "PH", "MY", "ID", "VN", "TH", "HK", "TW", "PK", "BD", "LK", "NP", "CN"}
EMEA = EUROPE | {"TR", "IL", "AE", "SA", "EG", "ZA", "NG", "KE"}

# Big cities that stand for their country in a location string ("Remote - Toronto").
CITIES: dict[str, list[str]] = {
    "US": ["New York", "San Francisco", "Seattle", "Austin", "Boston", "Chicago", "Los Angeles", "Denver", "Atlanta", "Miami", "Washington, DC"],
    "CA": ["Toronto", "Vancouver", "Montreal", "Ottawa", "Calgary"], "GB": ["London", "Manchester", "Edinburgh", "Cambridge"],
    "DE": ["Berlin", "Munich", "Hamburg", "Frankfurt"], "NL": ["Amsterdam", "Rotterdam"], "FR": ["Paris"], "ES": ["Madrid", "Barcelona"],
    "PL": ["Warsaw", "Krakow", "Kraków", "Wroclaw"], "IE": ["Dublin"], "PT": ["Lisbon", "Porto"], "SE": ["Stockholm"], "CH": ["Zurich", "Zürich", "Geneva"],
    "AU": ["Sydney", "Melbourne", "Brisbane"], "SG": [], "JP": ["Tokyo"], "AE": [], "BR": ["São Paulo", "Sao Paulo"], "MX": ["Mexico City"],
}

_RX: dict[str, re.Pattern] = {}
for _code, _names in NAMES.items():
    words = _names + CITIES.get(_code, [])
    # "US" and "UK" only as whole words in capitals, so "us" in prose doesn't count.
    parts = [re.escape(w) if w not in ("US", "UK") else rf"(?-i:{w})" for w in words]
    _RX[_code] = re.compile(r"(?<![A-Za-z])(" + "|".join(parts) + r")(?![A-Za-z])", re.I)


def named(text: str) -> set[str]:
    """Countries a location or title names."""
    t = text or ""
    return {code for code, rx in _RX.items() if rx.search(t)}


def name_of(code: str) -> str:
    return NAMES.get((code or "").upper(), [code])[0]


def in_region(code: str, scope: str) -> bool | None:
    """Is someone in `code` covered by a remote scope from extract.remote_scope? None when unknown."""
    code = (code or "").upper()
    return {"worldwide": True, "india": code == "IN", "us": code == "US", "americas": code in AMERICAS,
            "europe": code in EUROPE, "apac": code in APAC, "emea": code in EMEA}.get(scope)


# Rough standard offsets from UTC, used when a posting asks for a time-zone range.
OFFSETS = {"IN": 5.5, "US": -5, "CA": -5, "GB": 0, "IE": 0, "PT": 0, "DE": 1, "PL": 1, "NL": 1, "ES": 1, "FR": 1, "IT": 1, "SE": 1, "DK": 1, "NO": 1,
           "CH": 1, "AT": 1, "BE": 1, "CZ": 1, "HU": 1, "HR": 1, "RS": 1, "FI": 2, "RO": 2, "GR": 2, "UA": 2, "EE": 2, "LT": 2, "LV": 2, "BG": 2,
           "TR": 3, "IL": 2, "AE": 4, "SA": 3, "EG": 2, "ZA": 2, "NG": 1, "KE": 3, "SG": 8, "AU": 10, "NZ": 12, "JP": 9, "KR": 9, "PH": 8, "MY": 8,
           "ID": 7, "VN": 7, "TH": 7, "HK": 8, "TW": 8, "PK": 5, "BD": 6, "LK": 5.5, "NP": 5.75, "CN": 8, "MX": -6, "BR": -3, "AR": -3, "CO": -5,
           "CL": -4, "PE": -5, "UY": -3, "CR": -6}
