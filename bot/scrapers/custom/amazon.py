"""Amazon Jobs scraper.

Targets the public GET search API at amazon.jobs/en/search.json.
Location is filtered via country[]=us (not normalized_location[], which returns
empty results). The entry-level/US filter pipeline deduplicates further.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from bot.models import Job

logger = logging.getLogger(__name__)

BASE_URL = "https://www.amazon.jobs"
SEARCH_URL = f"{BASE_URL}/en/search.json"

CATEGORIES = ["software-development", "hardware-engineering"]
QUERIES = ["intern", "new grad"]

RESULT_LIMIT = 100
MAX_PAGES = 3

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.amazon.jobs/en/jobs",
    # Browser-like UA helps avoid empty responses from bot detection
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_DATE_FORMATS = ("%B %d, %Y", "%Y-%m-%d")


def _parse_date(value: str) -> datetime | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


async def scrape(client: httpx.AsyncClient) -> list[Job]:
    seen_ids: set[str] = set()
    jobs: list[Job] = []

    for category in CATEGORIES:
        for query in QUERIES:
            offset = 0
            while offset < MAX_PAGES * RESULT_LIMIT:
                params: dict[str, object] = {
                    "base_query": query,
                    "category[]": category,
                    "country[]": "us",  # NOT normalized_location[] — that returns 0
                    "result_limit": RESULT_LIMIT,
                    "offset": offset,
                    "sort": "recent",
                }
                try:
                    resp = await client.get(
                        SEARCH_URL,
                        params=params,
                        headers=HEADERS,
                        timeout=30,
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as e:
                    logger.warning(
                        "Amazon search failed (category=%r query=%r offset=%d): %s",
                        category,
                        query,
                        offset,
                        e,
                    )
                    break

                data = resp.json()

                # Log response shape on first call to help catch future API changes
                if offset == 0 and not seen_ids:
                    logger.debug(
                        "Amazon response top-level keys: %s", list(data.keys())
                    )

                # "hits" is the integer count; actual job list is under "jobs"
                job_list: list[dict] = data.get("jobs", [])
                if not job_list:
                    break

                # Log field names from first hit on first page for debuggability
                if offset == 0 and job_list:
                    logger.debug("Amazon hit keys: %s", list(job_list[0].keys()))

                for item in job_list:
                    # API has used both id_icims and id across versions
                    job_id = str(
                        item.get("id_icims") or item.get("id") or ""
                    ).strip()
                    if not job_id or job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    job_path: str = item.get("job_path") or item.get("jobPath") or ""
                    url = f"{BASE_URL}{job_path}" if job_path else ""

                    location: str = (
                        item.get("normalized_location")
                        or item.get("normalizedLocation")
                        or item.get("location")
                        or ""
                    )

                    desc_parts = [
                        p
                        for p in (
                            item.get("description_short") or item.get("descriptionShort"),
                            item.get("basic_qualifications") or item.get("basicQualifications"),
                        )
                        if p
                    ]
                    description = "\n\n".join(desc_parts) or None

                    jobs.append(
                        Job(
                            id=job_id,
                            title=item.get("title", ""),
                            company="amazon",
                            location=location,
                            url=url,
                            source="amazon",
                            posted_at=_parse_date(
                                item.get("posted_date") or item.get("postedDate") or ""
                            ),
                            description=description,
                        )
                    )

                # "hits" = total matching jobs (integer), "count" = jobs on this page
                total: int = data.get("hits", 0)
                offset += RESULT_LIMIT
                if offset >= total:
                    break

    return jobs
