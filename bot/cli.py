"""Dry-run CLI for testing scrapers locally without Discord."""

from __future__ import annotations

import asyncio
import argparse
import logging

import httpx

from bot.filters import passes_filter
from bot.models import Job
from bot.scrapers import ashby, greenhouse, lever, simplify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def run_scraper(source: str, slug: str | None) -> list[Job]:
    async with httpx.AsyncClient(timeout=20) as client:
        if source == "greenhouse" and slug:
            return await greenhouse.scrape(slug, client)
        elif source == "lever" and slug:
            return await lever.scrape(slug, client)
        elif source == "ashby" and slug:
            return await ashby.scrape(slug, client)
        elif source == "simplify":
            return await simplify.scrape(client)
        else:
            logger.error("Unknown source %s (slug=%s)", source, slug)
            return []


async def dry_run(source: str, slug: str | None, show_all: bool) -> None:
    logger.info("Scraping %s%s...", source, f"/{slug}" if slug else "")
    jobs = await run_scraper(source, slug)
    logger.info("Got %d raw jobs", len(jobs))

    if show_all:
        filtered = jobs
    else:
        filtered = [j for j in jobs if passes_filter(j)]
        logger.info("%d jobs pass filters", len(filtered))

    for job in filtered:
        print(f"  [{job.source}] {job.title}")
        print(f"    Company:  {job.company}")
        print(f"    Location: {job.location}")
        print(f"    URL:      {job.url}")
        print()

    if not filtered:
        print("  (no matching jobs)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run job scrapers locally")
    parser.add_argument(
        "source",
        choices=["greenhouse", "lever", "ashby", "simplify"],
        help="Scraper source to test",
    )
    parser.add_argument(
        "slug",
        nargs="?",
        default=None,
        help="Company slug (required for greenhouse/lever/ashby)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="Show all jobs, not just ones that pass filters",
    )
    args = parser.parse_args()

    if args.source != "simplify" and not args.slug:
        parser.error(f"{args.source} requires a company slug")

    asyncio.run(dry_run(args.source, args.slug, args.show_all))


if __name__ == "__main__":
    main()
