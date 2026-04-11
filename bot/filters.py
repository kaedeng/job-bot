from __future__ import annotations

import re

from bot.models import Job

# --- Title filters ---

# Intern signals in title
_INTERN_TITLE = re.compile(
    r"\b(intern(?:ship)?|co[\s-]?op)\b",
    re.IGNORECASE,
)

# New-grad / entry-level signals in title — includes explicit level markers and
# junior variants that often appear without saying "entry level"
_NEW_GRAD_TITLE = re.compile(
    r"\b(new\s*grad(?:uate)?|university\s*grad(?:uate)?|entry[\s-]*level"
    r"|junior|jr\.?|associate(?:\s+engineer)?|early[\s-]*career"
    r"|campus\s+(?:hire|recruit)|swe\s*[i1]\b|software\s+engineer\s+[i1]\b|l3)\b",
    re.IGNORECASE,
)

# Broad tech discipline check — storage gate (is_tech_job).
# Covers both SWE and EE so both get stored in job_postings.
DISCIPLINE_INCLUDE = re.compile(
    r"\b(software|swe|engineer(ing)?|developer|dev|data|ml"
    r"|machine\s*learning|systems|platform|infrastructure"
    r"|backend|frontend|full[\s-]?stack|devops|security|cloud"
    r"|electrical|hardware|embedded|firmware|fpga|asic|vlsi|pcb"
    r"|rf|analog|circuit|semiconductor|silicon|photonics)\b",
    re.IGNORECASE,
)

# Discipline-specific regexes for classify_discipline()
_SWE_DISCIPLINE = re.compile(
    r"\b(software|swe|developer|dev|backend|frontend|full[\s-]?stack"
    r"|devops|web|mobile|ios|android|ml|machine\s*learning|ai|cloud"
    r"|platform|infrastructure|security|data\s+engineer|data\s+scientist)\b",
    re.IGNORECASE,
)

_EE_DISCIPLINE = re.compile(
    r"\b(electrical|hardware|embedded|firmware|fpga|asic|vlsi|pcb"
    r"|rf|analog|circuit|semiconductor|silicon|photonics|ee\b)\b",
    re.IGNORECASE,
)

TITLE_EXCLUDE = re.compile(
    r"\b(senior|staff|principal|manager|lead|sr\.)",
    re.IGNORECASE,
)

# --- Description classifiers ---

# Intern signals in description
_INTERN_DESC = re.compile(
    r"\b(intern(?:ship)?|co[\s-]?op)\b",
    re.IGNORECASE,
)

# New-grad / entry-level signals in description
_NEW_GRAD_DESC = re.compile(
    r"(new\s*grad(?:uate)?|recent\s*grad(?:uate)?|entry[\s-]*level"
    r"|0\s*[-–to]+\s*[23]\s*years?"
    r"|no\s+(?:prior\s+)?(?:professional\s+)?experience\s+required"
    r"|early[\s-]*career|fresh(?:er|man)?)",
    re.IGNORECASE,
)

# Senior experience requirement — if description demands 4+ years, exclude
_SENIOR_EXP = re.compile(
    r"\b([4-9]|\d{2})\+?\s*(?:or\s+more\s+)?years?\s+of\s+(?:\w+\s+)?experience",
    re.IGNORECASE,
)

# --- Location filters ---

US_STATES = {
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
}

US_STATE_ABBREVS = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}

US_CITIES = {
    "san francisco",
    "new york",
    "seattle",
    "austin",
    "chicago",
    "los angeles",
    "boston",
    "denver",
    "atlanta",
    "miami",
    "san jose",
    "palo alto",
    "mountain view",
    "menlo park",
    "sunnyvale",
    "cupertino",
    "redmond",
    "pittsburgh",
}

US_KEYWORDS = {"united states", "usa", "u.s.", "remote"}

# Full US state name -> abbreviation (used in parse_location)
_STATE_TO_ABBREV: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}

