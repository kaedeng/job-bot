from __future__ import annotations

import logging

import discord
import httpx
from discord import app_commands

from bot import db, scheduler
from bot.filters import classify_job, is_tech_job, passes_filter
from bot.models import Job
from bot.scrapers import ashby, greenhouse, lever

logger = logging.getLogger(__name__)

MAX_DISPLAY = 10  # embeds shown inline; Discord allows up to 10 per message


def _build_embed(row: dict) -> discord.Embed:
    location = row["location_raw"] or "Unknown"
    tag = ""
    if row["is_intern"]:
        tag = "🎓 Intern"
    elif row["is_new_grad"]:
        tag = "🆕 New Grad"

    embed = discord.Embed(
        title=f"{row['title']} — {row['company']}",
        url=row["url"],
        color=0x5865F2,
    )
    embed.add_field(name="Location", value=location, inline=True)
    if tag:
        embed.add_field(name="Type", value=tag, inline=True)
    embed.set_footer(text=f"via {row['source']} • ingested {row['ingested_at'][:10]}")
    return embed


def _fmt_csv(val: str) -> str:
    return ", ".join(v.strip() for v in val.split(",") if v.strip())


def _build_filter_str(
    keyword: str | None,
    company: str | None,
    role: str | None,
    discipline: str | None,
    state: str | None,
    season_name: str | None,
) -> str:
    filters: list[str] = []
    if keyword:
        filters.append(f"keyword=**{_fmt_csv(keyword)}**")
    if company:
        filters.append(f"company=**{_fmt_csv(company)}**")
    if role:
        filters.append(f"role=**{_fmt_csv(role)}**")
    if discipline:
        filters.append(f"discipline=**{_fmt_csv(discipline)}**")
    if state:
        filters.append(f"state=**{_fmt_csv(state).upper()}**")
    if season_name:
        filters.append(f"season=**{season_name}**")
    return ", ".join(filters) if filters else "no filters"


