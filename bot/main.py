from __future__ import annotations

import asyncio
import logging

import discord

from bot.config import settings
from bot.db import init_db
from bot.scheduler import (
    poll_ashby,
    poll_greenhouse,
    poll_lever,
    poll_simplify,
    set_channel,
    start_scheduler,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
bot = discord.Client(intents=intents)


@bot.event
async def on_ready() -> None:
    logger.info("Logged in as %s", bot.user)

    channel = bot.get_channel(settings.discord_channel_id)
    if channel is None:
        logger.error("Channel %d not found — exiting", settings.discord_channel_id)
        await bot.close()
        return

    set_channel(channel)  # type: ignore[arg-type]

    logger.info("Initializing database...")
    await init_db()

    # Run all scrapers once on startup
    logger.info("Running initial scrape...")
    await asyncio.gather(
        poll_greenhouse(),
        poll_lever(),
        poll_ashby(),
        poll_simplify(),
    )

    # Then start the recurring scheduler
    start_scheduler()
    logger.info("Bot is running. Polling for jobs.")


def main() -> None:
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
