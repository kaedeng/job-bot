from __future__ import annotations

import asyncio
import logging
from typing import Any

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
from bot.scrapers import ashby, greenhouse, lever, simplify, workday
from bot.scrapers.custom import REGISTRY as _CUSTOM_REGISTRY

logger = logging.getLogger(__name__)

# Set by main.py once the bot is ready
_channel: discord.TextChannel | None = None
_bot: discord.Client | None = None

# Health tracking: consecutive failure counts per scraper (auto-populated)
_FAILURE_ALERT_THRESHOLD = 3
_scraper_failures: dict[str, int] = {
    name: 0
    for name in ("greenhouse", "lever", "ashby", "simplify", "workday", "amazon", *_CUSTOM_REGISTRY)
}


def set_channel(channel: discord.TextChannel) -> None:
    global _channel
    _channel = channel


def set_bot(bot: discord.Client) -> None:
    global _bot
    _bot = bot


def _record_success(scraper: str) -> None:
    _scraper_failures[scraper] = 0


def _record_failure(scraper: str, exc: BaseException) -> None:
    _scraper_failures[scraper] = _scraper_failures.get(scraper, 0) + 1
    count = _scraper_failures[scraper]
    logger.error("%s scraper failed (consecutive failures: %d): %s", scraper, count, exc)


def get_health_status() -> dict[str, int]:
    """Return a snapshot of consecutive failure counts per scraper.

    Public API for commands — avoids reaching into private module globals.
    """
    return dict(_scraper_failures)


def get_failure_threshold() -> int:
    """Return the consecutive-failure count that triggers a health alert."""
    return _FAILURE_ALERT_THRESHOLD


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

    # Batch dedup: single query instead of N individual lookups
    new_cs_jobs = await db.filter_unseen(cs_jobs)

    # Persist all new CS jobs (parse_location runs inside store_jobs_batch)
    if new_cs_jobs:
        await db.store_jobs_batch(new_cs_jobs, parse_locations, classify_job, classify_discipline)

    # Notify only those that also pass the full entry-level/US filter
    to_notify = [j for j in new_cs_jobs if passes_filter(j)]
    if not to_notify:
        return

    logger.info("Found %d new jobs to notify", len(to_notify))
    await notify(to_notify, _channel)