# International country name/variant -> ISO 3166-1 alpha-2 code.
# Ordered so that longer/more-specific strings are checked before shorter ones
# (e.g. "united kingdom" before "uk" to avoid false matches on "ukraine").
_COUNTRY_TO_CODE: dict[str, str] = {
    # Europe
    "united kingdom": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "germany": "DE",
    "france": "FR",
    "netherlands": "NL",
    "the netherlands": "NL",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "switzerland": "CH",
    "austria": "AT",
    "belgium": "BE",
    "ireland": "IE",
    "spain": "ES",
    "portugal": "PT",
    "italy": "IT",
    "poland": "PL",
    "czech republic": "CZ",
    "czechia": "CZ",
    "romania": "RO",
    "hungary": "HU",
    "ukraine": "UA",
    "estonia": "EE",
    "latvia": "LV",
    "lithuania": "LT",
    "luxembourg": "LU",
    "iceland": "IS",
    "greece": "GR",
    "turkey": "TR",
    # Americas (non-US)
    "canada": "CA",
    "mexico": "MX",
    "brazil": "BR",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "peru": "PE",
    # Asia-Pacific
    "australia": "AU",
    "new zealand": "NZ",
    "japan": "JP",
    "south korea": "KR",
    "korea": "KR",
    "china": "CN",
    "india": "IN",
    "singapore": "SG",
    "hong kong": "HK",
    "taiwan": "TW",
    "israel": "IL",
    "uae": "AE",
    "united arab emirates": "AE",
    # Abbreviations — checked last to avoid shadowing full names
    "uk": "GB",
}


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


def is_tech_job(job: Job) -> bool:
    """Return True if the job title contains any tech discipline keyword (SWE or EE).

    Used as a lightweight pre-filter before storing to job_postings — rejects
    clearly non-tech roles (e.g. "Chef", "HR Manager") that happen to appear on
    a curated company's board.
    """
    return bool(DISCIPLINE_INCLUDE.search(job.title))


def classify_discipline(job: Job) -> str:
    """Classify a job's engineering discipline from its title.

    A job can match multiple disciplines. Returns a comma-separated string of
    matched disciplines, or "unknown" if neither signal is present.

    Returns:
        "swe"     — only software engineering signals
        "ee"      — only electrical/hardware engineering signals
        "swe,ee"  — both signals present (e.g. "Embedded Software Engineer")
        "unknown" — title has neither clear SWE nor EE signal
    """
    disciplines = []
    if _SWE_DISCIPLINE.search(job.title):
        disciplines.append("swe")
    if _EE_DISCIPLINE.search(job.title):
        disciplines.append("ee")
    return ",".join(disciplines) if disciplines else "unknown"


def parse_location(location: str) -> tuple[str | None, str | None, str | None]:
    """Parse a raw location string into (country, state, city).

    Returns a 3-tuple of nullable strings. Best-effort: fields that can't be
    inferred are returned as None.

    Examples:
        "San Francisco, CA"              -> ("US", "CA", "San Francisco")
        "Remote"                         -> ("US", None, None)
        "New York, NY"                   -> ("US", "NY", "New York")
        "Warsaw, Masovian Voivodeship, Poland" -> ("PL", None, "Warsaw")
        "London, UK"                     -> ("GB", None, "London")
        "Toronto, ON, Canada"            -> ("CA", None, "Toronto")
        ""                               -> (None, None, None)
    """
    loc = location.strip()
    if not loc:
        return None, None, None

    loc_lower = loc.lower()

    # --- US detection ---
    is_us = (
        any(kw in loc_lower for kw in US_KEYWORDS)
        or any(state in loc_lower for state in US_STATES)
        or any(city in loc_lower for city in US_CITIES)
        or any(re.search(rf"\b{abbrev}\b", loc) for abbrev in US_STATE_ABBREVS)
    )

    if is_us:
        country: str | None = "US"

        # State abbreviation first (e.g. ", CA" or "(NY)")
        state: str | None = None
        for abbrev in US_STATE_ABBREVS:
            if re.search(rf"\b{abbrev}\b", loc):
                state = abbrev
                break

        # Fall back to full state name
        if state is None:
            for name, abbrev in _STATE_TO_ABBREV.items():
                if name in loc_lower:
                    state = abbrev
                    break

        # City — known set first, then first comma segment
        city: str | None = None
        for known_city in US_CITIES:
            if known_city in loc_lower:
                city = known_city.title()
                break
        if city is None and "," in loc:
            candidate = loc.split(",")[0].strip()
            if candidate.lower() not in US_STATES and candidate not in US_STATE_ABBREVS:
                city = candidate or None

        return country, state, city

    # --- International detection ---
    # Check longest keys first so "united kingdom" matches before "uk"
    country = None
    for name, code in sorted(_COUNTRY_TO_CODE.items(), key=lambda x: len(x[0]), reverse=True):
        if name in loc_lower:
            country = code
            break

    # City is almost always the first comma-separated segment
    city = None
    if "," in loc:
        candidate = loc.split(",")[0].strip()
        if candidate:
            city = candidate
    elif country is None:
        # Single-token location with no recognised country (e.g. "Remote - EMEA")
        pass

    return country, None, city


