"""Countries and regions, for people searching from outside India.

Matching for someone in India keeps its own, richer rules (south India, the rest of India, remote
roles open to India). For everyone else, a role fits when it's remote and open to their country or
region, or on-site or hybrid in a place they listed.
"""

from __future__ import annotations

import re
from functools import lru_cache

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


# Where most Indian students go for a master's and then look for work, largest first (MEA figures for 2025),
# plus the places graduates commonly move on to. Roles here are kept ahead of the rest of the world when the
# feed has to be trimmed, and boards with roles here are worth scanning even with nothing in India.
STUDY = ("CA", "US", "AE", "AU", "GB", "DE", "IE", "NZ", "NL", "FR", "SG")

# "Austin, TX", "Toronto, ON", "Sydney NSW": most postings in these countries never name the country.
US_STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
             "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
             "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
             "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
             "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
             "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
             "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
             "WY": "Wyoming", "DC": "District of Columbia"}
CA_PROVINCES = {"ON": "Ontario", "BC": "British Columbia", "QC": "Quebec", "AB": "Alberta", "MB": "Manitoba", "SK": "Saskatchewan",
                "NS": "Nova Scotia", "NB": "New Brunswick", "NL": "Newfoundland", "PE": "Prince Edward Island"}
AU_STATES = {"NSW": "New South Wales", "VIC": "Victoria", "QLD": "Queensland", "WA": "Western Australia", "SA": "South Australia",
             "TAS": "Tasmania", "ACT": "Australian Capital Territory", "NT": "Northern Territory"}
MORE_CITIES: dict[str, list[str]] = {
    "US": ["Sunnyvale", "Mountain View", "Palo Alto", "San Jose", "Santa Clara", "Menlo Park", "Redwood City", "Cupertino", "San Diego", "Irvine",
           "Portland", "Phoenix", "Dallas", "Houston", "Philadelphia", "Pittsburgh", "Detroit", "Minneapolis", "Raleigh", "Durham", "Charlotte",
           "Nashville", "Salt Lake City", "Columbus", "Cincinnati", "Cleveland", "St. Louis", "Kansas City", "Baltimore", "Arlington",
           "Reston", "McLean", "Bellevue", "Redmond", "Brooklyn", "Jersey City", "Boulder", "Tampa", "Orlando", "Las Vegas", "Indianapolis"],
    "CA": ["Waterloo", "Kitchener", "Mississauga", "Edmonton", "Winnipeg", "Halifax", "Quebec City", "Markham", "Burnaby"],
    "GB": ["Birmingham", "Leeds", "Glasgow", "Bristol", "Liverpool", "Sheffield", "Newcastle", "Nottingham", "Cardiff", "Belfast", "Oxford",
           "Reading", "Milton Keynes", "Southampton", "Leicester", "Coventry", "Aberdeen"],
    "DE": ["Stuttgart", "Cologne", "Köln", "Düsseldorf", "Dusseldorf", "Leipzig", "Dresden", "Nuremberg", "Nürnberg", "Hanover", "Hannover",
           "Bonn", "Karlsruhe", "Mannheim", "Aachen", "Darmstadt", "Heidelberg", "Bremen", "Essen", "Dortmund"],
    "AU": ["Perth", "Adelaide", "Canberra", "Gold Coast", "Hobart"], "NZ": ["Auckland", "Wellington", "Christchurch"],
    "IE": ["Cork", "Galway", "Limerick"], "NL": ["The Hague", "Utrecht", "Eindhoven", "Delft", "Groningen"],
    "FR": ["Lyon", "Toulouse", "Marseille", "Lille", "Nantes", "Bordeaux", "Grenoble", "Sophia Antipolis"],
    "AE": ["Sharjah"], "IT": ["Milan", "Rome", "Turin"], "CZ": ["Prague", "Brno"], "RO": ["Bucharest", "Cluj"], "IL": ["Tel Aviv"],
    "KR": ["Seoul"], "MY": ["Kuala Lumpur", "Penang"], "TH": ["Bangkok"], "CO": ["Bogota", "Bogotá", "Medellín", "Medellin"],
    "QA": ["Doha"], "BH": ["Manama"], "HU": ["Budapest"], "AT": ["Vienna"], "BE": ["Brussels"], "DK": ["Copenhagen"], "FI": ["Helsinki"],
    "NO": ["Oslo"], "ES": ["Valencia"], "PT": [], "CH": ["Basel", "Lausanne"], "SE": ["Gothenburg", "Malmö"], "JP": ["Osaka"],
    "CN": ["Shanghai", "Beijing", "Shenzhen"], "PH": ["Manila"], "ID": ["Jakarta"], "VN": ["Ho Chi Minh", "Hanoi"], "TR": ["Istanbul"],
    "EG": ["Cairo"], "SA": ["Riyadh", "Jeddah"], "ZA": ["Cape Town", "Johannesburg"], "KE": ["Nairobi"], "NG": ["Lagos"],
}
EXTRA_NAMES = {"QA": ["Qatar"], "BH": ["Bahrain"], "KW": ["Kuwait"], "OM": ["Oman"], "LU": ["Luxembourg"], "JO": ["Jordan"], "LB": ["Lebanon"],
               "MA": ["Morocco"], "SK": ["Slovakia"], "SI": ["Slovenia"], "IS": ["Iceland"], "MT": ["Malta"], "CY": ["Cyprus"]}

