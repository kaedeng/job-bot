from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
import httpx
from discord import app_commands

from bot import alerts, db, scheduler
from bot.company_names import search_by_slug
from bot.filters import classify_job, is_tech_job, passes_filter
from bot.models import Job
from bot.scrapers import ashby, greenhouse, lever

# Lookup for /scout platform dispatch
_PLATFORM_SCRAPERS = {
    "greenhouse": greenhouse.scrape,
    "lever": lever.scrape,
    "ashby": ashby.scrape,
}

logger = logging.getLogger(__name__)

MAX_DISPLAY = 10  # embeds shown inline; Discord allows up to 10 per message


_SINCE_HOURS: dict[str, int] = {
    "24h": 24,
    "3d": 72,
    "7d": 168,
    "14d": 336,
    "30d": 720,
}


def _since_to_ingested_after(since_value: str) -> str:
    hours = _SINCE_HOURS[since_value]
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_csv(val: str) -> str:
    return ", ".join(v.strip() for v in val.split(",") if v.strip())


def _build_filter_str(
    keyword: str | None,
    company: str | None,
    role: str | None,
    discipline: str | None,
    state: str | None,
    season_name: str | None,
    since_name: str | None = None,
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
    if since_name:
        filters.append(f"since=**{since_name}**")
    return ", ".join(filters) if filters else "no filters"


class _CompanySelect(discord.ui.Select):
    """Multi-select for filtering query results by company."""

    def __init__(self, all_companies: list[str], selected: list[str]) -> None:
        selected_lower = {s.lower() for s in selected}
        options = [
            discord.SelectOption(label=c, value=c, default=(c.lower() in selected_lower))
            for c in all_companies
        ]
        super().__init__(
            placeholder="Filter by company — leave empty to show all",
            min_values=0,
            max_values=len(options),
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: QueryView = self.view  # type: ignore[assignment]
        view._selected_companies = list(self.values)
        await view._refresh(interaction, offset=0)


class QueryView(discord.ui.View):
    """Paginated view for /query results with company multi-select."""

    def __init__(
        self,
        query_params: dict,
        offset: int,
        has_more: bool,
        filter_str: str,
        all_companies: list[str],
        selected_companies: list[str],
    ) -> None:
        super().__init__(timeout=180)
        self._params = query_params
        self._offset = offset
        self._filter_str = filter_str
        self._all_companies = all_companies
        self._selected_companies = selected_companies

        if all_companies:
            self.add_item(_CompanySelect(all_companies, selected_companies))

        if offset == 0:
            self.prev_page.disabled = True
        if not has_more:
            self.next_page.disabled = True
        if not selected_companies:
            self.clear_companies.disabled = True

    def _header(self, n: int, offset: int) -> str:
        page = offset // MAX_DISPLAY + 1
        co = (
            f", companies=**{', '.join(self._selected_companies)}**"
            if self._selected_companies
            else ""
        )
        return f"Page {page} — {n} result(s) for {self._filter_str}{co}:"

    async def _refresh(self, interaction: discord.Interaction, offset: int) -> None:
        rows = await db.query_jobs(
            **self._params,
            company=self._selected_companies or None,
            offset=offset,
            limit=MAX_DISPLAY + 1,
        )
        has_more = len(rows) > MAX_DISPLAY
        rows = rows[:MAX_DISPLAY]

        if not rows:
            await interaction.response.edit_message(
                content="No results found for the selected filters.", embeds=[], view=None
            )
            return

        embeds = [alerts.build_db_row_embed(r) for r in rows]
        new_view = QueryView(
            self._params, offset, has_more, self._filter_str,
            self._all_companies, self._selected_companies,
        )
        await interaction.response.edit_message(
            content=new_view._header(len(rows), offset), embeds=embeds, view=new_view
        )

    @discord.ui.button(label="← Prev", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._refresh(interaction, max(0, self._offset - MAX_DISPLAY))

    @discord.ui.button(label="Next →", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._refresh(interaction, self._offset + MAX_DISPLAY)

    @discord.ui.button(label="Select All", style=discord.ButtonStyle.primary, row=1)
    async def select_all_companies(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._selected_companies = list(self._all_companies)
        await self._refresh(interaction, 0)

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.danger, row=1)
    async def clear_companies(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._selected_companies = []
        await self._refresh(interaction, 0)


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


async def _keyword_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    parts = [p.strip() for p in current.split(",")]
    prefix = parts[-1].lower()
    already = ", ".join(p for p in parts[:-1] if p)

    keywords = await db.search_keywords(prefix)
    choices = []
    for k in keywords[:25]:
        value = f"{already}, {k}" if already else k
        value = value[:100]
        choices.append(app_commands.Choice(name=value, value=value))
    return choices


async def _company_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    # Autocomplete only the last comma-separated token; carry the rest forward
    parts = [p.strip() for p in current.split(",")]
    prefix = parts[-1]
    already = ", ".join(p for p in parts[:-1] if p)

    # Merge DB results (by display name) with slug-based matches, deduplicated
    db_results = await db.search_companies(prefix)
    slug_results = search_by_slug(prefix)
    seen: set[str] = set()
    merged: list[str] = []
    for c in db_results + slug_results:
        if c.lower() not in seen:
            seen.add(c.lower())
            merged.append(c)

    choices = []
    for c in merged[:25]:
        value = f"{already}, {c}" if already else c
        value = value[:100]  # Discord Choice limit
        choices.append(app_commands.Choice(name=value, value=value))
    return choices


def register(tree: app_commands.CommandTree) -> None:
    """Register all slash commands onto the given CommandTree."""

    @tree.command(name="query", description="Search the jobs database")
    @app_commands.describe(
        keyword="Title or description keyword(s), comma-separated for OR (e.g. 'Python,React')",
        company="Company name — start typing to search (autocomplete)",
        role="Role type(s): intern, new_grad, all — comma-separated for OR",
        discipline="Discipline(s): swe, ee, chem, unknown - comma-separated for OR",
        state="US state(s), comma-separated for OR (e.g. 'CO,WA')",
        season="Start season: summer, fall, spring, winter",
        since="Only show jobs posted/ingested within this window",
    )
    @app_commands.choices(
        season=[
            app_commands.Choice(name="Summer", value="summer"),
            app_commands.Choice(name="Fall", value="fall"),
            app_commands.Choice(name="Spring", value="spring"),
            app_commands.Choice(name="Winter", value="winter"),
        ],
        since=[
            app_commands.Choice(name="Last 24 hours", value="24h"),
            app_commands.Choice(name="Last 3 days", value="3d"),
            app_commands.Choice(name="Last 7 days", value="7d"),
            app_commands.Choice(name="Last 14 days", value="14d"),
            app_commands.Choice(name="Last 30 days", value="30d"),
        ],
    )
    @app_commands.autocomplete(keyword=_keyword_autocomplete, company=_company_autocomplete)
    async def query(
        interaction: discord.Interaction,
        keyword: str | None = None,
        company: str | None = None,
        role: str | None = None,
        discipline: str | None = None,
        state: str | None = None,
        season: app_commands.Choice[str] | None = None,
        since: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer()

        season_value = season.value if season else None
        ingested_after = _since_to_ingested_after(since.value) if since else None
        initial_companies = [c.strip() for c in company.split(",") if c.strip()] if company else []

        # company filter lives in view state; pass it separately to db.query_jobs
        query_params = dict(
            keyword=keyword,
            role=role,
            discipline=discipline,
            state=state,
            season=season_value,
            ingested_after=ingested_after,
        )

        parsed_keywords = (
            [k.strip().lower() for k in keyword.split(",") if k.strip()] if keyword else []
        )

        all_companies, rows, _ = await asyncio.gather(
            db.get_companies_for_query(**query_params),
            db.query_jobs(**query_params, company=initial_companies or None, limit=MAX_DISPLAY + 1),
            db.increment_keyword_stats(parsed_keywords),
        )

        has_more = len(rows) > MAX_DISPLAY
        rows = rows[:MAX_DISPLAY]

        if not rows:
            await interaction.followup.send("No matching jobs found. Try broadening your search.")
            return

        embeds = [alerts.build_db_row_embed(r) for r in rows]
        season_name = season.name if season else None
        since_name = since.name if since else None
        filter_str = _build_filter_str(
            keyword, company, role, discipline, state, season_name, since_name
        )
        header = f"Showing {len(rows)} result(s) for {filter_str}:"

        view = QueryView(
            query_params,
            offset=0,
            has_more=has_more,
            filter_str=filter_str,
            all_companies=all_companies,
            selected_companies=initial_companies,
        )
        await interaction.followup.send(content=header, embeds=embeds, view=view)
        logger.info(
            "Query from %s: keyword=%r company=%r role=%r discipline=%r state=%r season=%r since=%r → %d results (has_more=%s)",  # noqa: E501
            interaction.user,
            keyword,
            company,
            role,
            discipline,
            state,
            season_value,
            since.value if since else None,
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
        scrape_fn = _PLATFORM_SCRAPERS[platform.value]
        async with httpx.AsyncClient(timeout=20) as client:
            jobs = await scrape_fn(slug, client)

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
    @app_commands.describe(
        keyword="Keyword(s) to filter by — start typing to search, comma-separate for multiple",
        company="Company name(s) to watch — start typing to search, comma-separate for multiple",
    )
    @app_commands.autocomplete(keyword=_keyword_autocomplete, company=_company_autocomplete)
    async def alert(
        interaction: discord.Interaction,
        keyword: str | None = None,
        company: str | None = None,
    ) -> None:
        user_id = str(interaction.user.id)
        companies = [c.strip() for c in company.split(",") if c.strip()] if company else []
        keywords = [k.strip().lower() for k in keyword.split(",") if k.strip()] if keyword else []

        # Fetch existing prefs to show the user what they currently have
        prefs = await db.get_user_prefs(user_id)
        existing_keywords = prefs.get("keywords") or [] if prefs else []
        existing_companies = prefs.get("companies") or [] if prefs else []

        lines = ["Check your DMs — I've sent you the setup wizard!"]
        if existing_keywords or existing_companies:
            lines.append("")
            lines.append("**Your current filters:**")
            if existing_keywords:
                lines.append(f"Keywords: {', '.join(existing_keywords)}")
            if existing_companies:
                lines.append(f"Companies: {', '.join(existing_companies)}")
            lines.append("*(these will be pre-filled in the wizard)*")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

        # Pre-populate wizard with slash command values; fall back to existing prefs
        init_keywords = keywords or existing_keywords or None
        init_companies = companies or existing_companies or None

        try:
            await alerts.start_alert_setup(
                interaction.user,
                companies=init_companies,
                keywords=init_keywords,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I couldn't DM you. Make sure **Allow direct messages from server members** "
                "is enabled in your Discord Privacy & Safety settings, then try again.",
                ephemeral=True,
            )
        logger.info(
            "Alert setup started for user %s (companies=%r keywords=%r)",
            interaction.user, init_companies, init_keywords,
        )

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
        interval_str = alerts.interval_display(prefs["alert_interval_minutes"])

        disciplines = prefs.get("disciplines") or []
        disc_label = {"swe": "SWE", "ee": "EE", "chem": "ChemE", "unknown": "Unknown"}
        disc_str = (
            "SWE + EE + ChemE + Unknown (all)"
            if not disciplines
            else " + ".join(disc_label.get(d, d.upper()) for d in disciplines)
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
        threshold = scheduler.get_failure_threshold()
        failures = scheduler.get_health_status()

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

