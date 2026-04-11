from __future__ import annotations

import logging

import httpx

from bot.models import Job

logger = logging.getLogger(__name__)

SOURCES = {
    "simplify-intern": (
        "https://raw.githubusercontent.com/SimplifyJobs/Summer2025-Internships"
        "/dev/.github/scripts/listings.json"
    ),
    "simplify-newgrad": (
        "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions"
        "/dev/.github/scripts/listings.json"
    ),
}


async def scrape(client: httpx.AsyncClient) -> list[Job]:
    all_jobs: list[Job] = []
    for source_name, url in SOURCES.items():
        try:
            resp = await client.get(url, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Simplify %s failed: %s", source_name, e)
            continue

        for item in resp.json():
            locations = item.get("locations", [])
            location_str = ", ".join(locations) if locations else ""
            apply_url = item.get("url", "")

            all_jobs.append(
                Job(
                    id=str(item.get("id", "")),
                    title=item.get("title", ""),
                    company=item.get("company_name", ""),
                    location=location_str,
                    url=apply_url,
                    source=source_name,
                )
            )
    return all_jobs
