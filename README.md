# discord-job-bot

A Discord bot that polls job boards for entry-level and intern software engineering roles in the US, and posts them to a channel.

Supported sources: Greenhouse, Lever, Ashby, and Simplify (GitHub-based community lists).

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A Discord bot token and a server to add it to

## Quick Start

### 1. Clone and install

```bash
git clone <your-repo-url>
cd discord-job-bot
uv sync
```

Or with pip:

```bash
pip install -e .
```

### 2. Create a Discord bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**, give it a name
3. Go to **Bot** in the sidebar
4. Click **Reset Token** and copy your bot token
5. Under **Privileged Gateway Intents**, enable **Server Members Intent** — required to look up users for DM delivery
6. Go to **OAuth2 > URL Generator**
7. Select scopes: **bot**, **applications.commands**
8. Select permissions: **Send Messages**, **Embed Links**
9. Copy the generated URL, open it, and add the bot to your server

> **DM note:** Discord bots can only DM users who share a server with the bot. Users must also have **Allow direct messages from server members** enabled in their Discord privacy settings (Settings > Privacy & Safety). If this is off, the DM will silently fail with a 403.

### 3. Get the channel ID

1. In Discord, go to **User Settings > Advanced** and enable **Developer Mode**
2. Right-click the channel where you want job postings
3. Click **Copy Channel ID**

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
DISCORD_TOKEN=your-bot-token-here
DISCORD_CHANNEL_ID=123456789012345678
DISCORD_GUILD_ID=123456789012345678

# Comma-separated company slugs for each platform
GREENHOUSE_SLUGS=stripe,anthropic,airbnb,cloudflare,figma
LEVER_SLUGS=netflix
ASHBY_SLUGS=rippling,ramp
```

**Finding company slugs:**

- **Greenhouse:** Visit `https://boards.greenhouse.io/<company>` — the URL slug is what you need (e.g., `stripe`, `anthropic`)
- **Lever:** Visit `https://jobs.lever.co/<company>` — same idea (e.g., `netflix`)
- **Ashby:** Visit `https://jobs.ashbyhq.com/<company>` (e.g., `rippling`, `ramp`)

### 5. Run the bot

```bash
python -m bot.main
```

On first run, the bot will:

1. Connect to Discord and log in
2. Create the SQLite database (`jobs.db`)
3. Scrape all configured sources immediately
4. Send matching jobs as embeds to your channel
5. Start the recurring poll scheduler

## How It Works

### Pipeline

```
Scrapers → CS filter → Dedup → Store → Classify → Entry-level filter → Notify
```

1. **Scrapers** fetch job listings from each platform's API (with description text where available)
2. **CS filter** drops clearly non-CS roles (e.g. Chef, HR) using a discipline keyword check
3. **Dedup** checks `job_postings` to skip already-seen jobs
4. **Store** persists all new CS jobs to `job_postings` with parsed location and classification flags
5. **Classify** runs `classify_job()` to set `is_intern` / `is_new_grad` per job
6. **Entry-level filter** keeps only jobs that are intern or new-grad AND in the US
7. **Notifier** sends matching jobs to the Discord channel as embedded messages

### Filtering

Two-stage filter:

**Stage 1 — Tech relevance** (storage gate, `is_tech_job`):

- Title must contain a software or electrical engineering keyword (`software`, `engineer`, `developer`, `data`, `ml`, `backend`, `frontend`, `electrical`, `hardware`, `embedded`, `fpga`, etc.)
- Rejects non-tech roles that appear on curated company boards
- All passing jobs are stored in `job_postings` regardless of level or location

**Stage 2 — Entry-level classification** (`classify_job`), checked in priority order:

1. **Source trust** — Simplify's `Summer-Internships` repo → `is_intern`; `New-Grad-Positions` repo → `is_new_grad`
2. **Title signals**:
   - Intern: `intern`, `internship`, `co-op`
   - New grad: `new grad`, `university grad`, `entry level`, `junior`, `jr.`, `associate`, `early career`, `campus hire`, `swe i`, `software engineer i`, `l3`
