from __future__ import annotations

import aiosqlite
import pytest

from bot import db
from bot.filters import classify_discipline, classify_job, parse_locations
from bot.models import Job


def _job(
    id: str = "1",
    title: str = "Software Engineer Intern",
    company: str = "acme",
    location: str = "San Francisco, CA",
    source: str = "greenhouse",
    description: str | None = None,
) -> Job:
    return Job(
        id=id,
        title=title,
        company=company,
        location=location,
        url=f"https://example.com/jobs/{id}",
        source=source,
        description=description,
    )


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "_DB_PATH", path)
    await db.init_db()
    return path


async def _store(jobs: list[Job]) -> None:
    await db.store_jobs_batch(jobs, parse_locations, classify_job, classify_discipline)


# ---------------------------------------------------------------------------
# _strip_description
# ---------------------------------------------------------------------------


class TestStripDescription:
    def test_strips_html_tags(self):
        assert db._strip_description("<p>Hello <b>World</b></p>") == "Hello World"

    def test_collapses_whitespace(self):
        assert db._strip_description("foo   bar\n\nbaz") == "foo bar baz"

    def test_truncates_to_5000(self):
        long_text = "a" * 6000
        assert len(db._strip_description(long_text)) == 5000

    def test_empty_string(self):
        assert db._strip_description("") == ""

    def test_nested_html(self):
        result = db._strip_description("<div><ul><li>Item</li></ul></div>")
        assert "Item" in result
        assert "<" not in result


# ---------------------------------------------------------------------------
# is_seen
# ---------------------------------------------------------------------------


class TestIsSeen:
    async def test_not_seen_initially(self, fresh_db):
        assert not await db.is_seen("greenhouse", "123")

    async def test_seen_after_store(self, fresh_db):
        await _store([_job(id="1", source="greenhouse")])
        assert await db.is_seen("greenhouse", "1")

    async def test_different_source_not_seen(self, fresh_db):
        await _store([_job(id="1", source="greenhouse")])
        assert not await db.is_seen("lever", "1")

    async def test_different_id_not_seen(self, fresh_db):
        await _store([_job(id="1")])
        assert not await db.is_seen("greenhouse", "999")


# ---------------------------------------------------------------------------
# store_jobs_batch
# ---------------------------------------------------------------------------


class TestStoreJobsBatch:
    async def test_basic_insert(self, fresh_db):
        await _store([_job()])
        rows = await db.query_jobs(role="all")
        assert len(rows) == 1
        assert rows[0]["title"] == "Software Engineer Intern"
        assert rows[0]["company"] == "acme"

    async def test_dedup_skips_duplicate(self, fresh_db):
        await _store([_job()])
        await _store([_job()])
        rows = await db.query_jobs(role="all")
        assert len(rows) == 1

    async def test_strips_and_stores_description(self, fresh_db):
        await _store([_job(description="<p>Hello <b>World</b></p>")])
        rows = await db.query_jobs(role="all")
        assert rows[0]["description_text"] == "Hello World"

    async def test_null_description_stored_as_none(self, fresh_db):
        await _store([_job(description=None)])
        rows = await db.query_jobs(role="all")
        assert rows[0]["description_text"] is None

    async def test_creates_job_location_record(self, fresh_db):
        await _store([_job(location="San Francisco, CA")])
        rows = await db.query_jobs(state="CA", role="all")
        assert len(rows) == 1

    async def test_classifies_intern(self, fresh_db):
        await _store([_job(title="Software Engineer Intern")])
        rows = await db.query_jobs(role="intern")
        assert len(rows) == 1
        assert rows[0]["is_intern"] == 1

    async def test_classifies_new_grad(self, fresh_db):
        await _store([_job(title="New Grad Software Engineer")])
        rows = await db.query_jobs(role="new_grad")
        assert len(rows) == 1
        assert rows[0]["is_new_grad"] == 1

    async def test_classifies_swe_discipline(self, fresh_db):
        await _store([_job(title="Software Engineer Intern")])
        rows = await db.query_jobs(discipline="swe", role="all")
        assert len(rows) == 1

    async def test_classifies_ee_discipline(self, fresh_db):
        await _store([_job(title="Electrical Engineer Intern", location="Austin, TX")])
        rows = await db.query_jobs(discipline="ee", role="all")
        assert len(rows) == 1

    async def test_is_remote_flag(self, fresh_db):
        await _store([_job(location="Remote")])
        rows = await db.query_jobs(role="all")
        assert rows[0]["is_remote"] == 1

    async def test_multiple_jobs(self, fresh_db):
        jobs = [_job(id=str(i), title=f"Software Engineer Intern {i}") for i in range(3)]
        await _store(jobs)
        rows = await db.query_jobs(role="all")
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# query_jobs
# ---------------------------------------------------------------------------


