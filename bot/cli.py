"""Dry-run CLI for testing scrapers locally without Discord."""

from __future__ import annotations

import argparse
import asyncio
import logging

import httpx

from bot.db import init_db, store_jobs_batch
from bot.filters import (
    classify_discipline,
    classify_job,
    is_tech_job,
    parse_locations,
    passes_filter,
)
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


async def dry_run(source: str, slug: str | None, show_all: bool, store: bool) -> None:
    logger.info("Scraping %s%s...", source, f"/{slug}" if slug else "")
    jobs = await run_scraper(source, slug)
    logger.info("Got %d raw jobs", len(jobs))

    cs_jobs = [j for j in jobs if is_tech_job(j)]
    logger.info("%d jobs are tech-relevant", len(cs_jobs))

    if show_all:
        display = jobs
    else:
        display = [j for j in cs_jobs if passes_filter(j)]
        logger.info("%d jobs pass the full entry-level/US filter", len(display))

    for job in display:
        print(f"  [{job.source}] {job.title}")
        print(f"    Company:  {job.company}")
        print(f"    Location: {job.location}")
        print(f"    URL:      {job.url}")
        print()

    if not display:
        print("  (no matching jobs)")

    if store:
        await init_db()
        await store_jobs_batch(cs_jobs, parse_locations, classify_job, classify_discipline)
        from bot.config import settings
        logger.info("Stored %d CS jobs to %s", len(cs_jobs), settings.db_path)


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
    parser.add_argument(
        "--store",
        action="store_true",
        help="Store CS-relevant jobs to the local jobs.db (creates it if missing)",
    )
    args = parser.parse_args()

    if args.source != "simplify" and not args.slug:
        parser.error(f"{args.source} requires a company slug")

    asyncio.run(dry_run(args.source, args.slug, args.show_all, args.store))


if __name__ == "__main__":
    main()