# The long tail, taken from locations in the live feed that named no country the tables above knew. A remote
# role placed in one of these ("Almaty, Kazakhstan", "Belgrade", "NYC") is hired there, so someone living
# elsewhere should not be shown it. "Georgia" is left out on purpose: it is more often the US state.
EXTRA_NAMES.update({
    "KZ": ["Kazakhstan"], "BY": ["Belarus"], "BA": ["Bosnia and Herzegovina", "Bosnia"], "MK": ["North Macedonia"], "AL": ["Albania"],
    "ME": ["Montenegro"], "MD": ["Moldova"], "AM": ["Armenia"], "AZ": ["Azerbaijan"], "UZ": ["Uzbekistan"], "RU": ["Russia"], "GI": ["Gibraltar"],
    "HN": ["Honduras"], "PA": ["Panama"], "JM": ["Jamaica"], "BZ": ["Belize"], "SV": ["El Salvador"], "GT": ["Guatemala"], "EC": ["Ecuador"],
    "BO": ["Bolivia"], "DO": ["Dominican Republic"], "PY": ["Paraguay"], "VE": ["Venezuela"], "PR": ["Puerto Rico"], "SR": ["Suriname"],
    "SN": ["Senegal"], "TN": ["Tunisia"], "DZ": ["Algeria"], "ET": ["Ethiopia"], "GH": ["Ghana"], "UG": ["Uganda"], "MW": ["Malawi"],
    "TZ": ["Tanzania"], "RW": ["Rwanda"], "ZM": ["Zambia"], "ZW": ["Zimbabwe"], "CM": ["Cameroon"], "MU": ["Mauritius"],
    "KH": ["Cambodia"], "MM": ["Myanmar"], "MN": ["Mongolia"], "IQ": ["Iraq"],
    # Names in the country's own language, as its job boards write them.
    "BR": ["Brasil"], "CH": ["Schweiz", "Suisse"], "ES": ["España"], "IT": ["Italia"], "MX": ["México"], "BE": ["Belgique", "België"],
    "NL": ["Nederland"], "AT": ["Österreich"], "PL": ["Polska"],
})
for _code, _cities in {
    "US": ["NYC", "Manhattan", "Bay Area", "SF", "Washington, D.C.", "Washington D.C.", "Washington DC", "San Mateo", "Fremont", "Emeryville",
           "El Segundo", "Long Beach", "Oakland", "Scottsdale", "Santa Barbara", "Ann Arbor", "Los Altos", "Pleasanton", "Santa Monica"],
    "GB": ["Brighton", "Guildford", "Exeter", "Norwich", "Swindon", "Dundee", "Swansea"],
    "DE": ["Augsburg", "Mainz", "Passau", "Ulm", "Regensburg", "Wiesbaden", "Würzburg", "Freiburg", "Landshut", "Reutlingen", "Bamberg",
           "Pforzheim", "Münster", "Kiel", "Potsdam"],
    "LT": ["Vilnius", "Kaunas"], "FI": ["Espoo", "Tampere"], "UA": ["Kyiv", "Lviv", "Kharkiv"], "KZ": ["Almaty", "Astana"], "BG": ["Sofia"],
    "RS": ["Belgrade", "Novi Sad"], "BY": ["Minsk"], "EE": ["Tallinn"], "LV": ["Riga"], "SK": ["Bratislava"], "SI": ["Ljubljana"],
    "TW": ["Taipei"], "AR": ["Buenos Aires"], "PH": ["Makati", "Cebu"], "MA": ["Rabat", "Casablanca"], "TN": ["Tunis"], "HR": ["Zagreb"],
    "GR": ["Athens", "Thessaloniki"], "CH": ["Bern", "St. Gallen", "Zug"], "BE": ["Leuven", "Ghent", "Antwerp"], "CY": ["Limassol", "Nicosia"],
    "MK": ["Skopje"], "IL": ["Kfar Saba", "TLV", "Haifa", "Herzliya"], "MX": ["Ciudad de México", "Guadalajara", "Monterrey"],
    "IT": ["Milano", "Roma", "Bologna"], "PL": ["Gdańsk", "Gdansk", "Poznań", "Poznan", "Katowice", "Łódź"], "JP": ["Yokohama", "Kyoto"],
    "CN": ["Suzhou", "Hangzhou", "Guangzhou"], "BR": ["Campinas", "São Carlos", "Rio de Janeiro", "Belo Horizonte", "Curitiba"],
    "RO": ["Iași", "Timișoara"], "PT": ["Braga", "Coimbra"], "ES": ["Málaga", "Malaga", "Sevilla", "Seville", "Bilbao"], "DK": ["Aarhus"],
    "NO": ["Bergen", "Trondheim"], "SE": ["Uppsala", "Lund"], "AT": ["Graz", "Linz"],
}.items():
    MORE_CITIES[_code] = MORE_CITIES.get(_code, []) + _cities
