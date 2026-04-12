from __future__ import annotations

import re

from bot.models import Job

# --- Classification signal regexes ---

# Intern signals.  Negative lookaheads block "international" (ation) and
# "internal" / "internally" (al\b) which share the "intern" prefix.
_INTERN_RE = re.compile(
    r"\bintern(?!al\b|ation)(?:ship)?\b|\bco[\s-]?op\b",
    re.IGNORECASE,
)

# New-grad / entry-level signals (used for both title and description)
_NEW_GRAD_RE = re.compile(
    r"\b(new\s*grad(?:uates?)?|recent\s*grad(?:uates?)?|university\s*grad(?:uates?)?"
    r"|entry[\s-]*level|junior|jr\.?|associate(?:\s+engineer)?|early[\s-]*career"
    r"|campus\s+(?:hire|recruit)|swe\s*[i1]\b|software\s+engineer\s+[i1]\b|l3"
    r"|no\s+(?:prior\s+)?(?:professional\s+)?experience\s+required|fresher)\b",
    re.IGNORECASE,
)

# Senior / management / leadership signals
_OTHER_RE = re.compile(
    r"\b(senior|sr\.|staff|principal|manager|lead|director"
    r"|vice\s+president|vp|head\s+of|executive)\b",
    re.IGNORECASE,
)

# Years-of-experience extraction — captures the lower bound of ranges like
# "3-5 years", "4+ years of experience", "minimum of 2 years experience"
_YOE_RE = re.compile(
    r"(?:minimum\s+(?:of\s+)?|at\s+least\s+)?"
    r"(\d+)(?:\s*[-–]\s*\d+)?\+?\s*(?:or\s+more\s+)?"
    r"years?\s+(?:of\s+)?(?:\w+\s+)*experience",
    re.IGNORECASE,
)

# Score weights
_TITLE_SCORE = 3
_DESC_SCORE = 1

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

US_KEYWORDS = {"united states", "usa", "u.s."}

# Regions that explicitly exclude US workers even when combined with "remote".
# "global" / "worldwide" are intentionally omitted — those jobs are US-accessible.
_NON_US_REGION_RE = re.compile(
    r"\b(emea|europe(?:an)?\b|eu\b|apac|asia[\s-]pacific|latam|latin\s*america|mena)\b",
    re.IGNORECASE,
)

# Splits raw location strings on semicolons and " / " (multi-location separator used
# by Greenhouse, Lever etc.).  Avoids splitting on bare "/" to preserve "w/o", "24/7".
_LOCATION_SPLIT_RE = re.compile(r"\s*/\s*|;")

# Precompiled single-pass regex for all US state abbreviations
_US_STATE_ABBREV_RE = re.compile(r"\b(" + "|".join(US_STATE_ABBREVS) + r")\b")

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

