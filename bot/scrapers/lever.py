from __future__ import annotations

import logging

import httpx

from bot.models import Job

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lever.co/v0/postings/{slug}"


async def scrape(slug: str, client: httpx.AsyncClient) -> list[Job]:
    url = BASE_URL.format(slug=slug)
    try:
        resp = await client.get(url, params={"mode": "json"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Lever %s failed: %s", slug, e)
        return []

    jobs = []
    for item in resp.json():
        location = item.get("categories", {}).get("location", "")
        jobs.append(
            Job(
                id=item["id"],
                title=item["text"],
                company=slug,
                location=location,
                url=item.get("hostedUrl", ""),
                source="lever",
            )
        )
    return jobs
