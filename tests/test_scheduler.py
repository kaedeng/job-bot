from __future__ import annotations

import pytest
import httpx

from bot import db, scheduler


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_client(responses: list[httpx.Response]) -> httpx.AsyncClient:
    """Build an AsyncClient backed by a sequential mock transport."""
    queue = list(responses)

    async def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _resp(status: int, method: str = "GET") -> httpx.Response:
    return httpx.Response(
        status, request=httpx.Request(method, "https://example.com/jobs/1")
    )


# ---------------------------------------------------------------------------
# _check_url_live
# ---------------------------------------------------------------------------


class TestCheckUrlLive:
    async def test_200_returns_true(self):
        client = _make_client([_resp(200)])
        assert await scheduler._check_url_live(client, "https://example.com/jobs/1")

    async def test_404_returns_false(self):
        client = _make_client([_resp(404)])
        assert not await scheduler._check_url_live(client, "https://example.com/jobs/1")

    async def test_301_redirect_returns_true(self):
        # httpx follow_redirects resolves the chain; simulate final 200
        client = _make_client([_resp(200)])
        assert await scheduler._check_url_live(client, "https://example.com/jobs/1")

    async def test_405_falls_back_to_get_200(self):
        # HEAD returns 405, GET returns 200 → live
        client = _make_client([_resp(405, "HEAD"), _resp(200, "GET")])
        assert await scheduler._check_url_live(client, "https://example.com/jobs/1")

    async def test_405_falls_back_to_get_404(self):
        # HEAD returns 405, GET returns 404 → dead
        client = _make_client([_resp(405, "HEAD"), _resp(404, "GET")])
        assert not await scheduler._check_url_live(client, "https://example.com/jobs/1")

    async def test_429_treated_as_live(self):
        # Rate-limited responses should not mark jobs dead
        client = _make_client([_resp(429)])
        assert await scheduler._check_url_live(client, "https://example.com/jobs/1")

    async def test_500_treated_as_live(self):
        client = _make_client([_resp(500)])
        assert await scheduler._check_url_live(client, "https://example.com/jobs/1")

    async def test_network_error_treated_as_live(self):
        async def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("timeout", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        assert await scheduler._check_url_live(client, "https://example.com/jobs/1")


# ---------------------------------------------------------------------------
# poll_liveness (integration: real DB + mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.fixture
async def liveness_db(tmp_path, monkeypatch):
    path = str(tmp_path / "liveness.db")
    monkeypatch.setattr(db, "_DB_PATH", path)
    await db.init_db()
    return path


async def _insert(db_path: str, job_id: str, url: str, ingested_ago_hours: float = 2) -> int:
    import aiosqlite

    async with aiosqlite.connect(db_path) as conn:
        ingested_at = f"datetime('now', '-{ingested_ago_hours} hours')"
        cursor = await conn.execute(
            f"""
            INSERT INTO job_postings
                (source, job_id, title, company, location_raw, url,
                 is_intern, is_new_grad, is_remote, discipline,
                 is_active, ingested_at, last_checked_at)
            VALUES ('greenhouse', ?, 'SWE Intern', 'acme',
                    'Remote', ?, 1, 0, 0, 'swe', 1, {ingested_at}, NULL)
            """,  # noqa: S608
            (job_id, url),
        )
        await conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]


class TestPollLiveness:
    async def test_marks_404_inactive(self, liveness_db, monkeypatch):
        posting_id = await _insert(liveness_db, "j1", "https://example.com/jobs/j1")

        async def fake_check(client, url):
            return False  # simulate 404

        monkeypatch.setattr(scheduler, "_check_url_live", fake_check)
        await scheduler.poll_liveness()

        import aiosqlite
        async with aiosqlite.connect(liveness_db) as conn:
            cursor = await conn.execute(
                "SELECT is_active FROM job_postings WHERE id = ?", (posting_id,)
            )
            row = await cursor.fetchone()
        assert row[0] == 0

    async def test_touches_live_posting(self, liveness_db, monkeypatch):
        posting_id = await _insert(liveness_db, "j2", "https://example.com/jobs/j2")

        async def fake_check(client, url):
            return True  # simulate 200

        monkeypatch.setattr(scheduler, "_check_url_live", fake_check)
        await scheduler.poll_liveness()

        import aiosqlite
        async with aiosqlite.connect(liveness_db) as conn:
            cursor = await conn.execute(
                "SELECT is_active, last_checked_at FROM job_postings WHERE id = ?",
                (posting_id,),
            )
            row = await cursor.fetchone()
        assert row[0] == 1           # still active
        assert row[1] is not None    # timestamp updated

    async def test_skips_postings_checked_recently(self, liveness_db, monkeypatch):
        import aiosqlite

        async with aiosqlite.connect(liveness_db) as conn:
            await conn.execute(
                """
                INSERT INTO job_postings
                    (source, job_id, title, company, location_raw, url,
                     is_intern, is_new_grad, is_remote, discipline,
                     is_active, ingested_at, last_checked_at)
                VALUES ('greenhouse', 'j3', 'SWE Intern', 'acme',
                        'Remote', 'https://x', 1, 0, 0, 'swe', 1,
                        datetime('now', '-2 hours'), datetime('now', '-1 hour'))
                """
            )
            await conn.commit()

        called = []

        async def fake_check(client, url):
            called.append(url)
            return True

        monkeypatch.setattr(scheduler, "_check_url_live", fake_check)
        await scheduler.poll_liveness()
        assert called == []  # nothing probed — checked within 24h

    async def test_no_postings_is_noop(self, liveness_db, monkeypatch):
        called = []

        async def fake_check(client, url):
            called.append(url)
            return True

        monkeypatch.setattr(scheduler, "_check_url_live", fake_check)
        await scheduler.poll_liveness()
        assert called == []

    async def test_mixed_live_and_dead(self, liveness_db, monkeypatch):
        id_live = await _insert(liveness_db, "live", "https://example.com/live")
        id_dead = await _insert(liveness_db, "dead", "https://example.com/dead")

        async def fake_check(client, url):
            return "dead" not in url

        monkeypatch.setattr(scheduler, "_check_url_live", fake_check)
        await scheduler.poll_liveness()

        import aiosqlite
        async with aiosqlite.connect(liveness_db) as conn:
            cursor = await conn.execute(
                "SELECT id, is_active FROM job_postings ORDER BY id"
            )
            rows = {r[0]: r[1] for r in await cursor.fetchall()}
        assert rows[id_live] == 1
        assert rows[id_dead] == 0