# State names sorted longest-first so "west virginia" is matched before "virginia",
# "north carolina" before "carolina", etc.
_SORTED_STATES: list[tuple[str, str]] = sorted(
    _STATE_TO_ABBREV.items(), key=lambda x: len(x[0]), reverse=True
)

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
    # Additional full country names not in the original list
    "vietnam": "VN",
    "malaysia": "MY",
    "philippines": "PH",
    "thailand": "TH",
    "indonesia": "ID",
    "saudi arabia": "SA",
    "costa rica": "CR",
    "south africa": "ZA",
    "nigeria": "NG",
    "kenya": "KE",
    "egypt": "EG",
    "pakistan": "PK",
    "bangladesh": "BD",
    "qatar": "QA",
    "bahrain": "BH",
    "kuwait": "KW",
    "oman": "OM",
    "morocco": "MA",
    "ghana": "GH",
    "ethiopia": "ET",
    "panama": "PA",
    "peru": "PE",
    "sri lanka": "LK",
    "myanmar": "MM",
    "cambodia": "KH",
    "ecuador": "EC",
    "venezuela": "VE",
    "bolivia": "BO",
    "uruguay": "UY",
    "paraguay": "PY",
    # ISO 3166-1 alpha-3 codes — used by Workday, Oracle, SAP ATS exports
    # e.g. "IND.Chennai", "MEX.Guadalajara", "KSA.Riyadh"
    # Word-boundary regexes (built from _COUNTRY_DETECT) prevent substring matches.
    "ind": "IN",   # India
    "mex": "MX",   # Mexico
    "can": "CA",   # Canada
    "gbr": "GB",   # United Kingdom
    "aus": "AU",   # Australia
    "jpn": "JP",   # Japan
    "chn": "CN",   # China
    "bra": "BR",   # Brazil
    "deu": "DE",   # Germany
    "fra": "FR",   # France
    "ita": "IT",   # Italy
    "esp": "ES",   # Spain
    "nld": "NL",   # Netherlands
    "pol": "PL",   # Poland
    "swe": "SE",   # Sweden
    "sgp": "SG",   # Singapore
    "isr": "IL",   # Israel
    "twn": "TW",   # Taiwan
    "kor": "KR",   # South Korea
    "vnm": "VN",   # Vietnam
    "mys": "MY",   # Malaysia
    "phl": "PH",   # Philippines
    "tha": "TH",   # Thailand
    "idn": "ID",   # Indonesia
    "sau": "SA",   # Saudi Arabia (official alpha-3)
    "ksa": "SA",   # Saudi Arabia (informal but common in Gulf region)
    "cri": "CR",   # Costa Rica
    "zaf": "ZA",   # South Africa
    "arg": "AR",   # Argentina
    "col": "CO",   # Colombia
    "chl": "CL",   # Chile
    "per": "PE",   # Peru
    "irl": "IE",   # Ireland
    "nzl": "NZ",   # New Zealand
    "nor": "NO",   # Norway
    "dnk": "DK",   # Denmark
    "fin": "FI",   # Finland
    "che": "CH",   # Switzerland
    "aut": "AT",   # Austria
    "bel": "BE",   # Belgium
    "grc": "GR",   # Greece
    "tur": "TR",   # Turkey
    "cze": "CZ",   # Czech Republic
    "rou": "RO",   # Romania
    "hun": "HU",   # Hungary
    "ukr": "UA",   # Ukraine
    "prt": "PT",   # Portugal
    "are": "AE",   # UAE
    "egy": "EG",   # Egypt
    "nga": "NG",   # Nigeria
    "pak": "PK",   # Pakistan
    "bgd": "BD",   # Bangladesh
    "qat": "QA",   # Qatar
    "kwt": "KW",   # Kuwait
    "omn": "OM",   # Oman
    "bhr": "BH",   # Bahrain
    "mar": "MA",   # Morocco
    "ken": "KE",   # Kenya
    # Abbreviations — checked last to avoid shadowing full names
    "uk": "GB",
}

# Precompiled (pattern, name, iso_code) triples — longest name first so
# "united kingdom" is tried before "uk".  Word-boundary anchors prevent short
# codes from matching as substrings: "uk" must not fire inside "tukwila",
# and "india" must not fire inside "indiana".
_COUNTRY_DETECT: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE), name, code)
    for name, code in sorted(_COUNTRY_TO_CODE.items(), key=lambda x: len(x[0]), reverse=True)
]