NAMES.update({k: v for k, v in EXTRA_NAMES.items() if k not in NAMES})

_MORE: dict[str, re.Pattern] = {}
for _code in set(MORE_CITIES) | set(EXTRA_NAMES):
    _w = MORE_CITIES.get(_code, []) + EXTRA_NAMES.get(_code, [])
    if _w:
        _MORE[_code] = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(w) for w in _w) + r")(?![A-Za-z])", re.I)
# A two-letter state after a comma or dash ("Austin, TX", "Remote - CA" is left alone: it could be Canada),
# or the state's full name. Postal abbreviations are matched in capitals only.
_US_ABBR = re.compile(r",\s?(" + "|".join(US_STATES) + r")(?![A-Za-z])(?:\s+\d{5})?")
_US_NAME = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(n) for n in US_STATES.values() if n not in ("Georgia", "Washington")) + r")(?![A-Za-z])", re.I)
_CA_ABBR = re.compile(r",\s?(" + "|".join(CA_PROVINCES) + r")(?![A-Za-z])")
_CA_NAME = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(n) for n in CA_PROVINCES.values()) + r")(?![A-Za-z])", re.I)
_AU_ABBR = re.compile(r"(?:,\s?|\s)(NSW|VIC|QLD|TAS|ACT)(?![A-Za-z])")
_AU_NAME = re.compile(r"(?<![A-Za-z])(New South Wales|Queensland|Tasmania|Western Australia|South Australia)(?![A-Za-z])", re.I)
_IN_CODE = re.compile(r"(?<![A-Za-z])IND?(?![A-Za-z])\s?[-,]|,\s?IND?$|(?<![A-Za-z])IND(?![A-Za-z])")


_PARTS = re.compile(r"\s*(?:;|\||/|\bor\b)\s*")


_TOWN_BEFORE_STATE = re.compile(r"[^,;()]+,\s*(?=(?:" + "|".join(re.escape(n) for n in US_STATES.values() if n not in ("Georgia", "Washington", "New York"))
                                + r")(?![A-Za-z]))", re.I)


_COUNTRY_WORDS = {n.lower() for names in list(NAMES.values()) + list(EXTRA_NAMES.values()) for n in names}
_ANY_STATE = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(n) for n in US_STATES.values()) + r")(?![A-Za-z])", re.I)


def resolve(location: str) -> set[str]:
    """Countries a location is in, including the ones it doesn't name: Indian cities and states, US states
    ("Austin, TX"), Canadian provinces, Australian states and well-known cities. `named` is the strict
    version; this one is for deciding where a role is. Each place in a list is read on its own."""
    return set(_resolve(location or ""))


@lru_cache(maxsize=65536)
def _resolve(location: str) -> frozenset[str]:
    out: set[str] = set()
    for part in _PARTS.split(location):
        if part.strip():
            out |= _resolve_one(part)
    return frozenset(out)


def _resolve_one(t: str) -> set[str]:
    from . import geo
    # The town before a written-out state is in that state: "Belgrade, Montana" and "Athens, Ohio" are not
    # Serbia and Greece. ("New York" is left to the city tables: in "London, New York" it is a second place.)
    state = _US_NAME.search(t)
    src = t
    if state:
        parts = [x for x in t.split(",") if x.strip()]
        # Only when the string reads as "town, state" pairs. In "Palo Alto, Toronto, Virginia, Miami" the
        # places are a flat list and Toronto is still Toronto.
        if 2 * sum(1 for x in parts if _ANY_STATE.search(x)) >= len(parts) - 1:
            src = _TOWN_BEFORE_STATE.sub(lambda m: m.group(0) if m.group(0).strip(" ,").lower() in _COUNTRY_WORDS else "", t)
    out = set(named(src))
    for code, rx in _MORE.items():
        if code not in out and rx.search(src):
            out.add(code)
    india = geo.classify(t)["india"]
    if india or (_IN_CODE.search(t) and not out):
        out.add("IN")
    if _CA_ABBR.search(t) or _CA_NAME.search(t):
        out.add("CA")
    if _AU_ABBR.search(t) or _AU_NAME.search(t):
        out.add("AU")
    m = _US_ABBR.search(t)
    if m:
        st = m.group(1)
        # ", IN" after an Indian city is India, ", DE" after a German one Germany, ", WA" after Perth Western Australia.
        if st == "IN" and re.search(r"remote", t, re.I):
            return {"IN"}
        if not ((st == "IN" and india) or (st == "DE" and "DE" in out) or (st == "WA" and "AU" in out) or (st == "CA" and "CA" in out)):
            return {"US"}  # "Cambridge, MA", "Dublin, CA", "Birmingham, AL": the state settles it
    elif state:
        out.add("US")
    return out


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
