from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import aiosqlite

from bot.config import settings
from bot.models import Job

_STRIP_HTML_RE = re.compile(r"<[^>]+>")
_COLLAPSE_WS_RE = re.compile(r"\s+")
_DESC_MAX_CHARS = 5000


def _strip_description(text: str) -> str:
    """Strip HTML tags, collapse whitespace, and truncate to storage limit."""
    text = _STRIP_HTML_RE.sub(" ", text)
    text = _COLLAPSE_WS_RE.sub(" ", text).strip()
    return text[:_DESC_MAX_CHARS]


_DB_PATH = settings.db_path

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
"""


async def _migrate_db(db: aiosqlite.Connection) -> None:
    """Apply schema migrations for columns added after initial creation."""
    migrations = [
        "ALTER TABLE job_postings ADD COLUMN description_text TEXT",
        "ALTER TABLE job_postings ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE job_postings ADD COLUMN last_checked_at TIMESTAMP",
    ]
    for sql in migrations:
        try:
            await db.execute(sql)
        except aiosqlite.OperationalError:
            pass  # column already exists
    await db.commit()


async def init_db() -> None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.executescript(SCHEMA)
        await _migrate_db(db)


# ---------------------------------------------------------------------------
# job_postings
# ---------------------------------------------------------------------------


async def is_seen(source: str, job_id: str) -> bool:
    """Return True if (source, job_id) already exists in job_postings."""
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM job_postings WHERE source = ? AND job_id = ?",
            (source, job_id),
        )
        return await cursor.fetchone() is not None


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
    async with aiosqlite.connect(_DB_PATH) as db:
        for j in jobs:
            locations = parse_locations_fn(j.location)
            is_remote = any(loc["is_remote"] for loc in locations)
            is_intern, is_new_grad = classify_fn(j)
            discipline = classify_discipline_fn(j)
            posted = (
                j.posted_at.isoformat()
                if isinstance(j.posted_at, datetime)
                else j.posted_at
            )

            desc_text = _strip_description(j.description) if j.description else None

            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO job_postings
                    (source, job_id, title, company, location_raw,
                     url, posted_at, is_intern, is_new_grad, is_remote, discipline,
                     description_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    j.source, j.id, j.title, j.company, j.location,
                    j.url, posted, int(is_intern), int(is_new_grad), int(is_remote), discipline,
                    desc_text,
                ),
            )

            if cursor.rowcount == 0:
                continue  # already existed — skip location insert

            posting_id = cursor.lastrowid
            for loc in locations:
                await db.execute(
                    """
                    INSERT INTO job_locations (posting_id, country, state, city, is_remote)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (posting_id, loc["country"], loc["state"], loc["city"], int(loc["is_remote"])),
                )

        await db.commit()


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
        kw_clause = " OR ".join(
            "(jp.title LIKE ? OR jp.description_text LIKE ?)" for _ in keywords
        )
        jp_conditions.append(f"({kw_clause})")
        params.extend(val for kw in keywords for val in (f"%{kw}%", f"%{kw}%"))

    if companies:
        placeholders = ",".join("?" * len(companies))
        jp_conditions.append(f"jp.company IN ({placeholders})")
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

    jp_conditions.append("jp.is_active = 1")

    if states:
        placeholders = ",".join("?" * len(states))
        jp_conditions.append(f"jl.state IN ({placeholders})")
        params.extend(s.upper() for s in states)

    where = ("WHERE " + " AND ".join(jp_conditions)) if jp_conditions else ""
    params.append(limit)
    params.append(offset)

    join = "LEFT JOIN job_locations jl ON jp.id = jl.posting_id" if states else ""

    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
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


# ---------------------------------------------------------------------------
# liveness verification
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
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, source, job_id, url
            FROM job_postings
            WHERE is_active = 1
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
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """
            UPDATE job_postings
            SET is_active = 0, last_checked_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (posting_id,),
        )
        await db.commit()


async def touch_liveness_check(posting_id: int) -> None:
    """Record that a posting was checked and is still active."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "UPDATE job_postings SET last_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
            (posting_id,),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# user_preferences
# ---------------------------------------------------------------------------


async def get_user_prefs(user_id: str) -> dict | None:
    """Return the user's preferences as a plain dict, or None if not set."""
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        data = dict(row)
        data["companies"] = json.loads(data["companies"])
        return data


async def upsert_user_prefs(user_id: str, **kwargs: Any) -> None:
    """Create or partially update a user's delivery preferences.

    Pass only the columns you want to change. The `companies` column accepts
    a Python list and is serialized to JSON automatically.

    Example:
        await upsert_user_prefs("123", dm_enabled=0, companies=["stripe", "ramp"])
    """
    if "companies" in kwargs:
        kwargs["companies"] = json.dumps(kwargs["companies"])

    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_preferences (user_id) VALUES (?)",
            (user_id,),
        )
        if kwargs:
            set_clause = ", ".join(f"{col} = ?" for col in kwargs)
            set_clause += ", updated_at = CURRENT_TIMESTAMP"
            await db.execute(
                f"UPDATE user_preferences SET {set_clause} WHERE user_id = ?",  # noqa: S608
                (*kwargs.values(), user_id),
            )
        await db.commit()


# ---------------------------------------------------------------------------
# user_filter_rules
# ---------------------------------------------------------------------------


async def get_user_filter_rules(user_id: str) -> list[dict]:
    """Return all filter rules for a user as a list of dicts."""
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
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
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO user_filter_rules (user_id, role_type, location_scope)
            VALUES (?, ?, ?)
            """,
            (user_id, role_type, location_scope),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def remove_user_filter_rule(rule_id: int, user_id: str) -> bool:
    """Delete a filter rule by id. user_id is required to prevent cross-user deletion.

    Returns True if a row was deleted, False if not found.
    """
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM user_filter_rules WHERE id = ? AND user_id = ?",
            (rule_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0
