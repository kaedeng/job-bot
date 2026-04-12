import inspect

import httpx
import pytest

from bot.scrapers import CustomScraper, PlatformScraper, ashby, greenhouse, lever, simplify
from bot.scrapers.custom import amazon


@pytest.fixture
def mock_transport():
    """Helper to create an httpx.AsyncClient with a mocked response."""

    class _Transport:
        def __init__(self):
            self.responses: list[httpx.Response] = []

        def add(self, json_data: object, status_code: int = 200) -> None:
            self.responses.append(
                httpx.Response(
                    status_code, json=json_data, request=httpx.Request("GET", "https://x")
                )
            )

        def build_client(self) -> httpx.AsyncClient:
            responses = list(self.responses)

            async def handler(request: httpx.Request) -> httpx.Response:
                return responses.pop(0)

            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return _Transport()


class TestGreenhouse:
    async def test_parses_jobs(self, mock_transport):
        mock_transport.add(
            {
                "jobs": [
                    {
                        "id": 123,
                        "title": "Software Engineer Intern",
                        "location": {"name": "San Francisco, CA"},
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                    },
                    {
                        "id": 456,
                        "title": "Senior Backend Engineer",
                        "location": {"name": "New York, NY"},
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/456",
                    },
                ]
            }
        )
        client = mock_transport.build_client()
        jobs = await greenhouse.scrape("acme", client)

        assert len(jobs) == 2
        assert jobs[0].id == "123"
        assert jobs[0].title == "Software Engineer Intern"
        assert jobs[0].location == "San Francisco, CA"
        assert jobs[0].source == "greenhouse"
        assert jobs[0].company == "acme"

    async def test_empty_board(self, mock_transport):
        mock_transport.add({"jobs": []})
        client = mock_transport.build_client()
        jobs = await greenhouse.scrape("empty", client)
        assert jobs == []

    async def test_http_error_returns_empty(self, mock_transport):
        mock_transport.add({}, status_code=404)
        client = mock_transport.build_client()
        jobs = await greenhouse.scrape("nonexistent", client)
        assert jobs == []


class TestLever:
    async def test_parses_jobs(self, mock_transport):
        mock_transport.add(
            [
                {
                    "id": "abc-123",
                    "text": "New Grad Software Engineer",
                    "categories": {"location": "Seattle, WA"},
                    "hostedUrl": "https://jobs.lever.co/acme/abc-123",
                },
            ]
        )
        client = mock_transport.build_client()
        jobs = await lever.scrape("acme", client)

        assert len(jobs) == 1
        assert jobs[0].id == "abc-123"
        assert jobs[0].title == "New Grad Software Engineer"
        assert jobs[0].source == "lever"

    async def test_http_error_returns_empty(self, mock_transport):
        mock_transport.add({}, status_code=500)
        client = mock_transport.build_client()
        jobs = await lever.scrape("broken", client)
        assert jobs == []


class TestAshby:
    async def test_parses_jobs(self, mock_transport):
        mock_transport.add(
            {
                "data": {
                    "jobBoardWithTeams": {
                        "jobPostings": [
                            {
                                "id": "abc-123",
                                "title": "Software Engineer Intern",
                                "locationName": "San Francisco, CA",
                                "employmentType": "Internship",
                            }
                        ]
                    }
                }
            }
        )
        client = mock_transport.build_client()
        jobs = await ashby.scrape("acme", client)

        assert len(jobs) == 1
        assert jobs[0].id == "abc-123"
        assert jobs[0].title == "Software Engineer Intern"
        assert jobs[0].company == "acme"
        assert jobs[0].source == "ashby"
        assert jobs[0].location == "San Francisco, CA"
        assert jobs[0].url == "https://jobs.ashbyhq.com/acme/abc-123"

    async def test_empty_board(self, mock_transport):
        mock_transport.add({"data": {"jobBoardWithTeams": {"jobPostings": []}}})
        client = mock_transport.build_client()
        jobs = await ashby.scrape("empty", client)
        assert jobs == []

    async def test_null_board(self, mock_transport):
        mock_transport.add({"data": {"jobBoardWithTeams": None}})
        client = mock_transport.build_client()
        jobs = await ashby.scrape("null", client)
        assert jobs == []

    async def test_http_error_returns_empty(self, mock_transport):
        mock_transport.add({}, status_code=500)
        client = mock_transport.build_client()
        jobs = await ashby.scrape("broken", client)
        assert jobs == []


