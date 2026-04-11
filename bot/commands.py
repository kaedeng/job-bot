from __future__ import annotations

import logging

import discord
from discord import app_commands

from bot import db

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


def register(tree: app_commands.CommandTree) -> None:
    """Register all slash commands onto the given CommandTree."""

    @tree.command(name="query", description="Search the jobs database")
    @app_commands.describe(
        keyword="Word or phrase to search in job titles (e.g. 'backend', 'fpga')",
        company="Company slug to filter by (e.g. 'stripe', 'ramp')",
        role="Filter by role type (default: intern + new grad only)",
        discipline="Filter by engineering discipline",
        state="US state abbreviation to filter by (e.g. 'CA', 'NY')",
    )
    @app_commands.choices(
        role=[
            app_commands.Choice(name="Internship", value="intern"),
            app_commands.Choice(name="New Grad / Entry Level", value="new_grad"),
            app_commands.Choice(name="All Roles", value="all"),
        ],
        discipline=[
            app_commands.Choice(name="Software Engineering", value="swe"),
            app_commands.Choice(name="Electrical / Hardware Engineering", value="ee"),
        ],
    )
    async def query(
        interaction: discord.Interaction,
        keyword: str | None = None,
        company: str | None = None,
        role: app_commands.Choice[str] | None = None,
        discipline: app_commands.Choice[str] | None = None,
        state: str | None = None,
    ) -> None:
        await interaction.response.defer()

        role_value = role.value if role else None
        discipline_value = discipline.value if discipline else None

        rows = await db.query_jobs(
            keyword=keyword,
            company=company,
            role=role_value,
            discipline=discipline_value,
            state=state,
            limit=MAX_DISPLAY,
        )

        if not rows:
            await interaction.followup.send("No matching jobs found. Try broadening your search.")
            return

        embeds = [_build_embed(r) for r in rows]

        filters: list[str] = []
        if keyword:
            filters.append(f"keyword=**{keyword}**")
        if company:
            filters.append(f"company=**{company}**")
        if role:
            filters.append(f"role=**{role.name}**")
        if discipline:
            filters.append(f"discipline=**{discipline.name}**")
        if state:
            filters.append(f"state=**{state.upper()}**")

        filter_str = ", ".join(filters) if filters else "no filters"
        header = f"Showing {len(rows)} result(s) for {filter_str}:"

        await interaction.followup.send(content=header, embeds=embeds)
        logger.info(
            "Query from %s: keyword=%r company=%r role=%r discipline=%r state=%r → %d results",
            interaction.user,
            keyword,
            company,
            role_value,
            discipline_value,
            state,
            len(rows),
        )
