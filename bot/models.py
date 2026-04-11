from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    title: str
    company: str
    location: str
    url: str
    source: str
    posted_at: datetime | None = None
    description: str | None = None  # scraped text — classified at ingestion, never stored to DB
