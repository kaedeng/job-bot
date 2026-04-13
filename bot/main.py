from __future__ import annotations

import argparse
import logging
import os

# Parse args and set ENV_FILE *before* any bot imports so config.py
# reads the correct env file when it initializes at import time.
_parser = argparse.ArgumentParser(description="Job scraper Discord bot")
_parser.add_argument(
    "--env",
    default=".env",
    metavar="FILE",
    help="Path to env file (default: .env)",
)
_args = _parser.parse_args()
os.environ.setdefault("ENV_FILE", _args.env)

import asyncio  # noqa: E402

import discord  # noqa: E402
from discord import app_commands  # noqa: E402

from bot import commands  # noqa: E402
from bot.config import settings  # noqa: E402
from bot.db import init_db  # noqa: E402
from bot.scheduler import (  # noqa: E402
    poll_ashby,
    poll_greenhouse,
    poll_lever,
    poll_simplify,
    poll_user_alerts,
    poll_workday,
    run_custom_scrapers,
    set_bot,
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
tree = app_commands.CommandTree(bot)
commands.register(tree)


@bot.event
async def on_ready() -> None:
    logger.info("Logged in as %s", bot.user)

    channel = bot.get_channel(settings.discord_channel_id)
    if channel is None:
        logger.error("Channel %d not found — exiting", settings.discord_channel_id)
        await bot.close()
        return

    set_channel(channel)  # type: ignore[arg-type]
    set_bot(bot)

    logger.info("Initializing database...")
    await init_db()

    if settings.discord_guild_id:
        guild = discord.Object(id=settings.discord_guild_id)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        logger.info("Slash commands synced to guild %d (instant)", settings.discord_guild_id)
    else:
        await tree.sync()
        logger.info("Slash commands synced globally (may take up to 1 hour to propagate)")

    # Run all scrapers once on startup
    logger.info("Running initial scrape...")
    await asyncio.gather(
        poll_greenhouse(),
        poll_lever(),
        poll_ashby(),
        poll_simplify(),
        poll_workday(),
        *run_custom_scrapers(),
    )

    # Immediately check if any users are due for an alert after the first scrape
    await poll_user_alerts()

    # Then start the recurring scheduler
    start_scheduler()
    logger.info("Bot is running. Polling for jobs.")


def main() -> None:
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