class TestSimplify:
    async def test_parses_intern_and_newgrad(self, mock_transport):
        mock_transport.add(
            [
                {
                    "id": "i1",
                    "title": "SWE Intern",
                    "company_name": "Acme",
                    "locations": ["San Francisco, CA"],
                    "url": "https://acme.com/i1",
                    "active": True,
                },
            ]
        )
        mock_transport.add(
            [
                {
                    "id": "g1",
                    "title": "New Grad SWE",
                    "company_name": "Acme",
                    "locations": ["Seattle, WA"],
                    "url": "https://acme.com/g1",
                    "active": True,
                },
            ]
        )
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client)

        assert len(jobs) == 2
        sources = {j.source for j in jobs}
        assert "simplify-intern" in sources
        assert "simplify-newgrad" in sources

    async def test_skips_inactive(self, mock_transport):
        mock_transport.add(
            [
                {
                    "id": "i1",
                    "title": "SWE Intern",
                    "company_name": "Acme",
                    "locations": [],
                    "url": "",
                    "active": False,
                },
                {
                    "id": "i2",
                    "title": "SWE Intern",
                    "company_name": "Beta",
                    "locations": [],
                    "url": "",
                    "active": True,
                },
            ]
        )
        mock_transport.add([])
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client)
        assert len(jobs) == 1
        assert jobs[0].id == "i2"

    async def test_filters_by_company(self, mock_transport):
        mock_transport.add(
            [
                {
                    "id": "i1",
                    "title": "SWE Intern",
                    "company_name": "Stripe",
                    "locations": [],
                    "url": "",
                    "active": True,
                },
                {
                    "id": "i2",
                    "title": "SWE Intern",
                    "company_name": "Ramp",
                    "locations": [],
                    "url": "",
                    "active": True,
                },
            ]
        )
        mock_transport.add([])
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client, companies=frozenset(["stripe"]))
        assert len(jobs) == 1
        assert jobs[0].company == "Stripe"

    async def test_http_error_continues_to_next_source(self, mock_transport):
        # intern endpoint fails — bot should still return newgrad results
        mock_transport.add({}, status_code=500)
        mock_transport.add(
            [
                {
                    "id": "g1",
                    "title": "New Grad SWE",
                    "company_name": "Acme",
                    "locations": [],
                    "url": "",
                    "active": True,
                },
            ]
        )
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client)
        assert len(jobs) == 1
        assert jobs[0].source == "simplify-newgrad"

    async def test_locations_joined(self, mock_transport):
        mock_transport.add(
            [
                {
                    "id": "i1",
                    "title": "SWE Intern",
                    "company_name": "Acme",
                    "locations": ["San Francisco, CA", "Seattle, WA"],
                    "url": "",
                    "active": True,
                },
            ]
        )
        mock_transport.add([])
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client)
        assert jobs[0].location == "San Francisco, CA; Seattle, WA"

    async def test_empty_locations(self, mock_transport):
        mock_transport.add(
            [
                {
                    "id": "i1",
                    "title": "SWE Intern",
                    "company_name": "Acme",
                    "locations": [],
                    "url": "",
                    "active": True,
                },
            ]
        )
        mock_transport.add([])
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client)
        assert jobs[0].location == ""


# ---------------------------------------------------------------------------
# Scraper protocol contracts
# ---------------------------------------------------------------------------


