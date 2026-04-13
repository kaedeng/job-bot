from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from bot.config import settings
from bot.filters import strip_html
from bot.keywords import extract_keywords
from bot.models import Job

_DESC_MAX_CHARS = 5000


_DB_PATH = settings.db_path

# ---------------------------------------------------------------------------
# shared connection
# ---------------------------------------------------------------------------

_conn: aiosqlite.Connection | None = None


async def get_conn() -> aiosqlite.Connection:
    """Return the shared DB connection, creating it on first call."""
    global _conn
    if _conn is None:
        Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = await aiosqlite.connect(_DB_PATH)
        _conn.row_factory = aiosqlite.Row
        await _conn.execute("PRAGMA journal_mode=WAL")
        await _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


async def close() -> None:
    """Close the shared connection (call on shutdown)."""
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS job_postings (
    id               INTEGER   PRIMARY KEY AUTOINCREMENT,
    source           TEXT      NOT NULL,
    job_id           TEXT      NOT NULL,
    title            TEXT      NOT NULL,
    company          TEXT      NOT NULL,
    location_raw     TEXT      NOT NULL,
    url              TEXT      NOT NULL,
    posted_at        TIMESTAMP,
    ingested_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_intern        INTEGER,                        -- 1/0/NULL (NULL = unclassified)
    is_new_grad      INTEGER,                        -- 1/0/NULL
    is_remote        INTEGER   NOT NULL DEFAULT 0,   -- 1 if any location segment is remote
    discipline       TEXT      NOT NULL DEFAULT 'unknown',  -- "swe" | "ee" | "unknown"
    description_text TEXT,                           -- HTML-stripped description, max 5000 chars
    is_active        INTEGER   NOT NULL DEFAULT 1,   -- 0 once a liveness check returns 404
    last_checked_at  TIMESTAMP,                      -- last liveness probe timestamp
    missing_count    INTEGER   NOT NULL DEFAULT 0,   -- consecutive scrape-diff misses
    UNIQUE (source, job_id)
);

