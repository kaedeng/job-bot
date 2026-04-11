from __future__ import annotations

import re

from bot.models import Job

# --- Title filters ---

# Generic level/stage terms that don't imply discipline on their own
_LEVEL_TERMS = re.compile(
    r"\b(intern|internship|new\s*grad|university\s*grad|entry[\s-]*level)\b",
    re.IGNORECASE,
)

# Already discipline-specific — no extra check needed
_SWE_LEVEL_TERMS = re.compile(
    r"\bswe\s*i\b|\bsoftware\s*engineer\s*i\b|\bl3\b",
    re.IGNORECASE,
)

# Must appear alongside a generic level term to confirm SWE discipline
DISCIPLINE_INCLUDE = re.compile(
    r"\b(software|swe|engineer(ing)?|developer|dev|data|ml"
    r"|machine\s*learning|systems|platform|infrastructure"
    r"|backend|frontend|full[\s-]?stack|devops|security|cloud)\b",
    re.IGNORECASE,
)

TITLE_EXCLUDE = re.compile(
    r"\b(senior|staff|principal|manager|lead|sr\.)",
    re.IGNORECASE,
)

# --- Location filters ---

US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
}

US_STATE_ABBREVS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

US_CITIES = {
    "san francisco", "new york", "seattle", "austin", "chicago",
    "los angeles", "boston", "denver", "atlanta", "miami",
    "san jose", "palo alto", "mountain view", "menlo park",
    "sunnyvale", "cupertino", "redmond", "pittsburgh",
}

US_KEYWORDS = {"united states", "usa", "u.s.", "remote"}


def _is_us_location(location: str) -> bool:
    loc_lower = location.lower()

    if any(kw in loc_lower for kw in US_KEYWORDS):
        return True
    if any(state in loc_lower for state in US_STATES):
        return True
    if any(city in loc_lower for city in US_CITIES):
        return True

    # Check for state abbreviations like ", CA" or "(NY)"
    for abbrev in US_STATE_ABBREVS:
        if re.search(rf"\b{abbrev}\b", location):
            return True

    return False


def passes_filter(job: Job) -> bool:
    """Return True if the job matches entry-level/intern SWE criteria in the US."""
    if TITLE_EXCLUDE.search(job.title):
        return False
    if _SWE_LEVEL_TERMS.search(job.title):
        pass  # already discipline-specific (e.g. "Software Engineer I")
    elif _LEVEL_TERMS.search(job.title):
        if not DISCIPLINE_INCLUDE.search(job.title):
            return False  # e.g. "Marketing Intern" — not SWE
    else:
        return False
    if not _is_us_location(job.location):
        return False
    return True
