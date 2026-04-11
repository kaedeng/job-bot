# Job Scraper Bot

Discord bot that polls job posting sources and notifies on new entry-level/intern SWE and EE roles in the US.

## Stack
- Python 3.11+, `discord.py` (bot client), `httpx` (async HTTP for scrapers), `APScheduler` (scheduling), `aiosqlite` (SQLite), `pydantic-settings`, `uv`

## Structure
```
bot/
├── main.py                # entrypoint — discord.py Client, on_ready kicks off scraping
├── config.py              # pydantic-settings, reads .env
├── models.py              # Job dataclass (shared by all scrapers)
├── filters.py             # keyword + location + level logic
├── db.py                  # aiosqlite — job_postings dedup + user preferences
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
Two-stage filter. Target: intern and new-grad/entry-level SWE and EE roles, US only.

**Stage 1 — Tech relevance** (`is_tech_job`): title must match `DISCIPLINE_INCLUDE` regex. Covers both SWE and EE keywords. All passing jobs are stored in `job_postings`.

**Stage 2 — Entry-level classification** (`classify_job` → `passes_filter`):
- `classify_job(job) -> (is_intern, is_new_grad)`:
  1. Source trust: `simplify-intern` → intern, `simplify-newgrad` → new_grad
  2. Title: `_INTERN_TITLE` (intern, internship, co-op) / `_NEW_GRAD_TITLE` (new grad, university grad, entry level, junior, jr., associate, early career, campus hire, swe i, l3)
  3. Description (Greenhouse + Lever only): `_INTERN_DESC` / `_NEW_GRAD_DESC` patterns; `_SENIOR_EXP` (4+ years of experience) forces both False
- `passes_filter(job)`: title not in `TITLE_EXCLUDE` (senior, staff, principal, manager, lead, sr.), `classify_job` returns at least one True, title matches `DISCIPLINE_INCLUDE`, location is US

**Discipline classification** (`classify_discipline(job) -> str`):
- `"swe"` — title matches `_SWE_DISCIPLINE` (software, ml, backend, frontend, cloud, data engineer, etc.)
- `"ee"` — title matches `_EE_DISCIPLINE` (electrical, hardware, embedded, fpga, asic, pcb, rf, analog, etc.) and no SWE match
- `"unknown"` — neither signal present
- Stored in `discipline` column on `job_postings`; filterable via `/query`

## Scraper Behavior
- Greenhouse/Lever/Ashby: one generic `scrape(slug, client)` function per platform, company = slug in config list
- Simplify: `scrape(client)` — no slugs, fetches both intern and new-grad listings
- All scrapers return `list[Job]` with common fields: `id, title, company, location, url, source, posted_at, description`
- `description` is HTML-stripped and stored as `description_text` (max 5000 chars) in `job_postings` for keyword search; Greenhouse and Lever populate it; Ashby list endpoint doesn't expose it; Simplify is classified by source name
- Dedup via `job_postings` table `UNIQUE (source, job_id)` — `INSERT OR IGNORE` skips already-seen jobs
- Only tech-relevant jobs (title matches DISCIPLINE_INCLUDE) are stored in `job_postings`
- Only unseen CS jobs that pass the full entry-level/US filter reach the notifier
- Each slug request has a 1-second sleep between calls to be polite

## Database Schema

Single SQLite file (`jobs.db` by default). Three tables:

### `job_postings`
Stores every tech-relevant job returned by scrapers. Replaces the old `seen_jobs` table. Dedup via `UNIQUE (source, job_id)` + `INSERT OR IGNORE`. Location stored as raw string; parsed breakdowns live in `job_locations`.

```sql
CREATE TABLE IF NOT EXISTS job_postings (
    id           INTEGER   PRIMARY KEY AUTOINCREMENT,
    source       TEXT      NOT NULL,              -- greenhouse | lever | ashby | simplify
    job_id       TEXT      NOT NULL,              -- platform-assigned ID
    title        TEXT      NOT NULL,
    company      TEXT      NOT NULL,
    location_raw TEXT      NOT NULL,              -- unparsed string from scraper
    url          TEXT      NOT NULL,
    posted_at    TIMESTAMP,                       -- from scraper, nullable
    ingested_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_intern    INTEGER,                         -- 1/0/NULL (NULL = unclassified)
    is_new_grad  INTEGER,                         -- 1/0/NULL
    is_remote    INTEGER   NOT NULL DEFAULT 0,    -- 1 if any location segment is remote
    discipline   TEXT      NOT NULL DEFAULT 'unknown',  -- "swe" | "ee" | "unknown"
    description_text TEXT,                              -- HTML-stripped description, max 5000 chars
    UNIQUE (source, job_id)
);

CREATE TABLE IF NOT EXISTS job_locations (
    id          INTEGER   PRIMARY KEY AUTOINCREMENT,
    posting_id  INTEGER   NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    country     TEXT,                            -- parsed ISO code, e.g. "US", "GB"
    state       TEXT,                            -- US state abbrev, e.g. "CA"
    city        TEXT,                            -- parsed city name
    is_remote   INTEGER   NOT NULL DEFAULT 0     -- 1 if this segment is remote
);
```

### `user_preferences`
Per-Discord-user notification and delivery settings. Filter logic lives in `user_filter_rules`.

```sql
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id                TEXT      PRIMARY KEY,
    dm_enabled             INTEGER   NOT NULL DEFAULT 1,
    alert_interval_minutes INTEGER   NOT NULL DEFAULT 60,
    quiet_hours_start      TEXT,                          -- "HH:MM" | NULL
    quiet_hours_end        TEXT,                          -- "HH:MM" | NULL
    companies              TEXT      NOT NULL DEFAULT '[]',  -- JSON slug list; [] = all
    created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### `user_filter_rules`
Additive filter tuples. Each row = one independent filter; a user is notified if ANY rule matches (OR logic). Combines role type with location scope.

```sql
CREATE TABLE IF NOT EXISTS user_filter_rules (
    id             INTEGER   PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT      NOT NULL REFERENCES user_preferences(user_id) ON DELETE CASCADE,
    role_type      TEXT      NOT NULL,  -- "intern" | "new_grad" | "entry_level"
    location_scope TEXT      NOT NULL,  -- "us" | "remote" | "country:XX" | "state:XX" | "city:Name"
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Example: `(intern, us)` + `(entry_level, state:CO)` = internships anywhere in US OR entry-level roles in Colorado.

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
DISCORD_GUILD_ID=123456789012345678  # optional; enables instant guild-scoped slash command sync
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
