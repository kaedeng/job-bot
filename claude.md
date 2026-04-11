# Job Scraper Bot

Discord bot that polls job posting sources and notifies on new entry-level/intern SWE roles in the US.

## Stack
- Python 3.11+, `discord.py` (bot client), `httpx` (async HTTP for scrapers), `APScheduler` (scheduling), `aiosqlite` (SQLite), `pydantic-settings`, `uv`

## Structure
```
bot/
├── main.py                # entrypoint — discord.py Client, on_ready kicks off scraping
├── config.py              # pydantic-settings, reads .env
├── models.py              # Job dataclass (shared by all scrapers)
├── filters.py             # keyword + location + level logic
├── db.py                  # seen-IDs via SQLite (aiosqlite)
├── notifier.py            # sends discord.Embed messages to the configured channel
├── scheduler.py           # APScheduler — poll functions + orchestration
└── scrapers/
    ├── greenhouse.py      # slug-based, boards-api.greenhouse.io
    ├── lever.py           # slug-based, api.lever.co
    ├── ashby.py           # GraphQL, jobs.ashbyhq.com
    ├── simplify.py        # raw GitHub JSON (intern + new grad repos)
    └── custom/            # google, meta, amazon etc. (not yet implemented)
```

## Running
```bash
cp .env.example .env       # fill in bot token + channel ID + slugs
uv sync                    # install deps
python -m bot.main         # run the bot
```

## Sources
- **Greenhouse** `GET boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`
- **Lever** `GET api.lever.co/v0/postings/{slug}?mode=json`
- **Ashby** `POST jobs.ashbyhq.com/api/non-user-graphql` (GraphQL, operationName: ApiJobBoardWithTeams)
- **Simplify** raw GitHub JSON — `SimplifyJobs/Summer2025-Internships` and `SimplifyJobs/New-Grad-Positions` (`/dev/.github/scripts/listings.json`)
- **Custom scrapers** for Google, Meta, Amazon, Apple, Microsoft, Uber — target backing JSON APIs via DevTools, not HTML (not yet implemented)

## Filtering (filters.py)
Target: entry-level and intern SWE roles, US only, any season

- **Title include (regex):** `intern`, `internship`, `new grad`, `university grad`, `entry level`, `swe i`, `software engineer i`, `l3`
- **Title exclude (regex):** `senior`, `staff`, `principal`, `manager`, `lead`, `sr.`
- **Location:** must contain a US state name, state abbreviation, known city, or keyword (`united states`, `usa`, `u.s.`, `remote`)

## Scraper Behavior
- Greenhouse/Lever/Ashby: one generic `scrape(slug, client)` function per platform, company = slug in config list
- Simplify: `scrape(client)` — no slugs, fetches both intern and new-grad listings
- All scrapers return `list[Job]` with common fields: `id, title, company, location, url, source, posted_at`
- Dedup via SQLite `seen_jobs` table keyed on `(source, job_id)`
- Only unseen jobs that pass filters reach the notifier
- Each slug request has a 1-second sleep between calls to be polite

## Scheduling
- Greenhouse / Lever / Ashby: every `POLL_INTERVAL_MINUTES` (default 10)
- Simplify: every `SIMPLIFY_POLL_INTERVAL_MINUTES` (default 30)
- Lever and Ashby first runs are deferred (`next_run_time=None`) to stagger traffic
- All scrapers run once immediately on startup (in `on_ready`) before scheduler takes over

## Discord
- Full `discord.py` bot client — connects to gateway, sends embeds to a configured channel
- One embed per job: title + company, location, apply link, Discord blurple accent
- Batched up to 10 embeds per message (Discord API limit)
- Channel is resolved by `DISCORD_CHANNEL_ID` on bot ready

## Config (env vars via pydantic-settings)
```
DISCORD_TOKEN=your-bot-token
DISCORD_CHANNEL_ID=123456789012345678
GREENHOUSE_SLUGS=stripe,anthropic,airbnb,...
LEVER_SLUGS=netflix,github,...
ASHBY_SLUGS=rippling,ramp,...
POLL_INTERVAL_MINUTES=10
SIMPLIFY_POLL_INTERVAL_MINUTES=30
DB_PATH=jobs.db
META_ENABLED=false
META_POLL_INTERVAL_MINUTES=30
```

## Known Difficult Sites
- **NVIDIA, Snap** — Workday, session tokens, avoid or deprioritize
- **Meta** — Cloudflare, aggressive rate limiting, poll conservatively (30 min+)
- **Epic Games** — own system, low intern volume, low priority
- **HashiCorp** — IBM acquisition, careers infra may be in flux

## Deployment
Single persistent process on Railway, Render, or Hetzner ($5/mo). No serverless — scheduler requires persistence and bot needs a gateway connection.

## Dev
- Linting: `uv run ruff check .`
- Formatting: `uv run ruff format .`
- Tests: `uv run pytest`
- Dev deps: `uv sync --extra dev`
