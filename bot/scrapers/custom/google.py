"""Google Careers scraper.

Google's careers search page server-renders enough result-card HTML for the
bot's purposes, so this scraper avoids depending on private Google RPC payloads.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

import httpx

from bot.models import Job

logger = logging.getLogger(__name__)

BASE_URL = "https://www.google.com/about/careers/applications/"
SEARCH_URL = f"{BASE_URL}jobs/results/"

QUERIES = ["intern", "internship", "new grad"]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_CARD_RE = re.compile(
    r'<h3[^>]*class="QJPWVe"[^>]*>(?P<title>.*?)</h3>'
    r"(?P<body>.*?)"
    r'<a[^>]+href="(?P<href>jobs/results/(?P<id>\d+)-[^"]+)"',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_LOCATION_RE = re.compile(r'<span[^>]*class="[^"]*\br0wTof\b[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
_QUALS_RE = re.compile(r'<div[^>]*class="[^"]*\bXsxa1e\b[^"]*"[^>]*>(.*?)</div>', re.DOTALL)


def _clean_html(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", text))).strip()


def _extract_locations(body: str) -> str:
    locations = [_clean_html(m.group(1)) for m in _LOCATION_RE.finditer(body)]
    return "; ".join(loc for loc in locations if loc and not loc.startswith("+"))


def _extract_description(body: str) -> str | None:
    match = _QUALS_RE.search(body)
    if not match:
        return None
    desc = _clean_html(match.group(1))
    return desc or None


def _parse_cards(html: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for match in _CARD_RE.finditer(html):
        body = match.group("body")
        cards.append(
            {
                "id": match.group("id"),
                "title": _clean_html(match.group("title")),
                "location": _extract_locations(body),
                "url": urljoin(BASE_URL, unescape(match.group("href"))),
                "description": _extract_description(body),
            }
        )
    return cards


async def scrape(client: httpx.AsyncClient) -> list[Job]:
    seen_ids: set[str] = set()
    jobs: list[Job] = []

    for query in QUERIES:
        try:
            resp = await client.get(SEARCH_URL, params={"q": query}, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Google careers search failed (query=%r): %s", query, e)
            continue

        for item in _parse_cards(resp.text):
            job_id = item["id"]
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            jobs.append(
                Job(
                    id=job_id,
                    title=item["title"],
                    company="Google",
                    location=item["location"],
                    url=item["url"],
                    source="google",
                    description=item["description"],
                )
            )

    return jobs
