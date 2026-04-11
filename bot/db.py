from __future__ import annotations

import aiosqlite

from bot.config import settings

_DB_PATH = settings.db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_jobs (
    source TEXT NOT NULL,
    job_id  TEXT NOT NULL,
    seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source, job_id)
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.executescript(SCHEMA)


async def is_seen(source: str, job_id: str) -> bool:
    async with aiosqlite.connect(_DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM seen_jobs WHERE source = ? AND job_id = ?",
            (source, job_id),
        )
        return await cursor.fetchone() is not None


async def mark_seen(source: str, job_id: str) -> None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_jobs (source, job_id) VALUES (?, ?)",
            (source, job_id),
        )
        await db.commit()


async def mark_seen_batch(jobs: list[tuple[str, str]]) -> None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.executemany(
            "INSERT OR IGNORE INTO seen_jobs (source, job_id) VALUES (?, ?)",
            jobs,
        )
        await db.commit()