async def _poll_platform(
    name: str,
    slugs: list[str],
    scrape_fn: Any,
    timeout: int = 20,
) -> None:
    """Generic slug-based poll: iterate slugs, scrape, process, track health.

    After each slug is scraped we diff the returned job IDs against the DB and
    increment missing_count for absent jobs; jobs absent for >= 2 consecutive
    scrapes are marked inactive.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            all_jobs: list[Job] = []
            for slug in slugs:
                jobs = await scrape_fn(slug, client)
                all_jobs.extend(jobs)

                # Scrape-diff: detect jobs that have disappeared from the listing
                seen_ids = {j.id for j in jobs}
                deactivated = await db.reconcile_missing_jobs(name, slug, seen_ids)
                if deactivated:
                    logger.info(
                        "%s/%s: marked %d job(s) inactive (absent 2+ scrapes)",
                        name, slug, deactivated,
                    )

                await asyncio.sleep(1)  # be polite
            await _process_jobs(all_jobs)
        _record_success(name)
    except Exception as exc:
        _record_failure(name, exc)
        await _maybe_alert_health()


async def poll_greenhouse() -> None:
    await _poll_platform("greenhouse", settings.greenhouse_slugs, greenhouse.scrape)


async def poll_lever() -> None:
    await _poll_platform("lever", settings.lever_slugs, lever.scrape)


async def poll_ashby() -> None:
    await _poll_platform("ashby", settings.ashby_slugs, ashby.scrape)


async def poll_workday() -> None:
    """Poll all configured Workday career boards.

    Loads already-seen job IDs from the DB once and passes them to each scrape call
    so that description fetches are skipped for jobs we've already stored.  Full
    pagination still runs for every board — Workday sort order isn't reliably
    newest-first, so we can't safely stop early without risking missed postings.
    """
    try:
        seen_ids = await db.get_seen_ids_for_source("workday")
        async with httpx.AsyncClient(timeout=20) as client:
            all_jobs: list[Job] = []
            for slug in settings.workday_slugs:
                all_jobs.extend(await workday.scrape(slug, client, seen_ids=seen_ids))
                await asyncio.sleep(1)
            await _process_jobs(all_jobs)
        _record_success("workday")
    except Exception as exc:
        _record_failure("workday", exc)
        await _maybe_alert_health()


async def poll_simplify() -> None:
    try:
        companies = (
            frozenset(
                s.lower()
                for s in (
                    *settings.greenhouse_slugs,
                    *settings.lever_slugs,
                    *settings.ashby_slugs,
                )
            )
            or None
        )  # None = no filter if config is empty
        async with httpx.AsyncClient(timeout=30) as client:
            jobs = await simplify.scrape(client, companies=companies)
            await _process_jobs(jobs)
        _record_success("simplify")
    except Exception as exc:
        _record_failure("simplify", exc)
        await _maybe_alert_health()


async def _poll_custom(name: str) -> None:
    """Poll a custom scraper by registry name."""
    info = _CUSTOM_REGISTRY[name]
    try:
        async with httpx.AsyncClient(timeout=info.timeout) as client:
            jobs = await info.scrape(client)
            await _process_jobs(jobs)
        _record_success(name)
    except Exception as exc:
        _record_failure(name, exc)
        await _maybe_alert_health()


def run_custom_scrapers() -> list[Any]:
    """Return a list of coroutines for all enabled custom scrapers (for asyncio.gather)."""
    return [_poll_custom(name) for name in settings.custom_scrapers if name in _CUSTOM_REGISTRY]


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


async def poll_user_alerts() -> None:
    """Send DM job alerts to users whose interval has elapsed."""
    from bot.alerts import send_user_alerts

    if _bot is None:
        logger.warning("Bot not set — skipping user alert poll")
        return
    try:
        await send_user_alerts(_bot)
    except Exception as exc:
        logger.error("User alert poll failed: %s", exc)


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
                    posting["source"],
                    posting["job_id"],
                    posting["id"],
                )
            await asyncio.sleep(0.5)  # be polite

    if expired:
        logger.info(
            "Liveness check complete: %d expired, %d still active", expired, len(postings) - expired
        )


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    interval = settings.poll_interval_minutes

    # Stagger scrapers to avoid burst traffic
    scheduler.add_job(poll_greenhouse, "interval", minutes=interval, id="greenhouse")
    scheduler.add_job(
        poll_lever,
        "interval",
        minutes=interval,
        id="lever",
        next_run_time=None,  # delay first run
    )
    scheduler.add_job(
        poll_ashby,
        "interval",
        minutes=interval,
        id="ashby",
        next_run_time=None,
    )
    scheduler.add_job(poll_workday, "interval", minutes=interval, id="workday")
    scheduler.add_job(
        poll_simplify,
        "interval",
        minutes=settings.simplify_poll_interval_minutes,
        id="simplify",
    )

    # Custom scrapers — driven by CUSTOM_SCRAPERS env var + registry
    for name in settings.custom_scrapers:
        if name not in _CUSTOM_REGISTRY:
            logger.warning("Unknown custom scraper %r in CUSTOM_SCRAPERS — skipping", name)
            continue
        info = _CUSTOM_REGISTRY[name]
        interval_mins = settings.custom_scraper_interval_minutes or info.default_interval_minutes
        scheduler.add_job(
            _poll_custom,
            "interval",
            args=[name],
            minutes=interval_mins,
            id=name,
            next_run_time=None,  # stagger: first run happens in on_ready
        )

    # User DM alerts — checked every 2 min; actual delivery respects per-user intervals
    scheduler.add_job(poll_user_alerts, "interval", minutes=2, id="user_alerts")
    # Periodic health check — re-alerts every hour while scrapers stay broken
    scheduler.add_job(_maybe_alert_health, "interval", minutes=60, id="health")
    # URL liveness probe — catches dead Simplify/Workday links (not slug-based scrapers,
    # which use scrape-diff instead). Runs every 6 hours, deferred first run.
    scheduler.add_job(poll_liveness, "interval", hours=6, id="liveness", next_run_time=None)

    scheduler.start()
    logger.info("Scheduler started — polling every %d min", interval)
    return scheduler
