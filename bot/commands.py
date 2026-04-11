from __future__ import annotations

import logging

import discord
import httpx
from discord import app_commands

from bot import alerts, db, scheduler
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
        if offset == 0:
            self.prev_page.disabled = True
        if not has_more:
            self.next_page.disabled = True

    async def _go_to(self, interaction: discord.Interaction, new_offset: int) -> None:
        rows = await db.query_jobs(**self._params, offset=new_offset, limit=MAX_DISPLAY + 1)
        has_more = len(rows) > MAX_DISPLAY
        rows = rows[:MAX_DISPLAY]

        if not rows:
            await interaction.response.edit_message(
                content="No results on this page.", embeds=[], view=None
            )
            return

        embeds = [_build_embed(r) for r in rows]
        page = new_offset // MAX_DISPLAY + 1
        header = f"Page {page} — {len(rows)} result(s) for {self._filter_str}:"
        new_view = QueryView(self._params, new_offset, has_more, self._filter_str)
        await interaction.response.edit_message(content=header, embeds=embeds, view=new_view)

    @discord.ui.button(label="← Prev", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go_to(interaction, max(0, self._offset - MAX_DISPLAY))

    @discord.ui.button(label="Next →", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go_to(interaction, self._offset + MAX_DISPLAY)


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

    @tree.command(
        name="alert",
        description="Set up personalised job alert DMs — only you can see this",
    )
    async def alert(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Check your DMs — I've sent you the setup wizard!", ephemeral=True
        )
        try:
            await alerts.start_alert_setup(interaction.user)
        except discord.Forbidden:
            await interaction.followup.send(
                "I couldn't DM you. Make sure **Allow direct messages from server members** "
                "is enabled in your Discord Privacy & Safety settings, then try again.",
                ephemeral=True,
            )
        logger.info("Alert setup started for user %s", interaction.user)

    @tree.command(
        name="alert-status",
        description="Show your current job alert preferences — only you can see this",
    )
    async def alert_status(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        prefs = await db.get_user_prefs(user_id)
        rules = await db.get_user_filter_rules(user_id)

        if not prefs or not rules:
            await interaction.followup.send(
                "You don't have any alert preferences set up yet. Run `/alert` to get started.",
                ephemeral=True,
            )
            return

        status = "🟢 Active" if prefs["dm_enabled"] else "🔴 Paused"
        mins = prefs["alert_interval_minutes"]
        if mins < 60:
            interval_str = f"every {mins} minutes"
        elif mins == 60:
            interval_str = "every hour"
        elif mins < 1440:
            interval_str = f"every {mins // 60} hours"
        else:
            interval_str = "once a day"

        disciplines = prefs.get("disciplines") or []
        disc_str = (
            "SWE + EE (all)" if not disciplines else " + ".join(d.upper() for d in disciplines)
        )

        rule_lines = []
        for r in rules:
            loc = r["location_scope"]
            role = "Intern" if r["role_type"] == "intern" else "New Grad"
            rule_lines.append(f"  • {role} — {loc}")

        keywords = prefs.get("keywords") or []
        companies = prefs.get("companies") or []
        qh_start = prefs.get("quiet_hours_start")
        qh_end = prefs.get("quiet_hours_end")

        embed = discord.Embed(title="Your job alert settings", color=0x5865F2)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Check interval", value=interval_str, inline=True)
        embed.add_field(name="Discipline", value=disc_str, inline=True)
        embed.add_field(
            name="Filter rules (OR logic)",
            value="\n".join(rule_lines) or "none",
            inline=False,
        )
        if keywords:
            embed.add_field(name="Keywords", value=", ".join(keywords), inline=False)
        if companies:
            embed.add_field(name="Companies", value=", ".join(companies), inline=False)
        if qh_start and qh_end:
            embed.add_field(name="Quiet hours (UTC)", value=f"{qh_start} – {qh_end}", inline=True)
        if prefs.get("last_alerted_at"):
            embed.set_footer(text=f"Last alert sent: {prefs['last_alerted_at'][:16]} UTC")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tree.command(
        name="alert-off",
        description="Pause your job alert DMs — only you can see this",
    )
    async def alert_off(interaction: discord.Interaction) -> None:
        user_id = str(interaction.user.id)
        prefs = await db.get_user_prefs(user_id)
        if not prefs:
            await interaction.response.send_message(
                "You don't have any alerts set up. Run `/alert` first.",
                ephemeral=True,
            )
            return
        await db.upsert_user_prefs(user_id, dm_enabled=0)
        await interaction.response.send_message(
            "Alerts paused. Run `/alert-resume` to re-enable, or `/alert` to reconfigure.",
            ephemeral=True,
        )
        logger.info("Alerts disabled for user %s", interaction.user)

    @tree.command(
        name="alert-resume",
        description="Re-enable paused job alert DMs — only you can see this",
    )
    async def alert_resume(interaction: discord.Interaction) -> None:
        user_id = str(interaction.user.id)
        prefs = await db.get_user_prefs(user_id)
        if not prefs:
            await interaction.response.send_message(
                "You don't have any alerts set up yet. Run `/alert` to get started.",
                ephemeral=True,
            )
            return
        rules = await db.get_user_filter_rules(user_id)
        if not rules:
            await interaction.response.send_message(
                "No filter rules found. Run `/alert` to set up your preferences.",
                ephemeral=True,
            )
            return
        if prefs["dm_enabled"]:
            await interaction.response.send_message(
                "Your alerts are already active. Use `/alert-status` to review them.",
                ephemeral=True,
            )
            return
        await db.upsert_user_prefs(user_id, dm_enabled=1)
        await interaction.response.send_message(
            "Alerts re-enabled! I'll DM you matching jobs on your previous schedule.",
            ephemeral=True,
        )
        logger.info("Alerts re-enabled for user %s", interaction.user)

    @tree.command(
        name="alert-test",
        description="Immediately trigger your job alert DM to test delivery — only you see this",
    )
    async def alert_test(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        prefs = await db.get_user_prefs(user_id)
        rules = await db.get_user_filter_rules(user_id)

        if not prefs or not rules:
            await interaction.followup.send(
                "No alert preferences found. Run `/alert` first.", ephemeral=True
            )
            return

        jobs = await db.query_jobs_for_user(user_id=user_id, ingested_after=None, limit=25)
        if not jobs:
            await interaction.followup.send(
                "Query ran but found **0 matching jobs** (all time). "
                "Check your filter rules with `/alert-status`.",
                ephemeral=True,
            )
            return

        try:
            count = len(jobs)
            first_page = jobs[:10]
            has_more = count > 10
            embeds = [alerts.build_db_row_embed(r) for r in first_page]
            header = (
                f"**[Test alert] {count} job{'s' if count != 1 else ''}** "
                "matching your preferences:"
            )
            view = alerts._AlertPageView(user_id, ingested_after=None, offset=0, has_more=has_more)
            await interaction.user.send(content=header, embeds=embeds, view=view)
            await interaction.followup.send(
                f"Test DM sent! Found **{count} job(s)** matching your preferences.",
                ephemeral=True,
            )
            logger.info("Test alert sent to user %s: %d job(s)", interaction.user, count)
        except discord.Forbidden:
            await interaction.followup.send(
                "Could not send you a DM. Make sure **Allow direct messages from server members** "
                "is enabled in Discord Privacy & Safety settings.",
                ephemeral=True,
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
