from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from bot.models import Job


@dataclass(frozen=True, slots=True)
class CustomScraperInfo:
    """Metadata for a single-company custom scraper."""

    name: str
    scrape: Callable[[httpx.AsyncClient], Awaitable[list[Job]]]
    default_interval_minutes: int = 30
    timeout: int = 30


def _build_registry() -> dict[str, CustomScraperInfo]:
    """Build the registry, importing scraper modules lazily to keep the
    top-level import lightweight and avoid circular-import issues."""
    from bot.scrapers.custom import amazon

    return {
        "amazon": CustomScraperInfo(
            name="amazon",
            scrape=amazon.scrape,
            default_interval_minutes=30,
            timeout=30,
        ),
        # To add a new custom scraper:
        # 1. Create bot/scrapers/custom/<name>.py with:
        #        async def scrape(client: httpx.AsyncClient) -> list[Job]: ...
        # 2. Import the module above and add an entry here.
        # 3. Add the name to CUSTOM_SCRAPERS in .env.
    }


REGISTRY: dict[str, CustomScraperInfo] = _build_registry()