_IS_REMOTE = re.compile(r"\bremote\b", re.IGNORECASE)


def parse_locations(location_raw: str) -> list[dict]:
    """Parse a raw location string into a list of location dicts.

    Splits on semicolons for multi-location postings. Each dict has:
        country (str|None), state (str|None), city (str|None), is_remote (bool)

    Examples:
        "San Francisco, CA"
            -> [{"country":"US","state":"CA","city":"San Francisco","is_remote":False}]
        "London, UK; Remote-Friendly, United States; San Francisco, CA"
            -> [{"country":"GB",...,"is_remote":False},
                {"country":"US",...,"is_remote":True},
                {"country":"US","state":"CA","city":"San Francisco","is_remote":False}]
    """
    if not location_raw.strip():
        return []

    segments = [s.strip() for s in location_raw.split(";") if s.strip()]
    if not segments:
        segments = [location_raw.strip()]

    results = []
    for seg in segments:
        country, state, city = parse_location(seg)
        results.append(
            {
                "country": country,
                "state": state,
                "city": city,
                "is_remote": bool(_IS_REMOTE.search(seg)),
            }
        )
    return results


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def classify_job(job: Job) -> tuple[bool, bool]:
    """Classify a job as intern and/or new-grad.

    Returns:
        (is_intern, is_new_grad) — both can be True for combined postings.

    Priority:
        1. Source trust — Simplify repos are pre-curated; trust the list name directly.
        2. Title signals — fast, always available.
        3. Description signals — richer but optional; skipped when description is absent.
    """
    # 1. Source-level trust (Simplify repos are already curated by type)
    if job.source == "simplify-intern":
        return True, False
    if job.source == "simplify-newgrad":
        return False, True

    is_intern = bool(_INTERN_TITLE.search(job.title))
    is_new_grad = bool(_NEW_GRAD_TITLE.search(job.title))

    # 2. Description scanning (HTML stripped before matching)
    if job.description:
        desc = _strip_html(job.description)
        if _SENIOR_EXP.search(desc):
            # Description explicitly asks for 4+ years — not entry level
            return False, False
        if not is_intern and _INTERN_DESC.search(desc):
            is_intern = True
        if not is_new_grad and _NEW_GRAD_DESC.search(desc):
            is_new_grad = True

    return is_intern, is_new_grad


def passes_filter(job: Job) -> bool:
    """Return True if the job is an entry-level/intern SWE role in the US."""
    if TITLE_EXCLUDE.search(job.title):
        return False

    is_intern, is_new_grad = classify_job(job)
    if not (is_intern or is_new_grad):
        return False

    # Entry-level roles must be CS-discipline when classification came from title alone
    # (guards against "Marketing Intern" slipping through on description signals)
    if not DISCIPLINE_INCLUDE.search(job.title):
        return False

    if not _is_us_location(job.location):
        return False

    return True
