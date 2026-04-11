from __future__ import annotations

import logging

import httpx

from bot.company_names import resolve
from bot.models import Job

logger = logging.getLogger(__name__)

ASHBY_URL = "https://jobs.ashbyhq.com/api/non-user-graphql"

QUERY = """
query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {
  jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) {
    jobPostings {
      id
      title
      locationName
      employmentType
    }
  }
}
"""


async def scrape(slug: str, client: httpx.AsyncClient) -> list[Job]:
    payload = {
        "operationName": "ApiJobBoardWithTeams",
        "query": QUERY,
        "variables": {"organizationHostedJobsPageName": slug},
    }
    headers = {"content-type": "application/json"}
    try:
        resp = await client.post(
            ASHBY_URL,
            json=payload,
            headers={**headers, "origin": f"https://jobs.ashbyhq.com/{slug}"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Ashby %s failed: %s", slug, e)
        return []

    jobs = []
    data = resp.json().get("data", {}).get("jobBoardWithTeams") or {}
    for item in data.get("jobPostings", []):
        jobs.append(
            Job(
                id=item["id"],
                title=item["title"],
                company=resolve(slug),
                location=item.get("locationName", ""),
                url=f"https://jobs.ashbyhq.com/{slug}/{item['id']}",
                source="ashby",
                description=item.get("descriptionPlain") or None,
            )
        )
    return jobs
