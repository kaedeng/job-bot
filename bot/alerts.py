from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import discord

from bot import db

logger = logging.getLogger(__name__)

_HM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")  # HH:MM validation

_INTERVAL_OPTIONS = [
    discord.SelectOption(label="1 minute (testing)", value="1"),
    discord.SelectOption(label="Every 30 minutes", value="30"),
    discord.SelectOption(label="Every hour", value="60"),
    discord.SelectOption(label="Every 2 hours", value="120"),
    discord.SelectOption(label="Every 4 hours", value="240"),
    discord.SelectOption(label="Every 8 hours", value="480"),
    discord.SelectOption(label="Every 12 hours", value="720"),
    discord.SelectOption(label="Once a day", value="1440"),
]

_TOTAL_STEPS = 6  # shown in step headers
_STEP4_CONTENT = "**Step 4 of 6 — Alert Interval**\nHow often should I check for new matching jobs?"


@dataclass
class _AlertSetup:
    """Accumulates user choices through the wizard steps."""

    role_types: list[str] = field(default_factory=list)  # "intern", "new_grad"
    disciplines: list[str] = field(default_factory=list)  # "swe","ee"; empty = both
    location_scope: str = "us"  # "us","remote","state","country:<CC>","worldwide"
    states: list[str] = field(default_factory=list)  # e.g. ["CO","WA"]
    country_code: str = ""  # e.g. "GB" for non-US
    interval_minutes: int = 60
    keywords: list[str] = field(default_factory=list)  # optional title/desc substrings
    companies: list[str] = field(default_factory=list)  # optional company slugs
    quiet_hours_start: str | None = None  # "HH:MM" UTC
    quiet_hours_end: str | None = None  # "HH:MM" UTC


# ─── Step 1: Role types ────────────────────────────────────────────────────────


class _Step1View(discord.ui.View):
    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__(timeout=300)
        self._setup = setup

    @discord.ui.select(
        placeholder="Select one or both...",
        min_values=1,
        max_values=2,
        options=[
            discord.SelectOption(label="Internships", value="intern", emoji="🎓"),
            discord.SelectOption(label="New Grad / Entry Level", value="new_grad", emoji="🆕"),
        ],
    )
    async def role_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        self._setup.role_types = list(select.values)
        await interaction.response.edit_message(
            content=_header(2, "Discipline", "Which engineering discipline are you targeting?"),
            view=_Step2View(self._setup),
        )


# ─── Step 2: Discipline ────────────────────────────────────────────────────────


class _Step2View(discord.ui.View):
    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__(timeout=300)
        self._setup = setup

    @discord.ui.select(
        placeholder="Select one or both...",
        min_values=1,
        max_values=2,
        options=[
            discord.SelectOption(label="Software Engineering (SWE)", value="swe", emoji="💻"),
            discord.SelectOption(label="Electrical Engineering (EE)", value="ee", emoji="⚡"),
        ],
    )
    async def discipline_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        vals = list(select.values)
        self._setup.disciplines = [] if set(vals) == {"swe", "ee"} else vals
        await interaction.response.edit_message(
            content=_header(3, "Location", "Where do you want to look for jobs?"),
            view=_Step3View(self._setup),
        )


# ─── Step 3: Location ─────────────────────────────────────────────────────────


class _Step3View(discord.ui.View):
    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__(timeout=300)
        self._setup = setup

    @discord.ui.select(
        placeholder="Select location scope...",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Anywhere in the US", value="us", emoji="🇺🇸"),
            discord.SelectOption(label="Remote only", value="remote", emoji="🏠"),
            discord.SelectOption(
                label="Specific US state(s) — e.g. CO, WA", value="state", emoji="📍"
            ),
            discord.SelectOption(
                label="Specific country (non-US) — enter ISO code", value="country", emoji="🌍"
            ),
            discord.SelectOption(
                label="Anywhere worldwide (no location filter)", value="worldwide", emoji="🌐"
            ),
        ],
    )
    async def location_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        value = select.values[0]
        if value == "state":
            await interaction.response.send_modal(_StateModal(self._setup))
        elif value == "country":
            await interaction.response.send_modal(_CountryModal(self._setup))
        else:
            self._setup.location_scope = value
            await interaction.response.edit_message(
                content=_STEP4_CONTENT,
                view=_Step4View(self._setup),
            )


class _StateModal(discord.ui.Modal, title="Enter US State(s)"):
    states_input: discord.ui.TextInput = discord.ui.TextInput(
        label="State abbreviation(s), comma-separated",
        placeholder="e.g. CO, WA, CA",
        required=True,
        max_length=200,
    )

    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__()
        self._setup = setup

    async def on_submit(self, interaction: discord.Interaction) -> None:
        states = [s.strip().upper() for s in self.states_input.value.split(",") if s.strip()]
        if not states:
            await interaction.response.send_message(
                "No valid states entered — please try again.", ephemeral=True
            )
            return
        self._setup.states = states
        self._setup.location_scope = "state"
        await interaction.response.edit_message(
            content=_header(4, "Alert Interval", "How often should I check for new matching jobs?"),
            view=_Step4View(self._setup),
        )


