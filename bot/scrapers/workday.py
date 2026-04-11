from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from bot.company_names import resolve
from bot.models import Job

logger = logging.getLogger(__name__)

_PAGE_SIZE = 20

# Workday requires these headers or it returns 415 / empty results
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


@dataclass(frozen=True, slots=True)
class _WorkdayConfig:
    """Resolved URLs and identifiers for a Workday career board."""

    base: str        # e.g. https://bloomberg.wd1.myworkdayjobs.com
    org: str         # tenant/org used in API path, e.g. bloomberg or snapchat
    board: str       # career board name
    job_prefix: str  # prefix for public job URLs (everything before externalPath)
    company: str     # display name — first part of org

    @property
    def list_url(self) -> str:
        return f"{self.base}/wday/cxs/{self.org}/{self.board}/jobs"

    def detail_url(self, external_path: str) -> str:
        return f"{self.base}/wday/cxs/{self.org}/jobs{external_path}"

    def job_url(self, external_path: str) -> str:
        return f"{self.job_prefix}{external_path}"


def _parse_slug(slug: str) -> _WorkdayConfig:
    """Parse a Workday slug string into a resolved config.

    Two supported formats:

    1. Company-subdomain style (myworkdayjobs.com):
       'bloomberg.wd1:Bloombergindustrygroup_External_Career_Site'
       → base = https://bloomberg.wd1.myworkdayjobs.com
       → org  = bloomberg  (subdomain prefix)
       → board = Bloombergindustrygroup_External_Career_Site

    2. Shared-domain style (myworkdaysite.com):
       'wd1.myworkdaysite.com:snapchat:snap'
       → base = https://wd1.myworkdaysite.com
       → org  = snapchat
       → board = snap
    """
    parts = slug.split(":", 2)

    if len(parts) == 2:
        # myworkdayjobs.com — company subdomain
        host, board = parts
        base = f"https://{host}.myworkdayjobs.com"
        org = host.split(".")[0]
        job_prefix = f"{base}/en-US/{board}"

    elif len(parts) == 3:
        # myworkdaysite.com (or other shared domain) — full domain + org + board
        domain, org, board = parts
        base = f"https://{domain}"
        job_prefix = f"{base}/en-US/recruiting/{org}/{board}"

    else:
        raise ValueError(
            f"Invalid Workday slug {slug!r}. Expected 'host:board' or 'domain:org:board'."
        )

    company = resolve(org.split(".")[0])
    return _WorkdayConfig(base=base, org=org, board=board, job_prefix=job_prefix, company=company)


def _extract_job_id(external_path: str) -> str:
    """Extract the requisition ID from the externalPath trailing segment.

    '/job/New-York/Software-Engineer_R123456' → 'R123456'
    Falls back to the full path if the pattern doesn't match.
    """
    tail = external_path.rstrip("/").rsplit("/", 1)[-1]
    if "_" in tail:
        return tail.rsplit("_", 1)[-1]
    return tail


async def _fetch_description(
    cfg: _WorkdayConfig, external_path: str, client: httpx.AsyncClient
) -> str | None:
    """Fetch the job description HTML from the Workday detail endpoint."""
    url = cfg.detail_url(external_path)
    try:
        resp = await client.get(url, headers=_HEADERS)
        resp.raise_for_status()
        info = resp.json().get("jobPostingInfo", {})
        return info.get("jobDescription") or None
    except httpx.HTTPError as e:
        logger.debug("Workday detail fetch failed for %s: %s", external_path, e)
        return None


async def scrape(slug: str, client: httpx.AsyncClient, max_jobs: int | None = None) -> list[Job]:
    """Scrape all active jobs from a Workday career board.

    Slug formats:
      'bloomberg.wd1:Bloombergindustrygroup_External_Career_Site'  (myworkdayjobs.com)
      'wd1.myworkdaysite.com:snapchat:snap'                        (myworkdaysite.com)

    Args:
        max_jobs: If set, stop after collecting this many jobs (useful for testing).
    """
    try:
        cfg = _parse_slug(slug)
    except ValueError as e:
        logger.error("Workday slug parse error: %s", e)
        return []

    # Lazy import to avoid circular dependency
    from bot.filters import is_tech_job

    jobs: list[Job] = []
    offset = 0
    total: int | None = None  # only populated on first page by Workday API

    while True:
        page_size = _PAGE_SIZE
        if max_jobs is not None:
            remaining = max_jobs - len(jobs)
            if remaining <= 0:
                break
            page_size = min(_PAGE_SIZE, remaining)

        payload = {
            "appliedFacets": {},
            "limit": page_size,
            "offset": offset,
            "searchText": "",
        }
        try:
            resp = await client.post(cfg.list_url, json=payload, headers=_HEADERS)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Workday %s failed at offset %d: %s", slug, offset, e)
            break

        data = resp.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break

        # total is only non-zero on the first response; capture it once
        if total is None:
            total = data.get("total", 0)

        for item in postings:
            external_path: str = item.get("externalPath", "")
            job_id = _extract_job_id(external_path) if external_path else item.get("title", "")

            jobs.append(
                Job(
                    id=job_id,
                    title=item.get("title", ""),
                    company=cfg.company,
                    location=item.get("locationsText", ""),
                    url=cfg.job_url(external_path),
                    source="workday",
                )
            )

        offset += _PAGE_SIZE
        if offset >= (total or 0):
            break

        await asyncio.sleep(1)  # be polite between pages

    # Fetch descriptions only for tech-relevant jobs to limit extra requests
    tech_jobs = [j for j in jobs if is_tech_job(j)]
    if tech_jobs:
        logger.debug("Workday %s: fetching descriptions for %d tech jobs", slug, len(tech_jobs))
        path_to_desc: dict[str, str | None] = {}
        for job in tech_jobs:
            external_path = job.url[len(cfg.job_prefix):]
            desc = await _fetch_description(cfg, external_path, client)
            path_to_desc[job.url] = desc
            await asyncio.sleep(0.5)  # be polite between detail requests

        jobs = [
            Job(
                id=j.id,
                title=j.title,
                company=j.company,
                location=j.location,
                url=j.url,
                source=j.source,
                posted_at=j.posted_at,
                description=path_to_desc.get(j.url),
            )
            if j.url in path_to_desc
            else j
            for j in jobs
        ]

    return jobs
