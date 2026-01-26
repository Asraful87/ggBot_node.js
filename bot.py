import discord
from discord.ext import commands
import os
import yaml
import asyncio
from dotenv import load_dotenv
from database.db_manager import DatabaseManager
from utils.logging import get_logger, setup_logging

load_dotenv()

with open("config.yaml", "r", encoding="utf-8-sig") as f:
    config = yaml.safe_load(f)

# Configure logging once, then get a named logger
setup_logging()
logger = get_logger("modbot")


class ModBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix=config["bot"].get("command_prefix", "!"),  # ✅ enable prefix too
            intents=intents,
            help_command=None
        )

        self.config = config
        self.db = DatabaseManager()

    async def setup_hook(self):
        # ✅ init DB once
        try:
            await self.db.init_db()
            logger.info("Database initialized")
        except Exception as e:
            logger.error(f"DB init failed: {e}")

        cogs = [
            "cogs.moderation",
            "cogs.channels",
            "cogs.messages",
            "cogs.roles",
            "cogs.utilities",
            "cogs.setup",
            "cogs.verification",
            "cogs.tickets",
        ]

        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                logger.exception(f"Failed to load cog: {cog}")
                continue

        # ✅ FAST: sync to your test guild immediately
        guild_id = os.getenv("GUILD_ID")  # set this in .env
        if guild_id and guild_id.isdigit():
            gid = int(guild_id)
            guild_obj = discord.Object(id=gid)
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            logger.info(f"✅ Guild-synced {len(synced)} slash commands to guild {gid}")
        else:
            # ✅ Global sync (can take time to show)
            synced = await self.tree.sync()
            logger.info(f"✅ Globally synced {len(synced)} slash commands")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")


async def main():
    bot = ModBot()
    async with bot:
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise RuntimeError("DISCORD_TOKEN is not seti. Add it to your .env file (DISCORD_TOKEN=...).")

        try:
            await bot.start(token)
        except discord.LoginFailure as exc:
            logger.error("Discord login failed: invalid DISCORD_TOKEN. Regenerate the bot token in the Developer Portal and update your .env file.")
            raise exc


if __name__ == "__main__":
    asyncio.run(main())
