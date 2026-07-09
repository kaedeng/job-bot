"""Microsoft Careers scraper.

Microsoft's public careers site is an Eightfold PCS/PCSX frontend backed by
SuccessFactors data. The browser first loads /careers to establish cookies and a
CSRF token, then calls /api/pcsx/search for results and /api/pcsx/position_details
for job descriptions.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

import httpx

from bot.models import Job

logger = logging.getLogger(__name__)

BASE_URL = "https://apply.careers.microsoft.com"
DOMAIN = "microsoft.com"
CAREERS_URL = f"{BASE_URL}/careers"
SEARCH_URL = f"{BASE_URL}/api/pcsx/search"
DETAIL_URL = f"{BASE_URL}/api/pcsx/position_details"

PAGE_SIZE = 10  # Microsoft currently returns 10 positions per page.
MAX_PAGES_PER_SEARCH = 5

SEARCH_SPECS: list[tuple[str, dict[str, list[str]]]] = [
    ("intern", {}),
    ("internship", {}),
    ("new grad", {}),
    ("", {"seniority": ["Intern"]}),
    (
        "",
        {
            "seniority": ["Entry"],
            "profession": [
                "software engineering",
                "hardware engineering",
                "research, applied, & data sciences",
                "security engineering",
            ],
        },
    ),
]

BASE_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

PAGE_HEADERS = {
    **BASE_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

API_HEADERS = {
    **BASE_HEADERS,
    "Accept": "application/json, text/plain, */*",
    "Referer": CAREERS_URL,
    "X-Requested-With": "XMLHttpRequest",
}

_CSRF_RE = re.compile(r'<meta\s+name=["\']_csrf["\']\s+content=["\']([^"\']+)["\']')


def _parse_posted_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _join_locations(item: dict[str, Any]) -> str:
    locations = item.get("standardizedLocations") or item.get("locations")
    if isinstance(locations, list):
        return "; ".join(str(loc).strip() for loc in locations if str(loc).strip())
    return str(item.get("location") or "").strip()


def _job_url(item: dict[str, Any]) -> str:
    public_url = str(item.get("publicUrl") or "").strip()
    if public_url:
        return public_url

    path = str(item.get("positionUrl") or "").strip()
    if not path:
        position_id = str(item.get("id") or "").strip()
        path = f"/careers/job/{position_id}" if position_id else ""
    return f"{BASE_URL}{path}" if path.startswith("/") else path


def _job_id(item: dict[str, Any]) -> str:
    return str(item.get("displayJobId") or item.get("atsJobId") or item.get("id") or "").strip()


async def _bootstrap_headers(client: httpx.AsyncClient) -> dict[str, str]:
    """Load the careers page so the client gets cookies and a CSRF token."""
    try:
        resp = await client.get(CAREERS_URL, headers=PAGE_HEADERS, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Microsoft careers bootstrap failed: %s", e)
        return dict(API_HEADERS)

    headers = dict(API_HEADERS)
    match = _CSRF_RE.search(resp.text)
    if match:
        headers["X-CSRF-Token"] = match.group(1)
    else:
        logger.debug("Microsoft careers page did not expose a CSRF token")
    return headers


async def _search_page(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    query: str,
    filters: dict[str, list[str]],
    start: int,
) -> tuple[list[dict[str, Any]], int]:
    params: list[tuple[str, str | int]] = [
        ("domain", DOMAIN),
        ("query", query),
        ("location", ""),
        ("start", start),
    ]
    for name, values in filters.items():
        for value in values:
            params.append((f"filter_{name}", value))

    try:
        resp = await client.get(SEARCH_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Microsoft search failed (query=%r start=%d): %s", query, start, e)
        return [], 0

    data = resp.json().get("data", {})
    positions = data.get("positions") or []
    count = data.get("count") or 0
    return positions, int(count)


async def _fetch_detail(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    position_id: str,
) -> dict[str, Any]:
    params = {
        "position_id": position_id,
        "domain": DOMAIN,
        "hl": "en",
    }
    try:
        resp = await client.get(DETAIL_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.debug("Microsoft detail fetch failed for %s: %s", position_id, e)
        return {}
    return resp.json().get("data") or {}


async def scrape(client: httpx.AsyncClient) -> list[Job]:
    headers = await _bootstrap_headers(client)
    seen_ids: set[str] = set()
    jobs: list[Job] = []

    for query, filters in SEARCH_SPECS:
        start = 0
        for _ in range(MAX_PAGES_PER_SEARCH):
            positions, total = await _search_page(client, headers, query, filters, start)
            if not positions:
                break

            for item in positions:
                job_id = _job_id(item)
                position_id = str(item.get("id") or "").strip()
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                detail = await _fetch_detail(client, headers, position_id) if position_id else {}
                merged = {**item, **detail}
                description = merged.get("jobDescription")

                jobs.append(
                    Job(
                        id=job_id,
                        title=str(merged.get("name") or "").strip(),
                        company="Microsoft",
                        location=_join_locations(merged),
                        url=_job_url(merged),
                        source="microsoft",
                        posted_at=_parse_posted_ts(
                            merged.get("postedTs") or merged.get("creationTs")
                        ),
                        description=unescape(description) if isinstance(description, str) else None,
                    )
                )

            start += len(positions)
            if start >= total:
                break

    return jobs
