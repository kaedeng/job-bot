"""Netflix scraper.

Netflix publishes jobs through Lever, so this custom scraper is a small wrapper
around the shared Lever parser with the company baked in.
"""

from __future__ import annotations

import httpx

from bot.models import Job
from bot.scrapers import lever


async def scrape(client: httpx.AsyncClient) -> list[Job]:
    jobs = await lever.scrape("netflix", client)
    return [
        Job(
            id=j.id,
            title=j.title,
            company="Netflix",
            location=j.location,
            url=j.url,
            source="netflix",
            posted_at=j.posted_at,
            description=j.description,
        )
        for j in jobs
    ]