class _CountryModal(discord.ui.Modal, title="Enter Country Code"):
    country_input: discord.ui.TextInput = discord.ui.TextInput(
        label="ISO 3166-1 alpha-2 country code",
        placeholder="e.g. GB, DE, CA, AU",
        required=True,
        min_length=2,
        max_length=2,
    )

    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__()
        self._setup = setup

    async def on_submit(self, interaction: discord.Interaction) -> None:
        code = self.country_input.value.strip().upper()
        self._setup.country_code = code
        self._setup.location_scope = "country"
        await interaction.response.edit_message(
            content=_header(4, "Alert Interval", "How often should I check for new matching jobs?"),
            view=_Step4View(self._setup),
        )


# ─── Step 4: Interval ─────────────────────────────────────────────────────────


class _Step4View(discord.ui.View):
    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__(timeout=300)
        self._setup = setup

    @discord.ui.select(
        placeholder="Select check frequency...",
        min_values=1,
        max_values=1,
        options=_INTERVAL_OPTIONS,
    )
    async def interval_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        self._setup.interval_minutes = int(select.values[0])
        await interaction.response.edit_message(
            content=_header(
                5,
                "Optional filters",
                "Want to narrow down by keyword or company? You can skip this.",
            ),
            view=_Step5View(self._setup),
        )


# ─── Step 5: Optional keyword / company filters ───────────────────────────────