CREATE TABLE IF NOT EXISTS job_locations (
    id          INTEGER   PRIMARY KEY AUTOINCREMENT,
    posting_id  INTEGER   NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    country     TEXT,
    state       TEXT,
    city        TEXT,
    is_remote   INTEGER   NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id                TEXT      PRIMARY KEY,
    dm_enabled             INTEGER   NOT NULL DEFAULT 1,
    alert_interval_minutes INTEGER   NOT NULL DEFAULT 60,
    quiet_hours_start      TEXT,
    quiet_hours_end        TEXT,
    companies              TEXT      NOT NULL DEFAULT '[]',
    disciplines            TEXT      NOT NULL DEFAULT '[]',  -- JSON: ["swe","ee"] or [] for all
    keywords               TEXT      NOT NULL DEFAULT '[]',  -- JSON: title/desc keyword substrings
    last_alerted_at        TIMESTAMP,                        -- last time DM alerts were sent
    created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_filter_rules (
    id             INTEGER   PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT      NOT NULL REFERENCES user_preferences(user_id) ON DELETE CASCADE,
    role_type      TEXT      NOT NULL,
    location_scope TEXT      NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS keyword_stats (
    keyword      TEXT      PRIMARY KEY,
    use_count    INTEGER   NOT NULL DEFAULT 1,
    last_used_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_job_postings_active_ingested ON job_postings(is_active, ingested_at);
CREATE INDEX IF NOT EXISTS idx_job_postings_last_checked    ON job_postings(last_checked_at);
CREATE INDEX IF NOT EXISTS idx_job_locations_posting_id     ON job_locations(posting_id);
CREATE INDEX IF NOT EXISTS idx_job_locations_country        ON job_locations(country);
CREATE INDEX IF NOT EXISTS idx_job_locations_state          ON job_locations(state);
CREATE INDEX IF NOT EXISTS idx_user_filter_rules_user_id    ON user_filter_rules(user_id);
"""


async def _migrate_db(db: aiosqlite.Connection) -> None:
    """Apply schema migrations for columns added after initial creation."""
    migrations = [
        "ALTER TABLE job_postings ADD COLUMN description_text TEXT",
        "ALTER TABLE job_postings ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE job_postings ADD COLUMN last_checked_at TIMESTAMP",
        "ALTER TABLE job_postings ADD COLUMN missing_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE user_preferences ADD COLUMN disciplines TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE user_preferences ADD COLUMN keywords TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE user_preferences ADD COLUMN last_alerted_at TIMESTAMP",
    ]
    for sql in migrations:
        try:
            await db.execute(sql)
        except aiosqlite.OperationalError:
            pass  # column already exists
    await db.commit()


async def backfill_keyword_stats() -> int:
    """Populate keyword_stats from all existing job_postings rows.

    Iterates every posting's title + description_text, extracts keywords, and
    upserts them into keyword_stats. Safe to call multiple times — use_count
    accumulates rather than resets. Returns the number of postings processed.
    """
    import logging

    log = logging.getLogger(__name__)
    conn = await get_conn()
    cursor = await conn.execute("SELECT title, description_text FROM job_postings")
    rows = await cursor.fetchall()
    if not rows:
        return 0

    log.info("backfill_keyword_stats: processing %d postings", len(rows))
    for row in rows:
        kws = extract_keywords(row[0], row[1])
        if kws:
            await increment_keyword_stats(kws)

    log.info("backfill_keyword_stats: done")
    return len(rows)


async def init_db() -> None:
    conn = await get_conn()
    await conn.executescript(SCHEMA)
    await _migrate_db(conn)

    # One-time backfill: if keyword_stats is empty but job_postings has rows,
    # populate from existing data so autocomplete works immediately.
    cursor = await conn.execute("SELECT COUNT(*) FROM keyword_stats")
    count = (await cursor.fetchone())[0]
    if count == 0:
        await backfill_keyword_stats()


# ---------------------------------------------------------------------------
# job_postings
# ---------------------------------------------------------------------------


async def is_seen(source: str, job_id: str) -> bool:
    """Return True if (source, job_id) already exists in job_postings."""
    conn = await get_conn()
    cursor = await conn.execute(
        "SELECT 1 FROM job_postings WHERE source = ? AND job_id = ?",
        (source, job_id),
    )
    return await cursor.fetchone() is not None


async def get_seen_ids_for_source(source: str) -> frozenset[str]:
    """Return all known job_ids for a given source as a frozenset."""
    conn = await get_conn()
    cursor = await conn.execute(
        "SELECT job_id FROM job_postings WHERE source = ?",
        (source,),
    )
    return frozenset(row[0] for row in await cursor.fetchall())


async def filter_unseen(jobs: list[Job]) -> list[Job]:
    """Return only the jobs whose (source, job_id) pairs are not yet in the DB.

    Uses a single batch query instead of N individual lookups.
    """
    if not jobs:
        return []

    conn = await get_conn()
    # Build a temp-value list for batch lookup
    pairs = [(j.source, j.id) for j in jobs]
    placeholders = ",".join(["(?, ?)"] * len(pairs))
    flat_params = [v for pair in pairs for v in pair]

    cursor = await conn.execute(
        "SELECT source, job_id FROM job_postings"  # noqa: S608
        f" WHERE (source, job_id) IN (VALUES {placeholders})",
        flat_params,
    )
    seen = {(row[0], row[1]) for row in await cursor.fetchall()}
    return [j for j in jobs if (j.source, j.id) not in seen]


async def store_jobs_batch(
    jobs: list[Job],
    parse_locations_fn: Any,
    classify_fn: Any,
    classify_discipline_fn: Any,
) -> None:
    """Insert new tech-relevant jobs into job_postings + job_locations.

    Already-seen jobs (matched on UNIQUE source+job_id) are silently skipped.

    Args:
        jobs: Jobs to store. Caller is responsible for pre-filtering to tech-relevant roles.
        parse_locations_fn: Callable[[str], list[dict]] -- returns a list of location dicts
            (country, state, city, is_remote) parsed from the raw location string.
        classify_fn: Callable[[Job], tuple[bool, bool]] --
            returns (is_intern, is_new_grad) for each job.
        classify_discipline_fn: Callable[[Job], str] --
            returns "swe", "ee", or "unknown" for each job.
    """
    conn = await get_conn()
    for j in jobs:
        locations = parse_locations_fn(j.location)
        is_remote = any(loc["is_remote"] for loc in locations)
        is_intern, is_new_grad = classify_fn(j)
        discipline = classify_discipline_fn(j)
        posted = j.posted_at.isoformat() if isinstance(j.posted_at, datetime) else j.posted_at

        desc_text = strip_html(j.description)[:_DESC_MAX_CHARS] if j.description else None

        cursor = await conn.execute(
            """
            INSERT OR IGNORE INTO job_postings
                (source, job_id, title, company, location_raw,
                 url, posted_at, is_intern, is_new_grad, is_remote, discipline,
                 description_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                j.source,
                j.id,
                j.title,
                j.company,
                j.location,
                j.url,
                posted,
                int(is_intern),
                int(is_new_grad),
                int(is_remote),
                discipline,
                desc_text,
            ),
        )

        if cursor.rowcount == 0:
            continue  # already existed — skip location insert and keyword extraction

        posting_id = cursor.lastrowid
        for loc in locations:
            await conn.execute(
                """
                INSERT INTO job_locations (posting_id, country, state, city, is_remote)
                VALUES (?, ?, ?, ?, ?)
                """,
                (posting_id, loc["country"], loc["state"], loc["city"], int(loc["is_remote"])),
            )

        # Extract and count tech keywords from the new job's title + description
        for kw in extract_keywords(j.title, desc_text):
            await conn.execute(
                """
                INSERT INTO keyword_stats (keyword, use_count, last_used_at)
                VALUES (?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(keyword) DO UPDATE SET
                    use_count    = use_count + 1,
                    last_used_at = CURRENT_TIMESTAMP
                """,
                (kw,),
            )

    await conn.commit()


# ---------------------------------------------------------------------------
# queries
# ---------------------------------------------------------------------------


async def query_jobs(
    *,
    keyword: str | None = None,
    company: str | list[str] | None = None,
    role: str | None = None,
    discipline: str | None = None,
    state: str | list[str] | None = None,
    season: str | None = None,
    remote_only: bool = False,
    ingested_after: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[dict]:
    """Query job_postings with optional filters. Returns most-recently ingested first.

    Args:
        keyword: One or more title substrings (comma-string or list). OR logic.
        company: One or more company slugs (comma-string or list). OR logic across values.
        role: One or more of "intern", "new_grad", "all" (comma-string or list).
              OR logic; "all" disables the level filter entirely. None = intern + new_grad.
        discipline: One or more of "swe", "ee" (comma-string or list). OR logic.
        state: One or more US state abbreviations (comma-string or list). OR logic.
        season: "summer", "fall", "spring", or "winter" — matched against job title.
        remote_only: If True, only return jobs with is_remote = 1.
        limit: Max rows to return (capped at 25 to stay under Discord embed limit).
    """
    limit = min(limit, 25)

    jp_conditions: list[str] = []
    params: list[object] = []

    # Normalize multi-value inputs: accept "CO,WA" or ["CO", "WA"]
    def _to_list(val: str | list[str] | None) -> list[str]:
        if val is None:
            return []
        if isinstance(val, str):
            return [v.strip() for v in val.split(",") if v.strip()]
        return [v.strip() for v in val if v.strip()]

    keywords = _to_list(keyword)
    companies = _to_list(company)
    roles = _to_list(role)
    disciplines = _to_list(discipline)
    states = _to_list(state)

    if keywords:
        kw_clause = " OR ".join("(jp.title LIKE ? OR jp.description_text LIKE ?)" for _ in keywords)
        jp_conditions.append(f"({kw_clause})")
        params.extend(val for kw in keywords for val in (f"%{kw}%", f"%{kw}%"))

    if companies:
        placeholders = ",".join("?" * len(companies))
        jp_conditions.append(f"LOWER(jp.company) IN ({placeholders})")
        params.extend(c.lower() for c in companies)

    if "all" in roles:
        pass  # no role condition
    elif roles:
        role_parts: list[str] = []
        for r in roles:
            if r == "intern":
                role_parts.append("jp.is_intern = 1")
            elif r == "new_grad":
                role_parts.append("jp.is_new_grad = 1")
        if role_parts:
            jp_conditions.append(f"({' OR '.join(role_parts)})")
    else:
        # Default: intern or new_grad only (exclude senior/unclassified)
        jp_conditions.append("(jp.is_intern = 1 OR jp.is_new_grad = 1)")

    if disciplines:
        placeholders = ",".join("?" * len(disciplines))
        jp_conditions.append(f"jp.discipline IN ({placeholders})")
        params.extend(d.lower() for d in disciplines)

    if season:
        jp_conditions.append("jp.title LIKE ?")
        params.append(f"%{season}%")

    if remote_only:
        jp_conditions.append("jp.is_remote = 1")

    if ingested_after:
        jp_conditions.append("COALESCE(jp.posted_at, jp.ingested_at) > ?")
        params.append(ingested_after)

    jp_conditions.append("jp.is_active = 1")

    if states:
        placeholders = ",".join("?" * len(states))
        jp_conditions.append(f"jl.state IN ({placeholders})")
        params.extend(s.upper() for s in states)

    where = ("WHERE " + " AND ".join(jp_conditions)) if jp_conditions else ""
    params.append(limit)
    params.append(offset)

    join = "LEFT JOIN job_locations jl ON jp.id = jl.posting_id" if states else ""

    conn = await get_conn()
    cursor = await conn.execute(
        f"""
        SELECT DISTINCT jp.*
        FROM job_postings jp
        {join}
        {where}
        ORDER BY jp.ingested_at DESC
        LIMIT ? OFFSET ?
        """,  # noqa: S608
        params,
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_companies_for_query(
    *,
    keyword: str | None = None,
    role: str | None = None,
    discipline: str | None = None,
    state: str | list[str] | None = None,
    season: str | None = None,
    remote_only: bool = False,
    ingested_after: str | None = None,
    limit: int = 25,
) -> list[str]:
    """Return distinct companies (ranked by job count) that match the given filters.

    Mirrors query_jobs parameter semantics but excludes the company filter so the
    dropdown always reflects what's available given the *other* active filters.
    """

    def _to_list(val: str | list[str] | None) -> list[str]:
        if val is None:
            return []
        if isinstance(val, str):
            return [v.strip() for v in val.split(",") if v.strip()]
        return [v.strip() for v in val if v.strip()]

    keywords = _to_list(keyword)
    roles = _to_list(role)
    disciplines = _to_list(discipline)
    states = _to_list(state)

    conditions: list[str] = ["jp.is_active = 1"]
    params: list[object] = []

    if keywords:
        kw_clause = " OR ".join(
            "(jp.title LIKE ? OR jp.description_text LIKE ?)" for _ in keywords
        )
        conditions.append(f"({kw_clause})")
        params.extend(v for kw in keywords for v in (f"%{kw}%", f"%{kw}%"))

    if "all" in roles:
        pass
    elif roles:
        role_parts = []
        for r in roles:
            if r == "intern":
                role_parts.append("jp.is_intern = 1")
            elif r == "new_grad":
                role_parts.append("jp.is_new_grad = 1")
        if role_parts:
            conditions.append(f"({' OR '.join(role_parts)})")
    else:
        conditions.append("(jp.is_intern = 1 OR jp.is_new_grad = 1)")

    if disciplines:
        placeholders = ",".join("?" * len(disciplines))
        conditions.append(f"jp.discipline IN ({placeholders})")
        params.extend(d.lower() for d in disciplines)

    if season:
        conditions.append("jp.title LIKE ?")
        params.append(f"%{season}%")

    if remote_only:
        conditions.append("jp.is_remote = 1")

    if ingested_after:
        conditions.append("COALESCE(jp.posted_at, jp.ingested_at) > ?")
        params.append(ingested_after)

    join = ""
    if states:
        placeholders = ",".join("?" * len(states))
        conditions.append(f"jl.state IN ({placeholders})")
        params.extend(s.upper() for s in states)
        join = "LEFT JOIN job_locations jl ON jp.id = jl.posting_id"

    where = "WHERE " + " AND ".join(conditions)
    params.append(limit)

    conn = await get_conn()
    cursor = await conn.execute(
        f"""
        SELECT jp.company
        FROM job_postings jp
        {join}
        {where}
        GROUP BY LOWER(jp.company)
        ORDER BY COUNT(*) DESC
        LIMIT ?
        """,  # noqa: S608
        params,
    )
    rows = await cursor.fetchall()
    return [r["company"] for r in rows]


async def search_companies(prefix: str, limit: int = 25) -> list[str]:
    """Return company names that start with *prefix* (case-insensitive), ranked by job count."""
    conn = await get_conn()
    cursor = await conn.execute(
        """
        SELECT company
        FROM job_postings
        WHERE is_active = 1 AND LOWER(company) LIKE ?
        GROUP BY LOWER(company)
        ORDER BY COUNT(*) DESC
        LIMIT ?
        """,
        (f"{prefix.lower()}%", limit),
    )
    rows = await cursor.fetchall()
    return [r["company"] for r in rows]


async def search_keywords(prefix: str, limit: int = 25) -> list[str]:
    """Return keywords from keyword_stats matching *prefix*, ranked by use count."""
    conn = await get_conn()
    cursor = await conn.execute(
        """
        SELECT keyword FROM keyword_stats
        WHERE keyword LIKE ?
        ORDER BY use_count DESC, keyword ASC
        LIMIT ?
        """,
        (f"{prefix.lower()}%", limit),
    )
    rows = await cursor.fetchall()
    return [r["keyword"] for r in rows]


async def increment_keyword_stats(keywords: list[str]) -> None:
    """Upsert keyword usage counts — called whenever keywords are used in a query or alert."""
    if not keywords:
        return
    conn = await get_conn()
    for kw in keywords:
        await conn.execute(
            """
            INSERT INTO keyword_stats (keyword, use_count, last_used_at)
            VALUES (?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(keyword) DO UPDATE SET
                use_count    = use_count + 1,
                last_used_at = CURRENT_TIMESTAMP
            """,
            (kw.lower(),),
        )
    await conn.commit()


async def get_distinct_companies(limit: int = 25) -> list[str]:
    """Return up to *limit* active company display names, ranked by job count."""
    conn = await get_conn()
    cursor = await conn.execute(
        """
        SELECT company
        FROM job_postings
        WHERE is_active = 1
        GROUP BY LOWER(company)
        ORDER BY COUNT(*) DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await cursor.fetchall()
    return [r["company"] for r in rows]


# ---------------------------------------------------------------------------
# scrape-diff liveness
# ---------------------------------------------------------------------------

_MISSING_THRESHOLD = 2  # consecutive misses before a job is marked inactive


async def get_active_job_ids_for_company(source: str, company: str) -> set[str]:
    """Return job_ids for all active postings from a given source + company slug."""
    conn = await get_conn()
    cursor = await conn.execute(
        "SELECT job_id FROM job_postings WHERE source = ? AND company = ? AND is_active = 1",
        (source, company),
    )
    return {row[0] for row in await cursor.fetchall()}


async def reconcile_missing_jobs(
    source: str,
    company: str,
    seen_ids: set[str],
) -> int:
    """Compare *seen_ids* (from a fresh scrape) against active DB rows for this slug.

    - Jobs present in the scrape: reset missing_count to 0.
    - Jobs absent from the scrape: increment missing_count; if >= threshold, mark inactive.

    Returns the number of jobs newly marked inactive.
    """
    conn = await get_conn()

    # Reset count for jobs that came back
    if seen_ids:
        placeholders = ",".join(["?"] * len(seen_ids))
        await conn.execute(
            f"UPDATE job_postings SET missing_count = 0"  # noqa: S608
            f" WHERE source = ? AND company = ? AND is_active = 1"
            f" AND job_id IN ({placeholders})",
            (source, company, *seen_ids),
        )

    # Increment count for jobs not in the scrape
    if seen_ids:
        placeholders = ",".join(["?"] * len(seen_ids))
        absent_clause = f"AND job_id NOT IN ({placeholders})"
        absent_params: tuple = (source, company, *seen_ids)
    else:
        absent_clause = ""
        absent_params = (source, company)

    await conn.execute(
        f"UPDATE job_postings SET missing_count = missing_count + 1"  # noqa: S608
        f" WHERE source = ? AND company = ? AND is_active = 1 {absent_clause}",
        absent_params,
    )

    # Mark inactive those that have hit the threshold
    cursor = await conn.execute(
        """
        UPDATE job_postings
        SET is_active = 0, last_checked_at = CURRENT_TIMESTAMP
        WHERE source = ? AND company = ? AND is_active = 1
          AND missing_count >= ?
        RETURNING id, job_id, title
        """,
        (source, company, _MISSING_THRESHOLD),
    )
    deactivated = await cursor.fetchall()
    await conn.commit()
    return len(deactivated)


# ---------------------------------------------------------------------------
# liveness verification (URL probe — used for Simplify / Workday)
# ---------------------------------------------------------------------------


async def get_postings_due_for_liveness_check(
    min_age_hours: int = 1,
    recheck_interval_hours: int = 24,
    batch_size: int = 100,
) -> list[dict]:
    """Return active postings that need a liveness probe.

    Selects jobs that are:
    - is_active = 1
    - ingested at least min_age_hours ago (avoid probing brand-new listings)
    - never checked OR last_checked_at is older than recheck_interval_hours
    """
    conn = await get_conn()
    # Only probe sources that don't use scrape-diff (Simplify + Workday).
    # Greenhouse / Lever / Ashby are covered by reconcile_missing_jobs() instead.
    cursor = await conn.execute(
        """
        SELECT id, source, job_id, url
        FROM job_postings
        WHERE is_active = 1
          AND source IN ('simplify-intern', 'simplify-newgrad', 'workday')
          AND ingested_at <= datetime('now', ? || ' hours')
          AND (
                last_checked_at IS NULL
                OR last_checked_at <= datetime('now', ? || ' hours')
          )
        ORDER BY last_checked_at ASC NULLS FIRST
        LIMIT ?
        """,
        (f"-{min_age_hours}", f"-{recheck_interval_hours}", batch_size),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def mark_job_inactive(posting_id: int) -> None:
    """Mark a posting as expired (is_active = 0) and update last_checked_at."""
    conn = await get_conn()
    await conn.execute(
        """
        UPDATE job_postings
        SET is_active = 0, last_checked_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (posting_id,),
    )
    await conn.commit()


async def touch_liveness_check(posting_id: int) -> None:
    """Record that a posting was checked and is still active."""
    conn = await get_conn()
    await conn.execute(
        "UPDATE job_postings SET last_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
        (posting_id,),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# user_preferences
# ---------------------------------------------------------------------------


def _parse_pref_row(row: aiosqlite.Row) -> dict:
    """Convert a user_preferences row to a dict with JSON fields decoded."""
    data = dict(row)
    data["companies"] = json.loads(data["companies"])
    data["disciplines"] = json.loads(data.get("disciplines") or "[]")
    data["keywords"] = json.loads(data.get("keywords") or "[]")
    return data


async def get_user_prefs(user_id: str) -> dict | None:
    """Return the user's preferences as a plain dict, or None if not set."""
    conn = await get_conn()
    cursor = await conn.execute(
        "SELECT * FROM user_preferences WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _parse_pref_row(row)


async def upsert_user_prefs(user_id: str, **kwargs: Any) -> None:
    """Create or partially update a user's delivery preferences.

    Pass only the columns you want to change. The `companies` column accepts
    a Python list and is serialized to JSON automatically.

    Example:
        await upsert_user_prefs("123", dm_enabled=0, companies=["stripe", "ramp"])
    """
    for col in ("companies", "disciplines", "keywords"):
        if col in kwargs and not isinstance(kwargs[col], str):
            kwargs[col] = json.dumps(kwargs[col])

    conn = await get_conn()
    await conn.execute(
        "INSERT OR IGNORE INTO user_preferences (user_id) VALUES (?)",
        (user_id,),
    )
    if kwargs:
        set_clause = ", ".join(f"{col} = ?" for col in kwargs)
        set_clause += ", updated_at = CURRENT_TIMESTAMP"
        await conn.execute(
            f"UPDATE user_preferences SET {set_clause} WHERE user_id = ?",  # noqa: S608
            (*kwargs.values(), user_id),
        )
    await conn.commit()


# ---------------------------------------------------------------------------
# user_filter_rules
# ---------------------------------------------------------------------------


async def get_user_filter_rules(user_id: str) -> list[dict]:
    """Return all filter rules for a user as a list of dicts."""
    conn = await get_conn()
    cursor = await conn.execute(
        "SELECT * FROM user_filter_rules WHERE user_id = ? ORDER BY id",
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def add_user_filter_rule(user_id: str, role_type: str, location_scope: str) -> int:
    """Add a filter rule for a user. Creates the user_preferences row if missing.

    Returns the new rule's id.
    """
    await upsert_user_prefs(user_id)  # ensure parent row exists
    conn = await get_conn()
    cursor = await conn.execute(
        """
        INSERT INTO user_filter_rules (user_id, role_type, location_scope)
        VALUES (?, ?, ?)
        """,
        (user_id, role_type, location_scope),
    )
    await conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


async def remove_user_filter_rule(rule_id: int, user_id: str) -> bool:
    """Delete a filter rule by id. user_id is required to prevent cross-user deletion.

    Returns True if a row was deleted, False if not found.
    """
    conn = await get_conn()
    cursor = await conn.execute(
        "DELETE FROM user_filter_rules WHERE id = ? AND user_id = ?",
        (rule_id, user_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def clear_user_filter_rules(user_id: str) -> None:
    """Delete all filter rules for a user (used before replacing with a fresh set)."""
    conn = await get_conn()
    await conn.execute(
        "DELETE FROM user_filter_rules WHERE user_id = ?",
        (user_id,),
    )
    await conn.commit()


async def get_users_due_for_alert() -> list[dict]:
    """Return users with dm_enabled=1 whose next alert window has passed."""
    conn = await get_conn()
    cursor = await conn.execute(
        """
        SELECT * FROM user_preferences
        WHERE dm_enabled = 1
          AND (
            last_alerted_at IS NULL
            OR datetime(last_alerted_at, '+' || alert_interval_minutes || ' minutes')
               <= datetime('now')
          )
        """
    )
    rows = await cursor.fetchall()
    return [_parse_pref_row(row) for row in rows]


async def update_last_alerted(user_id: str) -> None:
    """Stamp the current time as the last alert sent time for a user."""
    conn = await get_conn()
    await conn.execute(
        "UPDATE user_preferences SET last_alerted_at = CURRENT_TIMESTAMP WHERE user_id = ?",
        (user_id,),
    )
    await conn.commit()


async def query_jobs_for_user(
    user_id: str,
    ingested_after: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> list[dict]:
    """Return jobs matching a user's filter rules, most-recently ingested first.

    Combines all of the user's filter rules with OR logic:
    a job matches if it satisfies at least one (role_type + location_scope) pair.
    Discipline preference (stored in user_preferences.disciplines) is applied
    as a global AND filter across all rules.
    """
    rules = await get_user_filter_rules(user_id)
    prefs = await get_user_prefs(user_id)
    if not rules or not prefs:
        return []

    disciplines: list[str] = prefs.get("disciplines") or []
    keywords: list[str] = prefs.get("keywords") or []
    companies: list[str] = prefs.get("companies") or []

    conditions: list[str] = ["jp.is_active = 1"]
    params: list[object] = []

    if ingested_after:
        conditions.append("jp.ingested_at > ?")
        params.append(ingested_after)

    if disciplines:
        placeholders = ",".join("?" * len(disciplines))
        conditions.append(f"jp.discipline IN ({placeholders})")
        params.extend(disciplines)

    if keywords:
        kw_clause = " OR ".join("(jp.title LIKE ? OR jp.description_text LIKE ?)" for _ in keywords)
        conditions.append(f"({kw_clause})")
        params.extend(v for kw in keywords for v in (f"%{kw}%", f"%{kw}%"))

    if companies:
        placeholders = ",".join("?" * len(companies))
        conditions.append(f"LOWER(jp.company) IN ({placeholders})")
        params.extend(c.lower() for c in companies)

    # Build per-rule clauses — each rule is (role AND location), rules are OR'd
    rule_parts: list[str] = []
    rule_params: list[object] = []

    for rule in rules:
        role_type = rule["role_type"]
        loc_scope = rule["location_scope"]

        role_cond = "jp.is_intern = 1" if role_type == "intern" else "jp.is_new_grad = 1"

        if loc_scope == "us":
            loc_cond = (
                "EXISTS (SELECT 1 FROM job_locations jl "
                "WHERE jl.posting_id = jp.id AND jl.country = 'US')"
            )
        elif loc_scope == "remote":
            loc_cond = "jp.is_remote = 1"
        elif loc_scope.startswith("state:"):
            state = loc_scope.split(":", 1)[1].upper()
            loc_cond = (
                "EXISTS (SELECT 1 FROM job_locations jl "
                "WHERE jl.posting_id = jp.id AND jl.state = ?)"
            )
            rule_params.append(state)
        elif loc_scope.startswith("country:"):
            country = loc_scope.split(":", 1)[1].upper()
            loc_cond = (
                "EXISTS (SELECT 1 FROM job_locations jl "
                "WHERE jl.posting_id = jp.id AND jl.country = ?)"
            )
            rule_params.append(country)
        else:
            loc_cond = "1=1"

        rule_parts.append(f"({role_cond} AND {loc_cond})")

    if rule_parts:
        conditions.append(f"({' OR '.join(rule_parts)})")
        params.extend(rule_params)

    where = "WHERE " + " AND ".join(conditions)
    params.append(limit)
    params.append(offset)

    conn = await get_conn()
    cursor = await conn.execute(
        f"""
        SELECT DISTINCT jp.*
        FROM job_postings jp
        {where}
        ORDER BY jp.ingested_at DESC
        LIMIT ? OFFSET ?
        """,  # noqa: S608
        params,
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
