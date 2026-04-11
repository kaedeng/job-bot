from __future__ import annotations

import logging

import discord

from bot.models import Job

logger = logging.getLogger(__name__)

MAX_EMBEDS_PER_MESSAGE = 10  # Discord limit


def _build_embed(job: Job) -> discord.Embed:
    embed = discord.Embed(
        title=f"{job.title} — {job.company}",
        url=job.url,
        description=f"📍 {job.location}",
        color=0x5865F2,
    )
    return embed


async def notify(jobs: list[Job], channel: discord.TextChannel) -> None:
    if not jobs:
        return

    for i in range(0, len(jobs), MAX_EMBEDS_PER_MESSAGE):
        batch = jobs[i : i + MAX_EMBEDS_PER_MESSAGE]
        embeds = [_build_embed(j) for j in batch]
        try:
            await channel.send(embeds=embeds)
        except discord.HTTPException as e:
            logger.error("Failed to send to Discord: %s", e)