3. **Description scanning** (Greenhouse and Lever only — Ashby list endpoint doesn't expose descriptions):
   - Intern signals: `intern`, `internship`, `co-op` in body
   - New-grad signals: `new grad`, `recent grad`, `entry level`, `0–2 years`, `no experience required`, `early career`
   - Exclusion: if description demands `4+ years of experience`, job is excluded regardless of title

**Discipline classification** (`classify_discipline`):

- `swe` — title matches SWE keywords (`software`, `ml`, `backend`, `frontend`, `data engineer`, `cloud`, etc.)
- `ee` — title matches EE keywords (`electrical`, `hardware`, `embedded`, `fpga`, `asic`, `vlsi`, `pcb`, `rf`, `analog`, `circuit`, etc.) and no SWE match
- `unknown` — title has neither clear SWE nor EE signal
- Stored in the `discipline` column; filterable via `/query discipline:`

**Stage 2 — Location** (`passes_filter`):

- Title must NOT match: `senior`, `staff`, `principal`, `manager`, `lead`, `sr.`
- Location must be US — state names, state abbreviations, known cities, or keywords like `united states`, `usa`, `remote`

### Scheduling

| Source        | Interval | Notes                                             |
| ------------- | -------- | ------------------------------------------------- |
| Greenhouse    | 10 min   | Configurable via `POLL_INTERVAL_MINUTES`          |
| Lever         | 10 min   | Staggered start                                   |
| Ashby         | 10 min   | Staggered start                                   |
| Simplify      | 30 min   | Configurable via `SIMPLIFY_POLL_INTERVAL_MINUTES` |
| User alerts   | 2 min    | Checks all users; delivers per each user's interval |

Scrapers are staggered so they don't all fire at the same instant. Each individual slug request includes a 1-second delay to be polite to APIs.

### Discord Output

Each new job appears as an embed with:

- Job title and company name
- Location
- Direct link to the application page

When many jobs are found in a single cycle, they're batched into messages of up to 10 embeds each.

### Slash Commands

| Command | Description |
|---------|-------------|
| `/query` | Search the jobs database with optional filters (keyword, company, role, discipline, state, season). Results are paginated with ← Prev / Next → buttons. |
| `/scout <company> <platform>` | Live-scrape a company+platform on demand to spot-check a slug before adding it to `.env`. |
| `/alert` | Open a 6-step DM wizard to set up personalised job alert notifications. |
| `/alert-status` | View your current alert preferences (ephemeral). |
| `/alert-off` | Pause DM alerts. |
| `/alert-resume` | Re-enable paused alerts. |
| `/alert-test` | Immediately trigger a test DM with your current matching jobs (all time). |
| `/health` | Show scraper health and consecutive failure counts. |

### Job Alert DMs

Users can subscribe to personalised job alerts delivered via Discord DM. The `/alert` wizard collects:

1. **Role types** — Internships, New Grad / Entry Level, or both
2. **Discipline** — SWE, EE, or both
3. **Location** — Anywhere in the US, Remote only, Specific US state(s) (e.g. `CO, WA`), Specific country (ISO code), or Anywhere worldwide
4. **Check interval** — 1 min (testing) through once a day
5. **Optional filters** — keyword(s) matching title/description, company name(s)
6. **Optional quiet hours** — UTC time window during which no DMs are sent

Preferences are stored in `user_preferences` + `user_filter_rules`. The scheduler checks every 2 minutes and delivers to any user whose interval has elapsed. New users receive only jobs from the last 24 hours to avoid a flood on first run. Results are paginated with a **Next →** / **← Prev** button.

### Liveness & Health Monitoring

Each scraper tracks consecutive failures in memory. If a scraper fails **3 or more times in a row**, the bot posts a red embed to the configured Discord channel:

> **Scraper health alert**
> `greenhouse` scraper has failed **3** consecutive times. Check logs for details.

A periodic job re-checks all failure counts every 60 minutes and re-alerts while a scraper stays broken. Failures reset to zero on the next successful poll.

#### Posting liveness verification

Every 6 hours the bot re-probes stored active postings to confirm the listing URLs are still live. A `HEAD` request is sent to each job URL (falling back to `GET` on 405); a definitive `404` marks the posting `is_active = 0` in `job_postings`. Network errors and non-404 responses (including 429/5xx) are treated as still-live to avoid false positives.

Only postings ingested at least 1 hour ago and not checked in the last 24 hours are probed per cycle (up to 100 per run). The `/query` command and the notifier both exclude inactive postings automatically.

## Database Schema

The bot uses a single SQLite file (`jobs.db` by default, configurable via `DB_PATH`).

### `job_postings`

Canonical record for every CS-relevant job returned by any scraper. Serves as both the full job store and the dedup layer — `INSERT OR IGNORE` on the unique `(source, job_id)` key skips duplicates. Location is stored as a raw string and parsed components to support per-user location-scoped filters.

| Column         | Type       | Description                                                                |
| -------------- | ---------- | -------------------------------------------------------------------------- |
| `id`           | INTEGER PK | Auto-incrementing row ID                                                   |
| `source`       | TEXT       | `greenhouse`, `lever`, `ashby`, or `simplify`                              |
| `job_id`       | TEXT       | Platform-assigned job ID                                                   |
| `title`        | TEXT       | Job title                                                                  |
| `company`      | TEXT       | Company name                                                               |
| `location_raw` | TEXT       | Unparsed location string from the source                                   |
| `url`          | TEXT       | Direct link to the job posting                                             |
| `posted_at`    | TIMESTAMP  | Posting date from the source (nullable)                                    |
| `ingested_at`  | TIMESTAMP  | When the bot first saw this job (UTC, auto-set)                            |
| `is_intern`    | INTEGER    | `1` = classified as internship, `0` = not, `NULL` = unclassified           |
| `is_new_grad`  | INTEGER    | `1` = classified as new-grad/entry-level, `0` = not, `NULL` = unclassified |
| `is_remote`    | INTEGER    | `1` if any of the job's locations is remote                                |
| `discipline`   | TEXT       | `swe`, `ee`, or `unknown` — classified from job title at ingestion         |
| `description_text` | TEXT   | HTML-stripped description, max 5 000 chars (Greenhouse + Lever only)   |
| `is_active`    | INTEGER    | `0` once a liveness check returns 404                                      |
| `last_checked_at` | TIMESTAMP | Last liveness probe timestamp                                          |

Unique constraint: `(source, job_id)`

### `job_locations`

One row per location per job. Multi-location postings (e.g. `"London, UK; Remote, US; San Francisco, CA"`) produce multiple rows. Linked to `job_postings` via `posting_id`.

| Column       | Type       | Description                                        |
| ------------ | ---------- | -------------------------------------------------- |
| `id`         | INTEGER PK | Auto-incrementing row ID                           |
| `posting_id` | INTEGER    | FK → `job_postings.id` (cascade delete)            |
| `country`    | TEXT       | Parsed country code, e.g. `US`, `GB` (nullable)    |
| `state`      | TEXT       | Parsed US state abbreviation, e.g. `CA` (nullable) |
| `city`       | TEXT       | Parsed city name (nullable)                        |
| `is_remote`  | INTEGER    | `1` if this specific location segment is remote    |

### `user_preferences`

Per-Discord-user notification and delivery settings. Filter logic lives in `user_filter_rules`.

| Column                   | Type        | Default | Description                                                |
| ------------------------ | ----------- | ------- | ---------------------------------------------------------- |
| `user_id`                | TEXT PK     | —       | Discord user snowflake ID                                  |
| `dm_enabled`             | INTEGER     | `1`     | Whether to send DM notifications                           |
| `alert_interval_minutes` | INTEGER     | `60`    | How often to check for new matches                         |
| `quiet_hours_start`      | TEXT        | NULL    | Quiet window start, e.g. `"22:00"` (NULL = disabled)       |
| `quiet_hours_end`        | TEXT        | NULL    | Quiet window end, e.g. `"08:00"`                           |
| `companies`              | TEXT (JSON) | `[]`    | Company slugs to follow (empty = all configured companies) |
| `disciplines`            | TEXT (JSON) | `[]`    | `["swe"]`, `["ee"]`, or `[]` for both                      |
| `keywords`               | TEXT (JSON) | `[]`    | Title/description substrings to require (AND with rules)   |
| `last_alerted_at`        | TIMESTAMP   | NULL    | Last time a DM alert batch was sent                        |
| `created_at`             | TIMESTAMP   | now     | Row creation time                                          |
| `updated_at`             | TIMESTAMP   | now     | Last update time                                           |

### `user_filter_rules`

Additive filter tuples per user. Each row defines one independent filter — a user is notified if **any** of their rules matches a job (OR logic). Rules combine a role type with a location scope.

| Column           | Type       | Description                                              |
| ---------------- | ---------- | -------------------------------------------------------- |
| `id`             | INTEGER PK | Auto-incrementing row ID                                 |
| `user_id`        | TEXT       | Discord snowflake — FK to `user_preferences`             |
| `role_type`      | TEXT       | `intern`, `new_grad`, or `entry_level`                   |
| `location_scope` | TEXT       | `us`, `remote`, `country:XX`, `state:XX`, or `city:Name` |
| `created_at`     | TIMESTAMP  | Row creation time                                        |

**Example:** a user who wants internships anywhere in the US _and_ entry-level roles only in Colorado would have two rows:

| role_type     | location_scope |
| ------------- | -------------- |
| `intern`      | `us`           |
| `entry_level` | `state:CO`     |

## Configuration Reference

| Variable                         | Required | Default   | Description                                |
| -------------------------------- | -------- | --------- | ------------------------------------------ |
| `DISCORD_TOKEN`                  | Yes      | —         | Bot token from Discord Developer Portal    |
| `DISCORD_CHANNEL_ID`             | Yes      | —         | Channel ID where jobs are posted           |
| `GREENHOUSE_SLUGS`               | No       | `[]`      | Comma-separated Greenhouse company slugs   |
| `LEVER_SLUGS`                    | No       | `[]`      | Comma-separated Lever company slugs        |
| `ASHBY_SLUGS`                    | No       | `[]`      | Comma-separated Ashby company slugs        |
| `POLL_INTERVAL_MINUTES`          | No       | `10`      | Scrape interval for Greenhouse/Lever/Ashby |
| `SIMPLIFY_POLL_INTERVAL_MINUTES` | No       | `30`      | Scrape interval for Simplify               |
| `DB_PATH`                        | No       | `jobs.db` | Path to SQLite database file               |
| `META_ENABLED`                   | No       | `false`   | Enable Meta scraper (not yet implemented)  |
| `META_POLL_INTERVAL_MINUTES`     | No       | `30`      | Meta poll interval                         |

## Local Testing

You don't need a Discord bot token to test scrapers. The dry-run CLI hits real APIs and prints results to stdout.

### Dry-run CLI

```bash
# Test a single scraper + slug — only shows jobs that pass filters
python -m bot.cli greenhouse stripe

# Show ALL jobs (skip filters) to see raw API output
python -m bot.cli greenhouse anthropic --all

# Simplify doesn't need a slug
python -m bot.cli simplify

# Other platforms
python -m bot.cli lever netflix
python -m bot.cli ashby ramp
```

This is useful for:

- Verifying a company slug works before adding it to `.env`
- Checking if your filters are too strict or too loose
- Debugging scraper parsing without touching Discord

### Unit Tests

```bash
uv sync --extra dev
uv run pytest
```

Tests cover filter logic (title include/exclude, US location matching) and scraper parsing with mocked HTTP responses. No network calls, no Discord token needed.

## Development

### Setup

```bash
uv sync --extra dev
```

This installs dev dependencies: `ruff` (linter), `pytest`, and `pytest-asyncio`.

### Linting

```bash
uv run ruff check .
uv run ruff format --check .
```

To auto-fix:

```bash
uv run ruff check --fix .
uv run ruff format .
```

### Project Structure

```
bot/
├── main.py           # Entrypoint — discord.py Client, on_ready triggers scraping
├── config.py         # pydantic-settings — reads .env, validates config
├── models.py         # Job dataclass shared by all scrapers
├── filters.py        # Title + location filtering logic
├── db.py             # SQLite layer — job_postings, user_preferences, user_filter_rules
├── notifier.py       # Sends discord.Embed messages to the channel
├── alerts.py         # DM alert wizard, per-user delivery, quiet hours
├── commands.py       # Slash commands — /query, /scout, /alert-*, /health
├── scheduler.py      # APScheduler wiring + poll functions
└── scrapers/
    ├── greenhouse.py # GET boards-api.greenhouse.io/v1/boards/{slug}/jobs
    ├── lever.py      # GET api.lever.co/v0/postings/{slug}
    ├── ashby.py      # POST jobs.ashbyhq.com/api/non-user-graphql (GraphQL)
    ├── simplify.py   # GET raw GitHub JSON (intern + new-grad repos)
    └── custom/       # Placeholder for Google, Meta, Amazon, etc.
```

### Adding a New Scraper

1. Create `bot/scrapers/yourplatform.py`
2. Implement an async `scrape()` function that returns `list[Job]`:

```python
from bot.models import Job

async def scrape(slug: str, client: httpx.AsyncClient) -> list[Job]:
    # Fetch from the API
    # Return a list of Job objects
    ...
```

3. Add a poll function in `bot/scheduler.py` following the existing pattern
4. Register it with the scheduler in `start_scheduler()`
5. Add any new config (slugs, intervals) to `bot/config.py` and `.env.example`

### Resetting the Database

To re-scrape all jobs (e.g., after changing filters):

```bash
rm jobs.db
python -m bot.main
```

The database is auto-created on startup.

## Deployment

The bot needs a persistent process (not serverless) since it maintains a Discord gateway connection and APScheduler runs in-memory.

**Railway / Render:**

1. Push to GitHub
2. Connect the repo to Railway or Render
3. Set environment variables in the dashboard
4. Set the start command to `python -m bot.main`

**VPS (Hetzner, etc.):**

```bash
# Using systemd or screen/tmux
python -m bot.main
```

Estimated cost: ~$5/month for a small persistent instance.

## Next Steps

### User experience

- [x] **Discord DMs to specific users** — `/alert` wizard collects role, discipline, location, interval, keyword, company, and quiet-hours preferences and delivers matching jobs via DM on a per-user schedule.
- [ ] **Per-user company subscriptions** — Let each user maintain their own follow list, with predefined sets (FAANG, top startups) and individual company picks.
- [ ] **Multi-dimensional filters** — Combinable filter tuples per user, e.g. `(fulltime,SWE,US)+(intern,SWE,colo)`, covering role type (SWE/EE/systems), job type (fulltime/intern), and location preference.
- [x] **`/query` command** — On-demand search against the jobs DB. Supports keyword, company, role (internship / new grad / all), discipline (SWE / EE), and US state filters. Returns up to 10 embeds per query.
- [x] **Multiple `/query` subfilters** — Allow users to do comma separation to their queries (e.g. a query on CO,WA will return Colorado and Washington)
- [x] **Start season filter** — Add a `season` filter to `/query` (fall, spring, summer, winter) that maps to expected start date ranges, so users can narrow results to roles beginning in a specific season.
- [ ] **Quiet hours** — Per-user notification time windows so the bot only DMs or pings during hours the user configures.

### Job data quality

- [ ] **Job expiry** — Edit or mark posted embeds when a listing goes dead (HTTP 404 or removed from the board).
- [x] **Central jobs database** — Full job records in `job_postings` (title, company, location, URL, source, posted date, discipline, is_intern, is_new_grad, is_remote) with a `job_locations` child table for multi-location postings. Replaces the old `seen_jobs` dedup table.
- [x] **Liveness verification** — Periodically re-check stored postings to confirm they're still active before surfacing them to new users.
- [x] **Company + platform search** — CLI or slash command that takes a company name and a platform (e.g. `greenhouse`, `lever`) and scrapes that specific combination on demand, bypassing the scheduler. Useful for spot-checking a company before adding it to `.env`.
- [x] **Description keyword extraction** — At ingestion time, strip common stop-words from the description using a large base vocabulary, then store the remaining domain-specific terms (e.g. `rust`, `kubernetes`, `verilog`, `react`) in a `job_keywords` table linked to `job_postings`. Enables keyword-based search and filtering without storing full description text.
- [x] **Keyword search across title and description** — The `/query` keyword filter currently matches only job titles. Extend it to also match against extracted description keywords (requires the description keyword extraction above). Scrapers that expose descriptions (Greenhouse, Lever) should populate keywords at ingestion; others fall back to title-only matching.

### Scrapers & sources

- [ ] **Custom scraper API contract** — Document the interface a custom scraper must implement so future contributors can add proprietary career pages consistently. Should cover: required return type (`list[Job]`), expected fields and nullability, how to handle pagination, where to register the scraper in the scheduler, and how to wire up a new config slug/toggle.
- [ ] **Custom scrapers** — Google, Meta, Amazon, Apple, Microsoft, Uber. These use proprietary career APIs (found via DevTools), not standard ATS platforms. Each needs its own scraper in `bot/scrapers/custom/`.
- [ ] **Workday scraper** — NVIDIA, Snap, and others use Workday, which requires session tokens. Low priority but high value if cracked.
- [ ] **Rate limit handling** — Add exponential backoff and retry logic for APIs that return 429s, especially Meta and any Cloudflare-protected sites.

### Infrastructure

- [ ] **Richer embeds** — Add posted date, team/department, salary range (when available), and a footer with the source platform.
- [x] **Health monitoring** — Add a `/health` endpoint or periodic heartbeat message so you know the bot is alive. Alert if a scraper has failed N times in a row.
- [x] **CI** — GitHub Actions workflow to run `ruff check` + `pytest` on PRs.