class QueryView(discord.ui.View):
    """Paginated view for /query results."""

    def __init__(
        self,
        query_params: dict,
        offset: int,
        has_more: bool,
        filter_str: str,
    ) -> None:
        super().__init__(timeout=180)
        self._params = query_params
        self._offset = offset
        self._filter_str = filter_str
        if not has_more:
            self.next_page.disabled = True

    @discord.ui.button(label="Next →", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        new_offset = self._offset + MAX_DISPLAY
        rows = await db.query_jobs(**self._params, offset=new_offset, limit=MAX_DISPLAY + 1)
        has_more = len(rows) > MAX_DISPLAY
        rows = rows[:MAX_DISPLAY]

        if not rows:
            await interaction.response.edit_message(
                content="No more results.", embeds=[], view=None
            )
            return

        embeds = [_build_embed(r) for r in rows]
        page = new_offset // MAX_DISPLAY + 1
        header = f"Page {page} — {len(rows)} result(s) for {self._filter_str}:"

        new_view = QueryView(self._params, new_offset, has_more, self._filter_str)
        await interaction.response.edit_message(content=header, embeds=embeds, view=new_view)


def _build_scout_embed(job: Job) -> discord.Embed:
    is_intern, is_new_grad = classify_job(job)
    tag = ""
    if is_intern:
        tag = "Intern"
    elif is_new_grad:
        tag = "New Grad"

    embed = discord.Embed(
        title=f"{job.title} — {job.company}",
        url=job.url,
        color=0x5865F2,
    )
    embed.add_field(name="Location", value=job.location or "Unknown", inline=True)
    if tag:
        embed.add_field(name="Type", value=tag, inline=True)
    embed.set_footer(text=f"via {job.source} • live scrape")
    return embed


def register(tree: app_commands.CommandTree) -> None:
    """Register all slash commands onto the given CommandTree."""

    @tree.command(name="query", description="Search the jobs database")
    @app_commands.describe(
        keyword="Title or description keyword(s), comma-separated for OR (e.g. 'Python,React')",
        company="Company slug(s), comma-separated for OR (e.g. 'stripe,ramp')",
        role="Role type(s): intern, new_grad, all — comma-separated for OR",
        discipline="Discipline(s): swe, ee — comma-separated for OR (e.g. 'swe,ee')",
        state="US state(s), comma-separated for OR (e.g. 'CO,WA')",
        season="Start season: summer, fall, spring, winter",
    )
    @app_commands.choices(
        season=[
            app_commands.Choice(name="Summer", value="summer"),
            app_commands.Choice(name="Fall", value="fall"),
            app_commands.Choice(name="Spring", value="spring"),
            app_commands.Choice(name="Winter", value="winter"),
        ],
    )
    async def query(
        interaction: discord.Interaction,
        keyword: str | None = None,
        company: str | None = None,
        role: str | None = None,
        discipline: str | None = None,
        state: str | None = None,
        season: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer()

        season_value = season.value if season else None
        query_params = dict(
            keyword=keyword,
            company=company,
            role=role,
            discipline=discipline,
            state=state,
            season=season_value,
        )

        rows = await db.query_jobs(**query_params, limit=MAX_DISPLAY + 1)
        has_more = len(rows) > MAX_DISPLAY
        rows = rows[:MAX_DISPLAY]

        if not rows:
            await interaction.followup.send("No matching jobs found. Try broadening your search.")
            return

        embeds = [_build_embed(r) for r in rows]
        season_name = season.name if season else None
        filter_str = _build_filter_str(keyword, company, role, discipline, state, season_name)
        header = f"Showing {len(rows)} result(s) for {filter_str}:"

        view = QueryView(query_params, offset=0, has_more=has_more, filter_str=filter_str)
        await interaction.followup.send(content=header, embeds=embeds, view=view)
        logger.info(
            "Query from %s: keyword=%r company=%r role=%r discipline=%r state=%r season=%r → %d results (has_more=%s)",  # noqa: E501
            interaction.user,
            keyword,
            company,
            role,
            discipline,
            state,
            season_value,
            len(rows),
            has_more,
        )

    @tree.command(
        name="scout",
        description="Live-scrape a company+platform to spot-check before adding to config",
    )
    @app_commands.describe(
        company="Company slug (e.g. 'stripe', 'ramp')",
        platform="ATS platform to scrape",
    )
    @app_commands.choices(
        platform=[
            app_commands.Choice(name="Greenhouse", value="greenhouse"),
            app_commands.Choice(name="Lever", value="lever"),
            app_commands.Choice(name="Ashby", value="ashby"),
        ]
    )
    async def scout(
        interaction: discord.Interaction,
        company: str,
        platform: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer()

        slug = company.strip().lower()
        async with httpx.AsyncClient(timeout=20) as client:
            if platform.value == "greenhouse":
                jobs = await greenhouse.scrape(slug, client)
            elif platform.value == "lever":
                jobs = await lever.scrape(slug, client)
            else:
                jobs = await ashby.scrape(slug, client)

        if not jobs:
            await interaction.followup.send(
                f"No jobs found for **{slug}** on **{platform.name}**. "
                "Check the slug or try another platform."
            )
            return

        tech_jobs = [j for j in jobs if is_tech_job(j)]
        matching = [j for j in tech_jobs if passes_filter(j)]

        summary = (
            f"**{slug}** on **{platform.name}**: "
            f"{len(jobs)} total → {len(tech_jobs)} tech → {len(matching)} pass filter"
        )

        if not matching:
            await interaction.followup.send(f"{summary}\n\nNo entry-level/intern roles found.")
            return

        display = matching[:MAX_DISPLAY]
        embeds = [_build_scout_embed(j) for j in display]
        footer = (
            f"\n*(showing {len(display)} of {len(matching)})*"
            if len(matching) > MAX_DISPLAY
            else ""
        )

        await interaction.followup.send(content=f"{summary}{footer}", embeds=embeds)
        logger.info(
            "Scout from %s: company=%r platform=%r → %d total, %d tech, %d matching",
            interaction.user,
            slug,
            platform.value,
            len(jobs),
            len(tech_jobs),
            len(matching),
        )

    @tree.command(name="health", description="Show scraper health and failure counts")
    async def health(interaction: discord.Interaction) -> None:
        threshold = scheduler._FAILURE_ALERT_THRESHOLD
        failures = scheduler._scraper_failures

        lines: list[str] = []
        any_degraded = False
        for scraper, count in failures.items():
            if count == 0:
                icon = "🟢"
            elif count < threshold:
                icon = "🟡"
                any_degraded = True
            else:
                icon = "🔴"
                any_degraded = True
            lines.append(f"{icon} **{scraper}** — {count} consecutive failure(s)")

        color = discord.Color.red() if any_degraded else discord.Color.green()
        embed = discord.Embed(title="Scraper health", color=color)
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Alert threshold: {threshold} consecutive failures")
        await interaction.response.send_message(embed=embed)