def _is_us_location(location: str) -> bool:
    """Return True if any segment of the location string is US-based or US-accessible remote.

    Splits on both ";" and " / " so multi-location strings like
    "New York, NY / London, UK" are checked segment-by-segment.

    Unrecognized/unparseable segments are assumed to be US (the scraper list is
    curated toward US companies, so opaque strings like "2 Locations" or
    "Arlington - 1801 S Bell" are more likely to be US than not).
    The only exception is explicit non-US remote qualifiers like "Remote - EMEA",
    which are skipped rather than assumed.

    Fallback: some scrapers (Lever) emit comma-separated multi-country strings
    without semicolons, e.g. "San Francisco, Seattle, Remote in US or Canada".
    These are not split by _LOCATION_SPLIT_RE, so parse_location sees the whole
    string and may fire on the first detected non-US country.  If the segment
    loop exits without a US hit, a secondary raw-signal scan on the original
    string catches explicit US indicators (keywords, cities, state abbreviations).
    """
    if not location.strip():
        return False
    for seg in _LOCATION_SPLIT_RE.split(location):
        seg = seg.strip()
        if not seg:
            continue
        country, _, _ = parse_location(seg)
        if country == "US":
            return True
        if country is None:
            # Segment is unrecognised — assume US unless it's explicitly a
            # non-US remote qualifier (e.g. "Remote - EMEA", "Remote Europe").
            if _IS_REMOTE.search(seg) and _NON_US_REGION_RE.search(seg):
                continue  # explicitly non-US remote — do not assume
            return True

    # Fallback raw-signal scan for strings that weren't split (no ";" or " / ")
    # but still contain explicit US indicators alongside a non-US country.
    # e.g. "US, Canada", "San Francisco, Seattle, Remote in US or Canada"
    loc_lower = location.lower()
    if (
        any(kw in loc_lower for kw in US_KEYWORDS)
        or re.search(r"\bUS\b", location)
        or any(city in loc_lower for city in US_CITIES)
        or _US_STATE_ABBREV_RE.search(location)
        or any(state in loc_lower for state in US_STATES)
    ):
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

    International country detection runs FIRST so that a US state abbreviation
    that coincidentally appears in a foreign location string (e.g. "IN" in
    "Bangalore, IN" for India, "PE" in "Lima, PE" for Peru) doesn't trigger a
    false US match.

    Examples:
        "San Francisco, CA"              -> ("US", "CA", "San Francisco")
        "Remote"                         -> ("US", None, None)
        "Remote - EMEA"                  -> (None, None, None)
        "New York, NY"                   -> ("US", "NY", "New York")
        "Warsaw, Masovian Voivodeship, Poland" -> ("PL", None, "Warsaw")
        "London, UK"                     -> ("GB", None, "London")
        "Toronto, ON, Canada"            -> ("CA", None, "Toronto")
        "Bangalore, IN, India"           -> ("IN", None, "Bangalore")
        ""                               -> (None, None, None)
    """
    loc = location.strip()
    if not loc:
        return None, None, None

    loc_lower = loc.lower()

    # --- Step 1: International country detection (word-boundary, longest-match first) ---
    # Uses precompiled word-boundary regexes so short codes like "uk" don't fire inside
    # words ("tukwila") and full names like "india" don't fire inside "indiana".
    intl_country: str | None = None
    matched_country_name: str | None = None
    for pattern, name, code in _COUNTRY_DETECT:
        if pattern.search(loc):
            intl_country = code
            matched_country_name = name
            break

    if intl_country is not None:
        # Known non-US country found — skip US checks entirely.
        city: str | None = None
        if "," in loc:
            first_seg = loc.split(",")[0].strip()
            # If the first comma segment IS the country name, the city comes next.
            # e.g. "Israel, Yokneam" → city="Yokneam", not "Israel"
            if matched_country_name and first_seg.lower() == matched_country_name:
                parts = loc.split(",", 2)
                city = parts[1].strip() or None if len(parts) > 1 else None
            else:
                city = first_seg or None
        return intl_country, None, city

    # --- Step 2: US detection ---
    # "remote" without a non-US regional qualifier (EMEA, APAC, etc.) is US-accessible.
    is_remote_us = bool(_IS_REMOTE.search(loc)) and not bool(_NON_US_REGION_RE.search(loc))
    abbrev_match = _US_STATE_ABBREV_RE.search(loc)
    is_us = (
        is_remote_us
        or any(kw in loc_lower for kw in US_KEYWORDS)
        or any(state in loc_lower for state in US_STATES)
        or any(city_kw in loc_lower for city_kw in US_CITIES)
        or abbrev_match is not None
    )

    if is_us:
        country: str | None = "US"

        # State abbreviation first (e.g. ", CA" or "(NY)")
        state: str | None = abbrev_match.group(1) if abbrev_match else None

        # Fall back to full state name — longest-first so "west virginia" beats "virginia"
        if state is None:
            for name, abbrev in _SORTED_STATES:
                if name in loc_lower:
                    state = abbrev
                    break

        # City — known set first, then first comma segment
        city = None
        for known_city in US_CITIES:
            if known_city in loc_lower:
                city = known_city.title()
                break
        if city is None and "," in loc:
            candidate = loc.split(",")[0].strip()
            # Skip candidate if it's a country token ("US", "USA", "United States"),
            # bare state name, or state abbreviation — e.g. "US, CA, Pleasanton" and
            # "USA, CA, Santa Clara" should not yield city="US" / city="USA".
            _country_tokens = US_KEYWORDS | {"us", "america"}
            if (
                candidate.lower() not in US_STATES
                and candidate not in US_STATE_ABBREVS
                and candidate.lower() not in _country_tokens
            ):
                city = candidate or None

        return country, state, city

    # Unknown / unrecognised location
    return None, None, None


_IS_REMOTE = re.compile(r"\bremote\b", re.IGNORECASE)


def parse_locations(location_raw: str) -> list[dict]:
    """Parse a raw location string into a list of location dicts.

    Splits on semicolons AND " / " separators (Greenhouse/Lever multi-location
    format) so each office/remote option gets its own DB row.  Each dict has:
        country (str|None), state (str|None), city (str|None), is_remote (bool)

    Examples:
        "San Francisco, CA"
            -> [{"country":"US","state":"CA","city":"San Francisco","is_remote":False}]
        "New York, NY / London, UK"
            -> [{"country":"US","state":"NY","city":"New York","is_remote":False},
                {"country":"GB","state":None,"city":"London","is_remote":False}]
        "London, UK; Remote-Friendly, United States; San Francisco, CA"
            -> [{"country":"GB",...,"is_remote":False},
                {"country":"US",...,"is_remote":True},
                {"country":"US","state":"CA","city":"San Francisco","is_remote":False}]
    """
    if not location_raw.strip():
        return []

    segments = [s.strip() for s in _LOCATION_SPLIT_RE.split(location_raw) if s.strip()]
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


def strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _extract_min_years(text: str) -> int | None:
    """Return the lowest years-of-experience figure mentioned in text, or None."""
    values = [int(m.group(1)) for m in _YOE_RE.finditer(text)]
    return min(values) if values else None


def classify_job(job: Job) -> tuple[bool, bool]:
    """Score-based classification into (is_intern, is_new_grad).

    Three competing piles — intern, new_grad, other — accumulate points from
    keyword signals and years-of-experience extraction.  The pile(s) with the
    highest score win; if other strictly outscores both entry-level piles the job
    is excluded (returns False, False).  Ties between intern and new_grad produce
    (True, True) for combined postings.

    Scoring:
        Title keyword match  → 3 pts to matching pile
        Desc keyword match   → 1 pt
        Years of experience  → 0-2 yrs: +2 new_grad; 3 yrs: +1 new_grad;
                               4-5 yrs: +2 other; 6+ yrs: +3 other

    Source trust (Simplify) bypasses scoring entirely.
    """
    # Source-level trust — Simplify repos are pre-curated by type
    if job.source == "simplify-intern":
        return True, False
    if job.source == "simplify-newgrad":
        return False, True

    intern_score = 0
    new_grad_score = 0
    other_score = 0

    # Title signals (3 pts each)
    if _INTERN_RE.search(job.title):
        intern_score += _TITLE_SCORE
    if _NEW_GRAD_RE.search(job.title):
        new_grad_score += _TITLE_SCORE
    if _OTHER_RE.search(job.title):
        other_score += _TITLE_SCORE

    # Description signals (1 pt each) + years-of-experience scoring
    if job.description:
        desc = strip_html(job.description)
        if _INTERN_RE.search(desc):
            intern_score += _DESC_SCORE
        if _NEW_GRAD_RE.search(desc):
            new_grad_score += _DESC_SCORE
        if _OTHER_RE.search(desc):
            other_score += _DESC_SCORE

        years = _extract_min_years(desc)
        if years is not None:
            if years <= 2:
                new_grad_score += 2
            elif years == 3:
                new_grad_score += 1
            elif years <= 5:
                other_score += 2
            else:  # 6+
                other_score += 3

    # No signals at all → unclassified
    if intern_score == 0 and new_grad_score == 0 and other_score == 0:
        return False, False

    # Other pile strictly wins → not entry-level
    if other_score > intern_score and other_score > new_grad_score:
        return False, False

    # Assign entry-level piles at or tied for the top score
    max_entry = max(intern_score, new_grad_score)
    is_intern = intern_score > 0 and intern_score >= max_entry
    is_new_grad = new_grad_score > 0 and new_grad_score >= max_entry
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