class _Step5View(discord.ui.View):
    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__(timeout=300)
        self._setup = setup

    @discord.ui.button(label="Add keyword / company filters", style=discord.ButtonStyle.primary)
    async def add_filters(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(_FiltersModal(self._setup))

    @discord.ui.button(label="Skip →", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=_header(
                6,
                "Quiet hours (UTC)",
                "Want to pause alerts during certain hours? You can skip this.",
            ),
            view=_Step6View(self._setup),
        )


class _FiltersModal(discord.ui.Modal, title="Optional filters"):
    keywords_input: discord.ui.TextInput = discord.ui.TextInput(
        label="Keywords (matches title & description)",
        placeholder="e.g. rust, kubernetes, react",
        required=False,
        max_length=300,
    )
    companies_input: discord.ui.TextInput = discord.ui.TextInput(
        label="Companies (slugs/names, comma-separated)",
        placeholder="e.g. stripe, ramp, anthropic",
        required=False,
        max_length=300,
    )

    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__()
        self._setup = setup

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self._setup.keywords = [
            k.strip().lower() for k in self.keywords_input.value.split(",") if k.strip()
        ]
        self._setup.companies = [
            c.strip().lower() for c in self.companies_input.value.split(",") if c.strip()
        ]
        await interaction.response.edit_message(
            content=_header(
                6,
                "Quiet hours (UTC)",
                "Want to pause alerts during certain hours? You can skip this.",
            ),
            view=_Step6View(self._setup),
        )


# ─── Step 6: Optional quiet hours ────────────────────────────────────────────


class _Step6View(discord.ui.View):
    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__(timeout=300)
        self._setup = setup

    @discord.ui.button(label="Set quiet hours (UTC)", style=discord.ButtonStyle.primary)
    async def set_quiet(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(_QuietHoursModal(self._setup))

    @discord.ui.button(label="Skip →", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content=_build_summary(self._setup),
            view=_ConfirmView(self._setup),
        )


class _QuietHoursModal(discord.ui.Modal, title="Set quiet hours (UTC)"):
    start_input: discord.ui.TextInput = discord.ui.TextInput(
        label="Start time (UTC 24h, e.g. 22:00)",
        placeholder="22:00",
        required=True,
        min_length=5,
        max_length=5,
    )
    end_input: discord.ui.TextInput = discord.ui.TextInput(
        label="End time (UTC 24h, e.g. 08:00)",
        placeholder="08:00",
        required=True,
        min_length=5,
        max_length=5,
    )

    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__()
        self._setup = setup

    async def on_submit(self, interaction: discord.Interaction) -> None:
        start = self.start_input.value.strip()
        end = self.end_input.value.strip()
        if not _HM_RE.match(start) or not _HM_RE.match(end):
            await interaction.response.send_message(
                "Invalid time format — use HH:MM (e.g. `22:00`). Please try again.",
                ephemeral=True,
            )
            return
        if start == end:
            await interaction.response.send_message(
                "Start and end can't be the same time. Please try again.",
                ephemeral=True,
            )
            return
        self._setup.quiet_hours_start = start
        self._setup.quiet_hours_end = end
        await interaction.response.edit_message(
            content=_build_summary(self._setup),
            view=_ConfirmView(self._setup),
        )


# ─── Confirm ──────────────────────────────────────────────────────────────────


class _ConfirmView(discord.ui.View):
    def __init__(self, setup: _AlertSetup) -> None:
        super().__init__(timeout=300)
        self._setup = setup

    @discord.ui.button(label="Confirm ✓", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        user_id = str(interaction.user.id)
        await _save_preferences(user_id, self._setup)
        await interaction.response.edit_message(
            content=(
                "**Alerts are set up!** I'll DM you matching jobs on your schedule.\n"
                "Use `/alert-off` to pause, `/alert-resume` to re-enable, "
                "or `/alert` to change preferences."
            ),
            view=None,
        )
        logger.info(
            "Alert preferences saved for user %s: roles=%s disc=%s loc=%s states=%s "
            "country=%s interval=%d kw=%s companies=%s quiet=%s-%s",
            user_id,
            self._setup.role_types,
            self._setup.disciplines,
            self._setup.location_scope,
            self._setup.states,
            self._setup.country_code,
            self._setup.interval_minutes,
            self._setup.keywords,
            self._setup.companies,
            self._setup.quiet_hours_start,
            self._setup.quiet_hours_end,
        )

    @discord.ui.button(label="Cancel ✗", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content="Alert setup cancelled. Run `/alert` any time to start over.",
            view=None,
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _header(step: int, title: str, body: str) -> str:
    return f"**Step {step} of {_TOTAL_STEPS} — {title}**\n{body}"


def _loc_display(setup: _AlertSetup) -> str:
    if setup.location_scope == "us":
        return "Anywhere in the US"
    if setup.location_scope == "remote":
        return "Remote only"
    if setup.location_scope == "state":
        return "State(s): " + ", ".join(setup.states)
    if setup.location_scope == "country":
        return f"Country: {setup.country_code}"
    return "Anywhere worldwide"


def _interval_display(mins: int) -> str:
    if mins == 1:
        return "1 minute (testing)"
    if mins < 60:
        return f"every {mins} minutes"
    if mins == 60:
        return "every hour"
    if mins < 1440:
        return f"every {mins // 60} hours"
    return "once a day"


def _build_summary(setup: _AlertSetup) -> str:
    role_str = " + ".join(
        "Internships" if r == "intern" else "New Grad / Entry Level" for r in setup.role_types
    )
    disc_str = (
        "SWE + EE (all)"
        if not setup.disciplines
        else " + ".join(d.upper() for d in setup.disciplines)
    )
    lines = [
        "**Confirm your alert settings:**\n",
        f"**Roles:** {role_str}",
        f"**Discipline:** {disc_str}",
        f"**Location:** {_loc_display(setup)}",
        f"**Check interval:** {_interval_display(setup.interval_minutes)}",
    ]
    if setup.keywords:
        lines.append(f"**Keywords:** {', '.join(setup.keywords)}")
    if setup.companies:
        lines.append(f"**Companies:** {', '.join(setup.companies)}")
    if setup.quiet_hours_start:
        lines.append(f"**Quiet hours (UTC):** {setup.quiet_hours_start} – {setup.quiet_hours_end}")
    lines.append("\n*Confirm to save, or Cancel to discard.*")
    return "\n".join(lines)


async def _save_preferences(user_id: str, setup: _AlertSetup) -> None:
    """Persist wizard results to user_preferences + user_filter_rules."""
    await db.upsert_user_prefs(
        user_id,
        dm_enabled=1,
        alert_interval_minutes=setup.interval_minutes,
        disciplines=setup.disciplines,
        keywords=setup.keywords,
        companies=setup.companies,
        quiet_hours_start=setup.quiet_hours_start,
        quiet_hours_end=setup.quiet_hours_end,
    )

    # Determine the location_scope string for the DB
    if setup.location_scope == "state":
        scopes = [f"state:{s}" for s in setup.states]
    elif setup.location_scope == "country":
        scopes = [f"country:{setup.country_code}"]
    else:
        scopes = [setup.location_scope]  # "us", "remote", "worldwide"

    # Replace existing rules wholesale with the new set
    await db.clear_user_filter_rules(user_id)
    for role in setup.role_types:
        for scope in scopes:
            await db.add_user_filter_rule(user_id, role, scope)


def _is_quiet_time(prefs: dict) -> bool:
    """Return True if the current UTC time falls inside the user's quiet window."""
    start = prefs.get("quiet_hours_start")
    end = prefs.get("quiet_hours_end")
    if not start or not end:
        return False
    now = datetime.now(timezone.utc).strftime("%H:%M")
    if start <= end:
        return start <= now < end
    # Crosses midnight: quiet from e.g. 22:00 to 08:00
    return now >= start or now < end


# ─── DM Pagination ────────────────────────────────────────────────────────────

_PAGE_SIZE = 10


class _AlertPageView(discord.ui.View):
    """← Prev / Next → buttons attached to DM alert messages."""

    def __init__(
        self,
        user_id: str,
        ingested_after: str | None,
        offset: int,
        has_more: bool,
    ) -> None:
        super().__init__(timeout=300)
        self._user_id = user_id
        self._ingested_after = ingested_after
        self._offset = offset
        if offset == 0:
            self.prev_page.disabled = True
        if not has_more:
            self.next_page.disabled = True

    async def _go_to(self, interaction: discord.Interaction, new_offset: int) -> None:
        rows = await db.query_jobs_for_user(
            user_id=self._user_id,
            ingested_after=self._ingested_after,
            limit=_PAGE_SIZE + 1,
            offset=new_offset,
        )
        has_more = len(rows) > _PAGE_SIZE
        rows = rows[:_PAGE_SIZE]

        if not rows:
            await interaction.response.edit_message(
                content="No results on this page.", embeds=[], view=None
            )
            return

        embeds = [build_db_row_embed(r) for r in rows]
        page = new_offset // _PAGE_SIZE + 1
        n = len(rows)
        header = f"**Page {page}** — {n} job{'s' if n != 1 else ''} matching your preferences:"
        new_view = _AlertPageView(self._user_id, self._ingested_after, new_offset, has_more)
        await interaction.response.edit_message(content=header, embeds=embeds, view=new_view)

    @discord.ui.button(label="← Prev", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go_to(interaction, max(0, self._offset - _PAGE_SIZE))

    @discord.ui.button(label="Next →", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go_to(interaction, self._offset + _PAGE_SIZE)


# ─── Public API ───────────────────────────────────────────────────────────────


async def start_alert_setup(user: discord.User | discord.Member) -> None:
    """Send the first wizard step as a DM. Raises discord.Forbidden if DMs are off."""
    setup = _AlertSetup()
    await user.send(
        content=_header(1, "Role types", "What types of roles do you want to be alerted about?"),
        view=_Step1View(setup),
    )


def build_db_row_embed(row: dict) -> discord.Embed:
    """Build a Discord embed from a job_postings DB row dict."""
    location = row.get("location_raw") or "Unknown"
    tag = ""
    if row.get("is_intern"):
        tag = "🎓 Intern"
    elif row.get("is_new_grad"):
        tag = "🆕 New Grad"

    embed = discord.Embed(
        title=f"{row['title']} — {row['company']}",
        url=row["url"],
        color=0x5865F2,
    )
    embed.add_field(name="Location", value=location, inline=True)
    if tag:
        embed.add_field(name="Type", value=tag, inline=True)
    embed.set_footer(text=f"via {row['source']} • {row['ingested_at'][:10]}")
    return embed


async def send_user_alerts(bot: discord.Client) -> None:
    """Check all users due for an alert and DM them matching new jobs."""
    due_users = await db.get_users_due_for_alert()
    if not due_users:
        return

    logger.info("Processing alerts for %d user(s)", len(due_users))

    for prefs in due_users:
        user_id = prefs["user_id"]

        # Respect quiet hours — skip without touching last_alerted_at so the
        # interval picks up naturally once quiet hours end.
        if _is_quiet_time(prefs):
            logger.debug("Skipping user %s — in quiet hours", user_id)
            continue

        # New users (no last_alerted_at) get the last 24 h only, to avoid a flood.
        ingested_after: str | None = prefs.get("last_alerted_at")
        if ingested_after is None:
            ingested_after = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        # Tick the clock even when no new jobs found, so the interval resets.
        await db.update_last_alerted(user_id)

        jobs = await db.query_jobs_for_user(
            user_id=user_id,
            ingested_after=ingested_after,
            limit=25,
        )
        if not jobs:
            continue

        try:
            user = await bot.fetch_user(int(user_id))
        except discord.NotFound:
            logger.warning("User %s not found — skipping alert", user_id)
            continue

        count = len(jobs)
        header = f"**{count} new job{'s' if count != 1 else ''}** matching your alert preferences:"
        first_page = jobs[:_PAGE_SIZE]
        has_more = count > _PAGE_SIZE
        embeds = [build_db_row_embed(r) for r in first_page]
        view = _AlertPageView(user_id, ingested_after, offset=0, has_more=has_more)

        try:
            await user.send(content=header, embeds=embeds, view=view)
            logger.info("Sent %d job(s) to user %s (has_more=%s)", count, user_id, has_more)
        except discord.Forbidden:
            logger.warning("Cannot DM user %s (DMs closed) — disabling their alerts", user_id)
            await db.upsert_user_prefs(user_id, dm_enabled=0)
