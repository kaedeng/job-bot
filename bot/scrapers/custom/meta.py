"""Meta Careers scraper.

Meta Careers is a Comet/Relay app and may serve a blocked shell to simple HTTP
clients. This scraper is intentionally conservative: it parses job data only
when the public HTML contains concrete job cards/links, and otherwise returns an
empty list with a warning so one source cannot break the whole bot.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from urllib.parse import urljoin

import httpx

from bot.models import Job

logger = logging.getLogger(__name__)

BASE_URL = "https://www.metacareers.com"
SEARCH_URL = f"{BASE_URL}/jobsearch/"

QUERIES = ["intern", "internship", "new grad", "software engineer intern"]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_JOB_LINK_RE = re.compile(r'href="(?P<href>/(?:jobs|careers/jobs)/(?P<id>\d+)/?[^"]*)"', re.I)
_TITLE_NEAR_LINK_RE = re.compile(r"(?:aria-label|title)=\"(?P<title>[^\"]+)\"", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", text))).strip()


def _title_from_context(html: str, href_start: int, href_end: int) -> str:
    start = max(0, href_start - 1200)
    end = min(len(html), href_end + 1200)
    context = html[start:end]
    match = _TITLE_NEAR_LINK_RE.search(context)
    if match:
        title = _clean(match.group("title"))
        if title:
            return title
    return "Meta job"


async def scrape(client: httpx.AsyncClient) -> list[Job]:
    seen_ids: set[str] = set()
    jobs: list[Job] = []

    for query in QUERIES:
        try:
            resp = await client.get(SEARCH_URL, params={"q": query}, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Meta careers search failed (query=%r): %s", query, e)
            continue

        html = resp.text
        for match in _JOB_LINK_RE.finditer(html):
            job_id = match.group("id")
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            jobs.append(
                Job(
                    id=job_id,
                    title=_title_from_context(html, match.start(), match.end()),
                    company="Meta",
                    location="",
                    url=urljoin(BASE_URL, unescape(match.group("href"))),
                    source="meta",
                )
            )

    if not jobs:
        logger.warning(
            "Meta careers returned no parseable job cards; the site may have served a "
            "Relay shell or blocked page to this client."
        )
    return jobs
