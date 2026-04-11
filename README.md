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

# Comma-separated company slugs for each platform
GREENHOUSE_SLUGS=stripe,anthropic,airbnb,cloudflare,figma,notion
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
Scrapers → Filter → Dedup → Notify
```

1. **Scrapers** fetch job listings from each platform's API
2. **Filters** keep only entry-level/intern SWE roles in the US
3. **Dedup** checks the SQLite database to skip already-seen jobs
4. **Notifier** sends new jobs to the Discord channel as embedded messages

### Filtering

Jobs must pass all three checks:

- **Title must match** one of: `intern`, `internship`, `new grad`, `university grad`, `entry level`, `swe i`, `software engineer i`, `l3`
- **Title must NOT match** any of: `senior`, `staff`, `principal`, `manager`, `lead`, `sr.`
- **Location must be US** — checks for state names, state abbreviations (e.g., `CA`, `NY`), major city names, or keywords like `united states`, `usa`, `remote`

### Scheduling

| Source | Interval | Notes |
|--------|----------|-------|
| Greenhouse | 10 min | Configurable via `POLL_INTERVAL_MINUTES` |
| Lever | 10 min | Staggered start |
| Ashby | 10 min | Staggered start |
| Simplify | 30 min | Configurable via `SIMPLIFY_POLL_INTERVAL_MINUTES` |

Scrapers are staggered so they don't all fire at the same instant. Each individual slug request includes a 1-second delay to be polite to APIs.

### Discord Output

Each new job appears as an embed with:
- Job title and company name
- Location
- Direct link to the application page

When many jobs are found in a single cycle, they're batched into messages of up to 10 embeds each.

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_TOKEN` | Yes | — | Bot token from Discord Developer Portal |
| `DISCORD_CHANNEL_ID` | Yes | — | Channel ID where jobs are posted |
| `GREENHOUSE_SLUGS` | No | `[]` | Comma-separated Greenhouse company slugs |
| `LEVER_SLUGS` | No | `[]` | Comma-separated Lever company slugs |
| `ASHBY_SLUGS` | No | `[]` | Comma-separated Ashby company slugs |
| `POLL_INTERVAL_MINUTES` | No | `10` | Scrape interval for Greenhouse/Lever/Ashby |
| `SIMPLIFY_POLL_INTERVAL_MINUTES` | No | `30` | Scrape interval for Simplify |
| `DB_PATH` | No | `jobs.db` | Path to SQLite database file |
| `META_ENABLED` | No | `false` | Enable Meta scraper (not yet implemented) |
| `META_POLL_INTERVAL_MINUTES` | No | `30` | Meta poll interval |

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
├── db.py             # SQLite dedup layer (seen_jobs table)
├── notifier.py       # Sends discord.Embed messages to the channel
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
- [ ] **Per-user company subscriptions** — Let each user maintain their own follow list, with predefined sets (FAANG, top startups) and individual company picks.
- [ ] **Multi-dimensional filters** — Combinable filter tuples per user, e.g. `(fulltime,SWE,US)+(intern,SWE,colo)`, covering role type (SWE/EE/systems), job type (fulltime/intern), and location preference.
- [ ] **`/query` command** — On-demand search against the cached jobs DB so users can pull results without waiting for the next poll cycle.
- [ ] **Quiet hours** — Per-user notification time windows so the bot only DMs or pings during hours the user configures.

### Job data quality
- [ ] **Job expiry** — Edit or mark posted embeds when a listing goes dead (HTTP 404 or removed from the board).
- [ ] **DB persistence for all scraped jobs** — Store full job records (not just seen IDs) so `/query` can return historical results without re-scraping.
- [ ] **Liveness verification** — Periodically re-check stored postings to confirm they're still active before surfacing them to new users.

### Scrapers & sources
- [ ] **Custom scrapers** — Google, Meta, Amazon, Apple, Microsoft, Uber. These use proprietary career APIs (found via DevTools), not standard ATS platforms. Each needs its own scraper in `bot/scrapers/custom/`.
- [ ] **Workday scraper** — NVIDIA, Snap, and others use Workday, which requires session tokens. Low priority but high value if cracked.
- [ ] **Rate limit handling** — Add exponential backoff and retry logic for APIs that return 429s, especially Meta and any Cloudflare-protected sites.

### Infrastructure
- [ ] **Richer embeds** — Add posted date, team/department, salary range (when available), and a footer with the source platform.
- [ ] **Health monitoring** — Add a `/health` endpoint or periodic heartbeat message so you know the bot is alive. Alert if a scraper has failed N times in a row.
- [ ] **CI** — GitHub Actions workflow to run `ruff check` + `pytest` on PRs.
