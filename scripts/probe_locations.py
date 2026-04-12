"""Location-parse probe across all configured scrapers.

Run with:  uv run python scripts/probe_locations.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make sure the repo root is on sys.path when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from bot.filters import _is_us_location, parse_location
from bot.scrapers import ashby, greenhouse, lever, simplify
from bot.scrapers.workday import scrape as workday_scrape

# ── config ────────────────────────────────────────────────────────────────────

GREENHOUSE_SLUGS = [
    "stripe", "anthropic", "airbnb", "cloudflare", "block", "figma", "datadog",
    "coinbase", "andurilindustries", "waymo", "lucidmotors", "agilityrobotics",
    "rocketlab", "databricks", "brex", "instacart", "doordashusa", "duolingo",
    "samsara", "scaleai", "discord", "robinhood", "vercel", "mercury", "asana",
    "lyft", "reddit", "pinterest", "chime", "twilio", "gusto", "mongodb",
    "roblox", "gleanwork", "cerebrassystems", "xai", "verkada", "launchdarkly",
    "cockroachlabs", "grafanalabs", "airtable", "dropbox", "hubspot", "coupang",
    "smartsheet",
]

LEVER_SLUGS = ["plaid", "outreach", "highspot"]

ASHBY_SLUGS = [
    "rippling", "ramp", "notion", "pulumi", "openai", "perplexity", "replit",
    "1password", "benchling", "harvey", "sentry", "snowflake",
]

WORKDAY_SLUGS = [
    "nvidia.wd5:NVIDIAExternalCareerSite",
    "salesforce.wd12:External_Career_Site",
    "workday.wd5:Workday",
    "intel.wd1:External",
    "bloomberg.wd1:Bloombergindustrygroup_External_Career_Site",
    "disney.wd5:disneycareer",
    "boeing.wd1:EXTERNAL_CAREERS",
    "globalhr.wd5:REC_RTX_Ext_Gateway",
    "ngc.wd1:Northrop_Grumman_External_Site",
    "tmobile.wd1:External",
    "zillow.wd5:Zillow_Group_External",
    "expedia.wd108:search",
    "zoom.wd5:Zoom",
    "wd1.myworkdaysite.com:snapchat:snap",
]

# ── helpers ───────────────────────────────────────────────────────────────────

def _report(platform: str, slug: str, jobs: list) -> None:
    """Print unique location parses for a single scraper result."""
    seen: set[str] = set()
    rows = []
    for j in jobs:
        raw = j.location
        if raw in seen:
            continue
        seen.add(raw)
        first_seg = raw.split(";")[0].split(" / ")[0].strip()
        country, state, city = parse_location(first_seg)
        is_us = _is_us_location(raw)
        rows.append((is_us, raw, country, state, city))

    us_n = sum(1 for r in rows if r[0])
    non_n = len(rows) - us_n
    label = f"{platform}:{slug}"
    print(f"\n{'─'*72}")
    print(f"  {label}")
    print(f"  {len(jobs)} jobs | {len(rows)} unique locs | {us_n} US  {non_n} non-US")
    print()
    for is_us, raw, country, state, city in rows:
        flag = "US " if is_us else "non"
        print(f"  [{flag}] {raw!r:58s} -> {country}/{state}/{city}")


# ── main ──────────────────────────────────────────────────────────────────────

async def run() -> None:
    async with httpx.AsyncClient(timeout=30) as client:

        # ── Greenhouse ────────────────────────────────────────────────────────
        print("\n" + "=" * 72)
        print("  GREENHOUSE")
        print("=" * 72)
        for slug in GREENHOUSE_SLUGS:
            try:
                jobs = await greenhouse.scrape(slug, client)
                _report("greenhouse", slug, jobs)
            except Exception as e:
                print(f"  [ERR] greenhouse:{slug} — {e}")
            await asyncio.sleep(0.5)

        # ── Lever ─────────────────────────────────────────────────────────────
        print("\n" + "=" * 72)
        print("  LEVER")
        print("=" * 72)
        for slug in LEVER_SLUGS:
            try:
                jobs = await lever.scrape(slug, client)
                _report("lever", slug, jobs)
            except Exception as e:
                print(f"  [ERR] lever:{slug} — {e}")
            await asyncio.sleep(0.5)

        # ── Ashby ─────────────────────────────────────────────────────────────
        print("\n" + "=" * 72)
        print("  ASHBY")
        print("=" * 72)
        for slug in ASHBY_SLUGS:
            try:
                jobs = await ashby.scrape(slug, client)
                _report("ashby", slug, jobs)
            except Exception as e:
                print(f"  [ERR] ashby:{slug} — {e}")
            await asyncio.sleep(0.5)

        # ── Simplify ──────────────────────────────────────────────────────────
        print("\n" + "=" * 72)
        print("  SIMPLIFY")
        print("=" * 72)
        try:
            jobs = await simplify.scrape(client)
            _report("simplify", "intern+newgrad", jobs)
        except Exception as e:
            print(f"  [ERR] simplify — {e}")

        # ── Workday ───────────────────────────────────────────────────────────
        print("\n" + "=" * 72)
        print("  WORKDAY  (max 20 each)")
        print("=" * 72)
        for slug in WORKDAY_SLUGS:
            try:
                jobs = await workday_scrape(slug, client, max_jobs=20)
                _report("workday", slug, jobs)
            except Exception as e:
                print(f"  [ERR] workday:{slug} — {e}")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run())
