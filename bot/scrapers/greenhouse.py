from __future__ import annotations

import logging

import httpx

from bot.models import Job

logger = logging.getLogger(__name__)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


async def scrape(slug: str, client: httpx.AsyncClient) -> list[Job]:
    url = BASE_URL.format(slug=slug)
    try:
        resp = await client.get(url, params={"content": "true"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Greenhouse %s failed: %s", slug, e)
        return []

    jobs = []
    for item in resp.json().get("jobs", []):
        location = item.get("location", {}).get("name", "")
        jobs.append(
            Job(
                id=str(item["id"]),
                title=item["title"],
                company=slug,
                location=location,
                url=item.get("absolute_url", ""),
                source="greenhouse",
                description=item.get("content") or None,
            )
        )
    return jobs