class TestScraperContracts:
    """Verify that each scraper module exposes the expected interface."""

    def test_platform_scrapers_have_correct_signature(self):
        for mod in (greenhouse, lever, ashby):
            sig = inspect.signature(mod.scrape)
            params = list(sig.parameters)
            assert params == ["slug", "client"], (
                f"{mod.__name__}.scrape signature should be (slug, client), got {params}"
            )

    def test_custom_scraper_has_correct_signature(self):
        sig = inspect.signature(amazon.scrape)
        params = list(sig.parameters)
        assert params == ["client"], f"amazon.scrape signature should be (client,), got {params}"

    def test_protocol_types_are_importable(self):
        # Ensures the public API of bot.scrapers is stable
        assert PlatformScraper is not None
        assert CustomScraper is not None


# ---------------------------------------------------------------------------
# Amazon scraper
# ---------------------------------------------------------------------------


def _hit(
    id: str = "111",
    title: str = "Software Development Engineer Intern",
    normalized_location: str = "Seattle, Washington, United States",
    job_path: str = "/en/jobs/111/software-development-engineer-intern",
    posted_date: str = "April 7, 2025",
    description_short: str = "Build cool things.",
    basic_qualifications: str = "Currently pursuing a BS in CS.",
) -> dict:
    return {
        "id_icims": id,
        "title": title,
        "normalized_location": normalized_location,
        "location": "Seattle, WA",  # raw fallback
        "job_path": job_path,
        "posted_date": posted_date,
        "description_short": description_short,
        "basic_qualifications": basic_qualifications,
    }


def _empty() -> dict:
    """A minimal response with no jobs — terminates the pagination loop."""
    return {"jobs": [], "hits": 0}


def _page(job_list: list[dict], total: int | None = None) -> dict:
    # "hits" = total count (integer), "jobs" = list for this page
    return {"jobs": job_list, "hits": total if total is not None else len(job_list)}


# amazon.scrape iterates: software-development/intern, software-development/new grad,
# hardware-engineering/intern, hardware-engineering/new grad
# For tests that only care about one chain, pad the remaining 3 with empty responses.
_EMPTY_PADDING = 3


