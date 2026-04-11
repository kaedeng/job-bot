from __future__ import annotations

from typing import Protocol

import httpx

from bot.models import Job


class PlatformScraper(Protocol):
    """Multi-company platform scraper (Greenhouse, Lever, Ashby).

    Called once per company slug; returns all job postings for that company.
    """

    async def __call__(self, slug: str, client: httpx.AsyncClient) -> list[Job]: ...


class CustomScraper(Protocol):
    """Single-company scraper with a proprietary careers API.

    No slug needed — the company and endpoint are baked into the implementation.
    """

    async def __call__(self, client: httpx.AsyncClient) -> list[Job]: ...
