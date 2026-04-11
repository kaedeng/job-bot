import httpx
import pytest

from bot.scrapers import ashby, greenhouse, lever, simplify


@pytest.fixture
def mock_transport():
    """Helper to create an httpx.AsyncClient with a mocked response."""

    class _Transport:
        def __init__(self):
            self.responses: list[httpx.Response] = []

        def add(self, json_data: object, status_code: int = 200) -> None:
            self.responses.append(
                httpx.Response(status_code, json=json_data, request=httpx.Request("GET", "https://x"))
            )

        def build_client(self) -> httpx.AsyncClient:
            responses = list(self.responses)

            async def handler(request: httpx.Request) -> httpx.Response:
                return responses.pop(0)

            return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return _Transport()


class TestGreenhouse:
    async def test_parses_jobs(self, mock_transport):
        mock_transport.add({
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
        })
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
        mock_transport.add([
            {
                "id": "abc-123",
                "text": "New Grad Software Engineer",
                "categories": {"location": "Seattle, WA"},
                "hostedUrl": "https://jobs.lever.co/acme/abc-123",
            },
        ])
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
        mock_transport.add({
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
        })
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
        mock_transport.add([
            {"id": "i1", "title": "SWE Intern", "company_name": "Acme",
             "locations": ["San Francisco, CA"], "url": "https://acme.com/i1", "active": True},
        ])
        mock_transport.add([
            {"id": "g1", "title": "New Grad SWE", "company_name": "Acme",
             "locations": ["Seattle, WA"], "url": "https://acme.com/g1", "active": True},
        ])
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client)

        assert len(jobs) == 2
        sources = {j.source for j in jobs}
        assert "simplify-intern" in sources
        assert "simplify-newgrad" in sources

    async def test_skips_inactive(self, mock_transport):
        mock_transport.add([
            {"id": "i1", "title": "SWE Intern", "company_name": "Acme",
             "locations": [], "url": "", "active": False},
            {"id": "i2", "title": "SWE Intern", "company_name": "Beta",
             "locations": [], "url": "", "active": True},
        ])
        mock_transport.add([])
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client)
        assert len(jobs) == 1
        assert jobs[0].id == "i2"

    async def test_filters_by_company(self, mock_transport):
        mock_transport.add([
            {"id": "i1", "title": "SWE Intern", "company_name": "Stripe",
             "locations": [], "url": "", "active": True},
            {"id": "i2", "title": "SWE Intern", "company_name": "Ramp",
             "locations": [], "url": "", "active": True},
        ])
        mock_transport.add([])
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client, companies=frozenset(["stripe"]))
        assert len(jobs) == 1
        assert jobs[0].company == "Stripe"

    async def test_http_error_continues_to_next_source(self, mock_transport):
        # intern endpoint fails — bot should still return newgrad results
        mock_transport.add({}, status_code=500)
        mock_transport.add([
            {"id": "g1", "title": "New Grad SWE", "company_name": "Acme",
             "locations": [], "url": "", "active": True},
        ])
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client)
        assert len(jobs) == 1
        assert jobs[0].source == "simplify-newgrad"

    async def test_locations_joined(self, mock_transport):
        mock_transport.add([
            {"id": "i1", "title": "SWE Intern", "company_name": "Acme",
             "locations": ["San Francisco, CA", "Seattle, WA"], "url": "", "active": True},
        ])
        mock_transport.add([])
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client)
        assert jobs[0].location == "San Francisco, CA, Seattle, WA"

    async def test_empty_locations(self, mock_transport):
        mock_transport.add([
            {"id": "i1", "title": "SWE Intern", "company_name": "Acme",
             "locations": [], "url": "", "active": True},
        ])
        mock_transport.add([])
        client = mock_transport.build_client()
        jobs = await simplify.scrape(client)
        assert jobs[0].location == ""