class TestAmazon:
    async def test_parses_job_fields(self, mock_transport):
        mock_transport.add(_page([_hit()]))
        for _ in range(_EMPTY_PADDING):
            mock_transport.add(_empty())

        jobs = await amazon.scrape(mock_transport.build_client())

        assert len(jobs) == 1
        j = jobs[0]
        assert j.id == "111"
        assert j.title == "Software Development Engineer Intern"
        assert j.company == "amazon"
        assert j.source == "amazon"
        assert j.location == "Seattle, Washington, United States"
        assert j.url == "https://www.amazon.jobs/en/jobs/111/software-development-engineer-intern"
        assert j.posted_at is not None
        assert j.posted_at.year == 2025
        assert j.posted_at.month == 4
        assert j.posted_at.day == 7
        assert "Build cool things." in (j.description or "")
        assert "Currently pursuing" in (j.description or "")

    async def test_deduplicates_same_id_across_queries(self, mock_transport):
        # Same id appears in both software-development chains
        hit = _hit(id="dup")
        mock_transport.add(_page([hit]))  # sw-dev / intern
        mock_transport.add(_page([hit]))  # sw-dev / new grad — duplicate
        mock_transport.add(_empty())  # hw / intern
        mock_transport.add(_empty())  # hw / new grad

        jobs = await amazon.scrape(mock_transport.build_client())
        assert len(jobs) == 1
        assert jobs[0].id == "dup"

    async def test_aggregates_across_all_chains(self, mock_transport):
        # One unique job per chain
        mock_transport.add(_page([_hit("a")]))  # sw / intern
        mock_transport.add(_page([_hit("b")]))  # sw / new grad
        mock_transport.add(_page([_hit("c")]))  # hw / intern
        mock_transport.add(_page([_hit("d")]))  # hw / new grad

        jobs = await amazon.scrape(mock_transport.build_client())
        assert {j.id for j in jobs} == {"a", "b", "c", "d"}

    async def test_paginates_when_count_exceeds_limit(self, mock_transport):
        page1_hits = [_hit(str(i)) for i in range(100)]
        page2_hits = [_hit(str(i)) for i in range(100, 130)]

        mock_transport.add(_page(page1_hits, total=130))  # sw / intern, offset=0
        mock_transport.add(_page(page2_hits, total=130))  # sw / intern, offset=100
        for _ in range(_EMPTY_PADDING):
            mock_transport.add(_empty())

        jobs = await amazon.scrape(mock_transport.build_client())
        assert len(jobs) == 130

    async def test_stops_pagination_at_max_pages(self, mock_transport):
        # count is huge but MAX_PAGES=3 caps at 300 requests per chain.
        # Each page needs unique ids to avoid dedup collapsing results.
        for page in range(3):
            hits = [_hit(str(page * 100 + i)) for i in range(100)]
            mock_transport.add(_page(hits, total=10_000))
        for _ in range(_EMPTY_PADDING):
            mock_transport.add(_empty())

        jobs = await amazon.scrape(mock_transport.build_client())
        assert len(jobs) == 300

    async def test_http_error_skips_chain_continues_next(self, mock_transport):
        mock_transport.add({"jobs": []}, status_code=500)  # sw / intern fails
        mock_transport.add(_page([_hit("ok")]))  # sw / new grad succeeds
        mock_transport.add(_empty())
        mock_transport.add(_empty())

        jobs = await amazon.scrape(mock_transport.build_client())
        assert len(jobs) == 1
        assert jobs[0].id == "ok"

    async def test_empty_hits_stops_pagination(self, mock_transport):
        mock_transport.add(_empty())  # sw / intern: no hits → no more pages
        for _ in range(_EMPTY_PADDING):
            mock_transport.add(_empty())

        jobs = await amazon.scrape(mock_transport.build_client())
        assert jobs == []

    async def test_falls_back_to_raw_location(self, mock_transport):
        hit = _hit(normalized_location="")
        hit["normalized_location"] = ""
        mock_transport.add(_page([hit]))
        for _ in range(_EMPTY_PADDING):
            mock_transport.add(_empty())

        jobs = await amazon.scrape(mock_transport.build_client())
        assert jobs[0].location == "Seattle, WA"  # raw fallback

    async def test_missing_optional_fields_do_not_crash(self, mock_transport):
        sparse = {"id_icims": "999", "title": "SWE Intern", "job_path": ""}
        mock_transport.add(_page([sparse]))
        for _ in range(_EMPTY_PADDING):
            mock_transport.add(_empty())

        jobs = await amazon.scrape(mock_transport.build_client())
        assert len(jobs) == 1
        assert jobs[0].id == "999"
        assert jobs[0].location == ""
        assert jobs[0].url == ""
        assert jobs[0].posted_at is None
        assert jobs[0].description is None

    async def test_unparseable_date_returns_none(self, mock_transport):
        hit = _hit(posted_date="not-a-date")
        mock_transport.add(_page([hit]))
        for _ in range(_EMPTY_PADDING):
            mock_transport.add(_empty())

        jobs = await amazon.scrape(mock_transport.build_client())
        assert jobs[0].posted_at is None

    async def test_skips_items_with_no_id(self, mock_transport):
        no_id = {"title": "Ghost Job", "job_path": "/en/jobs/x"}
        mock_transport.add(_page([no_id, _hit("real")]))
        for _ in range(_EMPTY_PADDING):
            mock_transport.add(_empty())

        jobs = await amazon.scrape(mock_transport.build_client())
        assert len(jobs) == 1
        assert jobs[0].id == "real"