class TestQueryJobs:
    async def test_keyword_filter_title(self, fresh_db):
        await _store([
            _job(id="1", title="Python Backend Intern", location="New York, NY"),
            _job(id="2", title="Frontend Engineer Intern", location="Seattle, WA"),
        ])
        rows = await db.query_jobs(keyword="Python")
        assert len(rows) == 1
        assert rows[0]["title"] == "Python Backend Intern"

    async def test_keyword_or_logic(self, fresh_db):
        await _store([
            _job(id="1", title="Python Backend Intern", location="New York, NY"),
            _job(id="2", title="React Frontend Intern", location="Seattle, WA"),
            _job(id="3", title="DevOps Engineer Intern", location="Austin, TX"),
        ])
        rows = await db.query_jobs(keyword="Python,React")
        titles = {r["title"] for r in rows}
        assert "Python Backend Intern" in titles
        assert "React Frontend Intern" in titles
        assert "DevOps Engineer Intern" not in titles

    async def test_keyword_matches_description_text(self, fresh_db):
        await _store([_job(id="1", description="<p>Looking for React experience</p>")])
        rows = await db.query_jobs(keyword="React")
        assert len(rows) == 1

    async def test_company_filter(self, fresh_db):
        await _store([
            _job(id="1", company="stripe"),
            _job(id="2", company="ramp"),
        ])
        rows = await db.query_jobs(company="stripe", role="all")
        assert len(rows) == 1
        assert rows[0]["company"] == "stripe"

    async def test_company_or_logic(self, fresh_db):
        await _store([
            _job(id="1", company="stripe"),
            _job(id="2", company="ramp"),
            _job(id="3", company="anthropic"),
        ])
        rows = await db.query_jobs(company="stripe,ramp", role="all")
        companies = {r["company"] for r in rows}
        assert companies == {"stripe", "ramp"}

    async def test_role_intern(self, fresh_db):
        await _store([
            _job(id="1", title="Software Engineer Intern"),
            _job(id="2", title="New Grad Software Engineer"),
        ])
        rows = await db.query_jobs(role="intern")
        assert len(rows) == 1
        assert rows[0]["is_intern"] == 1

    async def test_role_new_grad(self, fresh_db):
        await _store([
            _job(id="1", title="Software Engineer Intern"),
            _job(id="2", title="New Grad Software Engineer"),
        ])
        rows = await db.query_jobs(role="new_grad")
        assert len(rows) == 1
        assert rows[0]["is_new_grad"] == 1

    async def test_role_all(self, fresh_db):
        await _store([
            _job(id="1", title="Software Engineer Intern"),
            _job(id="2", title="New Grad Software Engineer"),
        ])
        rows = await db.query_jobs(role="all")
        assert len(rows) == 2

    async def test_default_role_excludes_unclassified(self, fresh_db):
        # Insert a job with is_intern=0, is_new_grad=0 directly
        async with aiosqlite.connect(fresh_db) as conn:
            await conn.execute(
                """INSERT INTO job_postings
                   (source, job_id, title, company, location_raw, url,
                    is_intern, is_new_grad, is_remote, discipline)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("test", "999", "Software Engineer", "acme",
                 "Seattle, WA", "https://x", 0, 0, 0, "swe"),
            )
            await conn.commit()
        rows = await db.query_jobs()
        assert all(r["title"] != "Software Engineer" for r in rows)

    async def test_role_or_logic(self, fresh_db):
        await _store([
            _job(id="1", title="Software Engineer Intern"),
            _job(id="2", title="New Grad Software Engineer"),
        ])
        rows = await db.query_jobs(role="intern,new_grad")
        assert len(rows) == 2

    async def test_discipline_filter(self, fresh_db):
        await _store([
            _job(id="1", title="Software Engineer Intern"),
            _job(id="2", title="Electrical Engineer Intern", location="Austin, TX"),
        ])
        rows = await db.query_jobs(discipline="swe", role="all")
        assert all(r["discipline"] == "swe" for r in rows)

    async def test_discipline_or_logic(self, fresh_db):
        await _store([
            _job(id="1", title="Software Engineer Intern"),
            _job(id="2", title="Electrical Engineer Intern", location="Austin, TX"),
        ])
        rows = await db.query_jobs(discipline="swe,ee", role="all")
        assert len(rows) == 2

    async def test_state_filter(self, fresh_db):
        await _store([
            _job(id="1", title="Software Engineer Intern", location="San Francisco, CA"),
            _job(id="2", title="New Grad Software Engineer", location="Seattle, WA"),
        ])
        rows = await db.query_jobs(state="CA")
        assert len(rows) == 1
        assert rows[0]["location_raw"] == "San Francisco, CA"

    async def test_state_or_logic(self, fresh_db):
        await _store([
            _job(id="1", title="Software Engineer Intern", location="San Francisco, CA"),
            _job(id="2", title="New Grad Software Engineer", location="Seattle, WA"),
            _job(id="3", title="Backend Engineer Intern", location="Austin, TX"),
        ])
        rows = await db.query_jobs(state="CA,WA")
        assert len(rows) == 2

    async def test_season_filter(self, fresh_db):
        await _store([
            _job(id="1", title="Software Engineer Summer Intern"),
            _job(id="2", title="Software Engineer Fall Intern"),
        ])
        rows = await db.query_jobs(season="summer")
        assert len(rows) == 1
        assert "Summer" in rows[0]["title"]

    async def test_limit(self, fresh_db):
        jobs = [_job(id=str(i)) for i in range(5)]
        for j in jobs:
            await _store([j])
        rows = await db.query_jobs(limit=3, role="all")
        assert len(rows) == 3

    async def test_offset_pagination(self, fresh_db):
        jobs = [_job(id=str(i), title=f"Software Engineer Intern {i}") for i in range(5)]
        for j in jobs:
            await _store([j])
        page1 = await db.query_jobs(limit=3, offset=0, role="all")
        page2 = await db.query_jobs(limit=3, offset=3, role="all")
        ids1 = {r["job_id"] for r in page1}
        ids2 = {r["job_id"] for r in page2}
        assert ids1.isdisjoint(ids2)

    async def test_empty_result(self, fresh_db):
        rows = await db.query_jobs(keyword="xyzzy_nonexistent")
        assert rows == []

    async def test_limit_capped_at_25(self, fresh_db):
        jobs = [_job(id=str(i)) for i in range(30)]
        for j in jobs:
            await _store([j])
        rows = await db.query_jobs(limit=30, role="all")
        assert len(rows) <= 25

    async def test_ordered_by_ingested_at_desc(self, fresh_db):
        # Insert multiple and confirm descending order
        jobs = [_job(id=str(i), title=f"Software Engineer Intern {i}") for i in range(3)]
        for j in jobs:
            await _store([j])
        rows = await db.query_jobs(role="all")
        ingested = [r["ingested_at"] for r in rows]
        assert ingested == sorted(ingested, reverse=True)


# ---------------------------------------------------------------------------
# user_preferences
# ---------------------------------------------------------------------------


class TestUserPreferences:
    async def test_get_nonexistent_returns_none(self, fresh_db):
        assert await db.get_user_prefs("999") is None

    async def test_upsert_creates_with_defaults(self, fresh_db):
        await db.upsert_user_prefs("123")
        prefs = await db.get_user_prefs("123")
        assert prefs is not None
        assert prefs["dm_enabled"] == 1
        assert prefs["alert_interval_minutes"] == 60
        assert prefs["companies"] == []

    async def test_upsert_updates_dm_enabled(self, fresh_db):
        await db.upsert_user_prefs("123", dm_enabled=0)
        prefs = await db.get_user_prefs("123")
        assert prefs["dm_enabled"] == 0

    async def test_upsert_updates_companies(self, fresh_db):
        await db.upsert_user_prefs("123", companies=["stripe", "ramp"])
        prefs = await db.get_user_prefs("123")
        assert prefs["companies"] == ["stripe", "ramp"]

    async def test_upsert_idempotent(self, fresh_db):
        await db.upsert_user_prefs("123")
        await db.upsert_user_prefs("123", dm_enabled=0)
        prefs = await db.get_user_prefs("123")
        assert prefs["dm_enabled"] == 0

    async def test_companies_serialized_as_json(self, fresh_db):
        await db.upsert_user_prefs("123", companies=["a", "b"])
        # Read raw from DB to confirm JSON storage
        async with aiosqlite.connect(fresh_db) as conn:
            cursor = await conn.execute(
                "SELECT companies FROM user_preferences WHERE user_id = '123'"
            )
            row = await cursor.fetchone()
        import json
        assert json.loads(row[0]) == ["a", "b"]


# ---------------------------------------------------------------------------
# user_filter_rules
# ---------------------------------------------------------------------------


class TestUserFilterRules:
    async def test_add_rule_returns_id(self, fresh_db):
        rule_id = await db.add_user_filter_rule("123", "intern", "us")
        assert isinstance(rule_id, int)

    async def test_get_rules(self, fresh_db):
        await db.add_user_filter_rule("123", "intern", "us")
        await db.add_user_filter_rule("123", "new_grad", "state:CO")
        rules = await db.get_user_filter_rules("123")
        assert len(rules) == 2
        assert rules[0]["role_type"] == "intern"
        assert rules[0]["location_scope"] == "us"
        assert rules[1]["role_type"] == "new_grad"
        assert rules[1]["location_scope"] == "state:CO"

    async def test_get_rules_empty(self, fresh_db):
        assert await db.get_user_filter_rules("nobody") == []

    async def test_remove_rule(self, fresh_db):
        rule_id = await db.add_user_filter_rule("123", "intern", "us")
        removed = await db.remove_user_filter_rule(rule_id, "123")
        assert removed is True
        assert await db.get_user_filter_rules("123") == []

    async def test_remove_rule_wrong_user(self, fresh_db):
        rule_id = await db.add_user_filter_rule("123", "intern", "us")
        removed = await db.remove_user_filter_rule(rule_id, "999")
        assert removed is False
        # Rule must still exist for the correct user
        assert len(await db.get_user_filter_rules("123")) == 1

    async def test_remove_nonexistent_rule(self, fresh_db):
        removed = await db.remove_user_filter_rule(9999, "123")
        assert removed is False

    async def test_add_rule_creates_user_prefs(self, fresh_db):
        await db.add_user_filter_rule("newuser", "intern", "remote")
        prefs = await db.get_user_prefs("newuser")
        assert prefs is not None

    async def test_rules_isolated_per_user(self, fresh_db):
        await db.add_user_filter_rule("alice", "intern", "us")
        await db.add_user_filter_rule("bob", "new_grad", "state:WA")
        alice_rules = await db.get_user_filter_rules("alice")
        bob_rules = await db.get_user_filter_rules("bob")
        assert len(alice_rules) == 1
        assert len(bob_rules) == 1
        assert alice_rules[0]["user_id"] == "alice"
        assert bob_rules[0]["user_id"] == "bob"


# ---------------------------------------------------------------------------
# liveness verification
# ---------------------------------------------------------------------------


async def _insert_posting(
    db_path: str,
    *,
    job_id: str = "1",
    source: str = "greenhouse",
    ingested_ago_hours: float = 2,
    last_checked_ago_hours: float | None = None,
    is_active: int = 1,
) -> int:
    """Insert a job_posting with controllable timestamps. Returns the row id."""
    async with aiosqlite.connect(db_path) as conn:
        ingested_at = f"datetime('now', '-{ingested_ago_hours} hours')"
        if last_checked_ago_hours is None:
            checked_expr = "NULL"
        else:
            checked_expr = f"datetime('now', '-{last_checked_ago_hours} hours')"
        cursor = await conn.execute(
            f"""
            INSERT INTO job_postings
                (source, job_id, title, company, location_raw, url,
                 is_intern, is_new_grad, is_remote, discipline,
                 is_active, ingested_at, last_checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, {ingested_at}, {checked_expr})
            """,  # noqa: S608
            (
                source, job_id, "Software Engineer Intern", "acme",
                "San Francisco, CA", f"https://example.com/jobs/{job_id}",
                1, 0, 0, "swe", is_active,
            ),
        )
        await conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]


class TestGetPostingsDueForLivenessCheck:
    async def test_returns_posting_never_checked(self, fresh_db):
        await _insert_posting(fresh_db, ingested_ago_hours=2, last_checked_ago_hours=None)
        postings = await db.get_postings_due_for_liveness_check(
            min_age_hours=1, recheck_interval_hours=24
        )
        assert len(postings) == 1

    async def test_excludes_posting_too_new(self, fresh_db):
        await _insert_posting(fresh_db, ingested_ago_hours=0.1, last_checked_ago_hours=None)
        postings = await db.get_postings_due_for_liveness_check(
            min_age_hours=1, recheck_interval_hours=24
        )
        assert postings == []

    async def test_excludes_recently_checked(self, fresh_db):
        await _insert_posting(fresh_db, ingested_ago_hours=2, last_checked_ago_hours=1)
        postings = await db.get_postings_due_for_liveness_check(
            min_age_hours=1, recheck_interval_hours=24
        )
        assert postings == []

    async def test_includes_stale_checked(self, fresh_db):
        await _insert_posting(fresh_db, ingested_ago_hours=48, last_checked_ago_hours=25)
        postings = await db.get_postings_due_for_liveness_check(
            min_age_hours=1, recheck_interval_hours=24
        )
        assert len(postings) == 1

    async def test_excludes_inactive_posting(self, fresh_db):
        await _insert_posting(fresh_db, ingested_ago_hours=2, is_active=0)
        postings = await db.get_postings_due_for_liveness_check(
            min_age_hours=1, recheck_interval_hours=24
        )
        assert postings == []

    async def test_respects_batch_size(self, fresh_db):
        for i in range(5):
            await _insert_posting(fresh_db, job_id=str(i), ingested_ago_hours=2)
        postings = await db.get_postings_due_for_liveness_check(
            min_age_hours=1, recheck_interval_hours=24, batch_size=3
        )
        assert len(postings) == 3

    async def test_result_has_expected_fields(self, fresh_db):
        await _insert_posting(fresh_db, job_id="abc", source="lever", ingested_ago_hours=2)
        postings = await db.get_postings_due_for_liveness_check(
            min_age_hours=1, recheck_interval_hours=24
        )
        assert postings[0]["job_id"] == "abc"
        assert postings[0]["source"] == "lever"
        assert "url" in postings[0]
        assert "id" in postings[0]


class TestMarkJobInactive:
    async def test_sets_is_active_to_zero(self, fresh_db):
        posting_id = await _insert_posting(fresh_db, ingested_ago_hours=2)
        await db.mark_job_inactive(posting_id)
        async with aiosqlite.connect(fresh_db) as conn:
            cursor = await conn.execute(
                "SELECT is_active FROM job_postings WHERE id = ?", (posting_id,)
            )
            row = await cursor.fetchone()
        assert row[0] == 0

    async def test_sets_last_checked_at(self, fresh_db):
        posting_id = await _insert_posting(fresh_db, ingested_ago_hours=2)
        await db.mark_job_inactive(posting_id)
        async with aiosqlite.connect(fresh_db) as conn:
            cursor = await conn.execute(
                "SELECT last_checked_at FROM job_postings WHERE id = ?", (posting_id,)
            )
            row = await cursor.fetchone()
        assert row[0] is not None

    async def test_inactive_job_not_returned_by_query(self, fresh_db):
        posting_id = await _insert_posting(fresh_db, job_id="dead", ingested_ago_hours=2)
        await db.mark_job_inactive(posting_id)
        rows = await db.query_jobs(role="all")
        assert all(r["job_id"] != "dead" for r in rows)


class TestTouchLivenessCheck:
    async def test_updates_last_checked_at(self, fresh_db):
        posting_id = await _insert_posting(
            fresh_db, ingested_ago_hours=48, last_checked_ago_hours=25
        )
        await db.touch_liveness_check(posting_id)
        async with aiosqlite.connect(fresh_db) as conn:
            cursor = await conn.execute(
                "SELECT last_checked_at FROM job_postings WHERE id = ?", (posting_id,)
            )
            row = await cursor.fetchone()
        assert row[0] is not None

    async def test_still_active_after_touch(self, fresh_db):
        posting_id = await _insert_posting(fresh_db, ingested_ago_hours=2)
        await db.touch_liveness_check(posting_id)
        async with aiosqlite.connect(fresh_db) as conn:
            cursor = await conn.execute(
                "SELECT is_active FROM job_postings WHERE id = ?", (posting_id,)
            )
            row = await cursor.fetchone()
        assert row[0] == 1

    async def test_touched_posting_not_requeued(self, fresh_db):
        posting_id = await _insert_posting(fresh_db, ingested_ago_hours=2)
        await db.touch_liveness_check(posting_id)
        postings = await db.get_postings_due_for_liveness_check(
            min_age_hours=1, recheck_interval_hours=24
        )
        assert all(p["id"] != posting_id for p in postings)


class TestQueryJobsExcludesInactive:
    async def test_inactive_job_hidden_from_query(self, fresh_db):
        # Store via normal path (is_active defaults to 1)
        await _store([_job(id="live")])
        # Insert a second posting manually with is_active=0
        await _insert_posting(fresh_db, job_id="dead", ingested_ago_hours=2, is_active=0)
        rows = await db.query_jobs(role="all")
        job_ids = {r["job_id"] for r in rows}
        assert "live" in job_ids
        assert "dead" not in job_ids
