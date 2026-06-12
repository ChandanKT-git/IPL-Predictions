"""Deterministic mapping between Cricbuzz identifiers and internal IDs.

Used by ``DataResolver`` to translate Cricbuzz squad / venue payloads
into the ten Internal_Team_Ids and ten Internal_Venue_Ids the rest of
the application speaks. All public functions are pure and total: lookup
misses surface as ``None`` so the resolver can fall back deterministically.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Team mapping tables
# ---------------------------------------------------------------------------

TEAM_NAME_ALIASES: dict[str, list[str]] = {
    "mi":   ["Mumbai Indians", "MI"],
    "csk":  ["Chennai Super Kings", "CSK"],
    "rcb":  ["Royal Challengers Bengaluru", "Royal Challengers Bangalore", "RCB"],
    "kkr":  ["Kolkata Knight Riders", "KKR"],
    "dc":   ["Delhi Capitals", "Delhi Daredevils", "DC", "DD"],
    "pbks": ["Punjab Kings", "Kings XI Punjab", "PBKS", "KXIP"],
    "rr":   ["Rajasthan Royals", "RR"],
    "srh":  ["Sunrisers Hyderabad", "Deccan Chargers", "SRH"],
    "gt":   ["Gujarat Titans", "Gujarat Lions", "GT"],
    "lsg":  ["Lucknow Super Giants", "Rising Pune Supergiant",
             "Rising Pune Supergiants", "Pune Warriors",
             "Kochi Tuskers Kerala", "LSG"],
}

CRICBUZZ_TEAM_ID_OVERRIDES: dict[int, str] = {}


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def to_internal_team_id(cricbuzz_team_id: Optional[int], name: str) -> Optional[str]:
    if cricbuzz_team_id is not None:
        try:
            override = CRICBUZZ_TEAM_ID_OVERRIDES.get(int(cricbuzz_team_id))
        except (TypeError, ValueError):
            override = None
        if override is not None:
            return override

    needle = _normalize(name)
    if not needle:
        return None
    for internal_id, aliases in TEAM_NAME_ALIASES.items():
        for alias in aliases:
            if _normalize(alias) == needle:
                return internal_id
    return None


def to_cricbuzz_name(internal_id: str) -> Optional[str]:
    aliases = TEAM_NAME_ALIASES.get(_normalize(internal_id))
    if not aliases:
        return None
    return aliases[0]


# ---------------------------------------------------------------------------
# Venue mapping tables
# ---------------------------------------------------------------------------

VENUE_FROM_CRICBUZZ: list[tuple[str, str, str]] = [
    ("Wankhede",          "Mumbai",     "wankhede"),
    ("Chinnaswamy",       "Bengaluru",  "chinnaswamy"),
    ("Chinnaswamy",       "Bangalore",  "chinnaswamy"),
    ("Eden Gardens",      "Kolkata",    "eden"),
    ("MA Chidambaram",    "Chennai",    "chepauk"),
    ("M. A. Chidambaram", "Chennai",    "chepauk"),
    ("Chidambaram",       "Chennai",    "chepauk"),
    ("Narendra Modi",     "Ahmedabad",  "narendramodi"),
    ("Arun Jaitley",      "Delhi",      "arunjaitley"),
    ("Feroz Shah Kotla",  "Delhi",      "arunjaitley"),
    ("PCA",               "Mohali",     "mohali"),
    ("Punjab Cricket",    "Mohali",     "mohali"),
    ("IS Bindra",         "Mohali",     "mohali"),
    ("Sawai Mansingh",    "Jaipur",     "sawaimansingh"),
    ("Rajiv Gandhi",      "Hyderabad",  "rajivgandhi"),
    ("Ekana",             "Lucknow",    "ekana"),
    ("Atal Bihari",       "Lucknow",    "ekana"),
]


def to_internal_venue_id(ground: str, city: str) -> Optional[str]:
    g = _normalize(ground)
    c = _normalize(city)
    if not g or not c:
        return None
    for ground_sub, expected_city, internal_id in VENUE_FROM_CRICBUZZ:
        if _normalize(expected_city) != c:
            continue
        if _normalize(ground_sub) in g:
            return internal_id
    return None


_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slug_ground(ground: str) -> str:
    """Return a URL-safe slug derived from a Cricbuzz ground name."""
    if not isinstance(ground, str):
        return ""
    return _SLUG_NON_ALNUM.sub("-", ground.lower()).strip("-")
