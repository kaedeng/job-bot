"""Databricks scraper.

Databricks publishes jobs through Greenhouse, so this custom scraper is a small
wrapper around the shared Greenhouse parser with the company baked in.
"""

from __future__ import annotations

import httpx

from bot.models import Job
from bot.scrapers import greenhouse


async def scrape(client: httpx.AsyncClient) -> list[Job]:
    jobs = await greenhouse.scrape("databricks", client)
    return [
        Job(
            id=j.id,
            title=j.title,
            company="Databricks",
            location=j.location,
            url=j.url,
            source="databricks",
            posted_at=j.posted_at,
            description=j.description,
        )
        for j in jobs
    ]
