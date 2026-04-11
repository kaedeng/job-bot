from __future__ import annotations

import asyncio
import logging

import discord
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import db
from bot.config import settings
from bot.filters import (
    classify_discipline,
    classify_job,
    is_tech_job,
    parse_locations,
    passes_filter,
)
from bot.models import Job
from bot.notifier import notify
from bot.scrapers import ashby, greenhouse, lever, simplify

logger = logging.getLogger(__name__)

# Set by main.py once the bot is ready
_channel: discord.TextChannel | None = None

# Health tracking: consecutive failure counts per scraper
_FAILURE_ALERT_THRESHOLD = 3
_scraper_failures: dict[str, int] = {
    "greenhouse": 0,
    "lever": 0,
    "ashby": 0,
    "simplify": 0,
}


def set_channel(channel: discord.TextChannel) -> None:
    global _channel
    _channel = channel


def _record_success(scraper: str) -> None:
    _scraper_failures[scraper] = 0


def _record_failure(scraper: str, exc: BaseException) -> None:
    _scraper_failures[scraper] = _scraper_failures.get(scraper, 0) + 1
    count = _scraper_failures[scraper]
    logger.error("%s scraper failed (consecutive failures: %d): %s", scraper, count, exc)


async def _maybe_alert_health() -> None:
    """Send a Discord alert for any scraper that has hit the failure threshold."""
    if _channel is None:
        return
    for scraper, count in _scraper_failures.items():
        if count >= _FAILURE_ALERT_THRESHOLD:
            embed = discord.Embed(
                title="Scraper health alert",
                description=(
                    f"**{scraper}** scraper has failed **{count}** consecutive times. "
                    "Check logs for details."
                ),
                color=discord.Color.red(),
            )
            await _channel.send(embed=embed)  # type: ignore[union-attr]


async def _process_jobs(jobs: list[Job]) -> None:
    """Dedup, store CS jobs, filter to entry-level/US, and notify."""
    if _channel is None:
        logger.error("Channel not set — skipping notification")
        return

    # Pre-filter to tech-relevant roles before touching the DB
    cs_jobs = [j for j in jobs if is_tech_job(j)]

    # Determine which CS jobs are new (not yet in job_postings)
    new_cs_jobs: list[Job] = []
    for job in cs_jobs:
        if not await db.is_seen(job.source, job.id):
            new_cs_jobs.append(job)

    # Persist all new CS jobs (parse_location runs inside store_jobs_batch)
    if new_cs_jobs:
        await db.store_jobs_batch(new_cs_jobs, parse_locations, classify_job, classify_discipline)

    # Notify only those that also pass the full entry-level/US filter
    to_notify = [j for j in new_cs_jobs if passes_filter(j)]
    if not to_notify:
        return

    logger.info("Found %d new jobs to notify", len(to_notify))
    await notify(to_notify, _channel)


async def poll_greenhouse() -> None:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            all_jobs: list[Job] = []
            for slug in settings.greenhouse_slugs:
                all_jobs.extend(await greenhouse.scrape(slug, client))
                await asyncio.sleep(1)  # be polite
            await _process_jobs(all_jobs)
        _record_success("greenhouse")
    except Exception as exc:
        _record_failure("greenhouse", exc)
        await _maybe_alert_health()


async def poll_lever() -> None:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            all_jobs: list[Job] = []
            for slug in settings.lever_slugs:
                all_jobs.extend(await lever.scrape(slug, client))
                await asyncio.sleep(1)
            await _process_jobs(all_jobs)
        _record_success("lever")
    except Exception as exc:
        _record_failure("lever", exc)
        await _maybe_alert_health()


async def poll_ashby() -> None:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            all_jobs: list[Job] = []
            for slug in settings.ashby_slugs:
                all_jobs.extend(await ashby.scrape(slug, client))
                await asyncio.sleep(1)
            await _process_jobs(all_jobs)
        _record_success("ashby")
    except Exception as exc:
        _record_failure("ashby", exc)
        await _maybe_alert_health()


async def poll_simplify() -> None:
    try:
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
        _record_success("simplify")
    except Exception as exc:
        _record_failure("simplify", exc)
        await _maybe_alert_health()


async def _check_url_live(client: httpx.AsyncClient, url: str) -> bool:
    """Return False only on a definitive 404. Treat network errors as still-live."""
    try:
        resp = await client.head(url, follow_redirects=True, timeout=15)
        if resp.status_code == 404:
            return False
        if resp.status_code == 405:
            # HEAD not supported — fall back to GET
            resp = await client.get(url, follow_redirects=True, timeout=15)
            return resp.status_code != 404
        return True
    except httpx.RequestError:
        return True  # network blip — don't mark dead on transient errors


async def poll_liveness() -> None:
    """Probe stored active postings and mark any 404s as inactive."""
    postings = await db.get_postings_due_for_liveness_check(
        min_age_hours=1,
        recheck_interval_hours=24,
        batch_size=100,
    )
    if not postings:
        return

    logger.info("Liveness check: probing %d postings", len(postings))
    expired = 0
    async with httpx.AsyncClient(timeout=15) as client:
        for posting in postings:
            live = await _check_url_live(client, posting["url"])
            if live:
                await db.touch_liveness_check(posting["id"])
            else:
                await db.mark_job_inactive(posting["id"])
                expired += 1
                logger.info(
                    "Marked inactive: [%s] %s (id=%d)",
                    posting["source"], posting["job_id"], posting["id"],
                )
            await asyncio.sleep(0.5)  # be polite

    if expired:
        logger.info("Liveness check complete: %d expired, %d still active", expired, len(postings) - expired)


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
    # Periodic health check — re-alerts every hour while scrapers stay broken
    scheduler.add_job(_maybe_alert_health, "interval", minutes=60, id="health")
    # Liveness verification — probe stored active postings every 6 hours
    scheduler.add_job(poll_liveness, "interval", hours=6, id="liveness", next_run_time=None)

    scheduler.start()
    logger.info("Scheduler started — polling every %d min", interval)
    return scheduler
