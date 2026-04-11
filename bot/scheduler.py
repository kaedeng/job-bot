from __future__ import annotations

import asyncio
import logging

import discord
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import db
from bot.config import settings
from bot.filters import passes_filter
from bot.models import Job
from bot.notifier import notify
from bot.scrapers import ashby, greenhouse, lever, simplify

logger = logging.getLogger(__name__)

# Set by main.py once the bot is ready
_channel: discord.TextChannel | None = None


def set_channel(channel: discord.TextChannel) -> None:
    global _channel
    _channel = channel


async def _process_jobs(jobs: list[Job]) -> None:
    """Filter, dedup, notify, and mark as seen."""
    if _channel is None:
        logger.error("Channel not set — skipping notification")
        return

    filtered = [j for j in jobs if passes_filter(j)]

    new_jobs: list[Job] = []
    for job in filtered:
        if not await db.is_seen(job.source, job.id):
            new_jobs.append(job)

    if not new_jobs:
        return

    logger.info("Found %d new jobs", len(new_jobs))
    await notify(new_jobs, _channel)
    await db.mark_seen_batch([(j.source, j.id) for j in new_jobs])


async def poll_greenhouse() -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        all_jobs: list[Job] = []
        for slug in settings.greenhouse_slugs:
            all_jobs.extend(await greenhouse.scrape(slug, client))
            await asyncio.sleep(1)  # be polite
        await _process_jobs(all_jobs)


async def poll_lever() -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        all_jobs: list[Job] = []
        for slug in settings.lever_slugs:
            all_jobs.extend(await lever.scrape(slug, client))
            await asyncio.sleep(1)
        await _process_jobs(all_jobs)


async def poll_ashby() -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        all_jobs: list[Job] = []
        for slug in settings.ashby_slugs:
            all_jobs.extend(await ashby.scrape(slug, client))
            await asyncio.sleep(1)
        await _process_jobs(all_jobs)


async def poll_simplify() -> None:
    companies = frozenset(
        s.lower()
        for s in (
            *settings.greenhouse_slugs,
            *settings.lever_slugs,
            *settings.ashby_slugs,
        )
    ) or None  # None = no filter if config is empty
    async with httpx.AsyncClient(timeout=30) as client:
        jobs = await simplify.scrape(client, companies=companies)
        await _process_jobs(jobs)


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    interval = settings.poll_interval_minutes

    # Stagger scrapers to avoid burst traffic
    scheduler.add_job(poll_greenhouse, "interval", minutes=interval, id="greenhouse")
    scheduler.add_job(
        poll_lever, "interval", minutes=interval, id="lever",
        next_run_time=None,  # delay first run
    )
    scheduler.add_job(
        poll_ashby, "interval", minutes=interval, id="ashby",
        next_run_time=None,
    )
    scheduler.add_job(
        poll_simplify, "interval",
        minutes=settings.simplify_poll_interval_minutes,
        id="simplify",
    )

    scheduler.start()
    logger.info("Scheduler started — polling every %d min", interval)
    return scheduler
