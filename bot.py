"""
Discord Moderation Bot
Main entry point for the bot
"""

import os
import asyncio
import logging
import yaml
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

from database.db_manager import DatabaseManager

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not found. Create a .env file in project root.")

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

BOT_PREFIX = config.get("bot", {}).get("command_prefix", "!")
GUILD_ID = config.get("bot", {}).get("guild_id", None)
GUILD_ID = int(GUILD_ID) if GUILD_ID else None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("modbot")


class ModBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.guilds = True
        intents.message_content = True

        super().__init__(
            command_prefix=BOT_PREFIX,   # classic prefix commands (e.g., !ping)
            case_insensitive=True,
            intents=intents,
            help_command=None
        )

        self.config = config
        self.db = DatabaseManager()

        # Global check: ensure bot has View/Send in the current text channel
        self.add_check(self._channel_perms_check)

    async def setup_hook(self):
        await self.db.init_db()
        logger.info("Database initialized")
        logger.info(f"Prefix commands enabled with prefix: '{BOT_PREFIX}' (case-insensitive)")
        if not self.intents.message_content:
            logger.warning("Message Content Intent is disabled; prefix commands will not work. Enable it in the Developer Portal.")

        cogs = [
            "cogs.moderation",
            "cogs.channels",
            "cogs.messages",
            "cogs.roles",
            "cogs.utilities",
            "cogs.setup",
        ]

        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception:
                logger.exception(f"Failed to load cog: {cog}")

        # ✅ FAST: Guild sync (shows in seconds)
        if GUILD_ID:
            try:
                guild = discord.Object(id=GUILD_ID)
                synced = await self.tree.sync(guild=guild)
                logger.info(f"✅ Guild-synced {len(synced)} slash commands to guild {GUILD_ID}")
            except Exception:
                logger.exception("❌ Guild sync failed")
        else:
            logger.warning("⚠️ No guild_id in config.yaml -> guild sync skipped (slash commands may take long).")

        # ✅ Global sync (can take time to appear)
        try:
            synced_global = await self.tree.sync()
            logger.info(f"✅ Globally synced {len(synced_global)} slash commands")
        except Exception:
            logger.exception("❌ Global sync failed")

        # Global slash-command error handler: prevents "Bot is thinking..." with no followup.
        self.tree.on_error = self._on_app_command_error

    async def _safe_interaction_send(
        self,
        interaction: discord.Interaction,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        ephemeral: bool = True,
    ):
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        return await send(content=content, embed=embed, ephemeral=ephemeral)

    async def _on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # Log full traceback server-side
        logger.exception("App command error", exc_info=error)

        # Unwrap common wrapper so message is useful
        if isinstance(error, app_commands.CommandInvokeError) and getattr(error, "original", None):
            error = error.original  # type: ignore[assignment]

        try:
            if isinstance(error, app_commands.MissingPermissions):
                return await self._safe_interaction_send(
                    interaction,
                    content="❌ You don’t have permission to use this command.",
                    ephemeral=True,
                )

            if isinstance(error, app_commands.CheckFailure):
                return await self._safe_interaction_send(
                    interaction,
                    content="❌ You can’t use this command here.",
                    ephemeral=True,
                )

            # Generic fallback
            return await self._safe_interaction_send(
                interaction,
                content=f"❌ Error: {error}",
                ephemeral=True,
            )
        except Exception:
            # If responding fails (e.g., interaction expired), swallow.
            return

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="/help"
            )
        )

        # Startup sanity check: warn if missing read/send in text channels
        try:
            for guild in self.guilds:
                me = guild.me
                missing_channels = []
                for ch in guild.text_channels:
                    perms = ch.permissions_for(me)
                    if not (perms.view_channel and perms.send_messages):
                        missing_channels.append(ch.name)

                if missing_channels:
                    sample = ", ".join(missing_channels[:5])
                    more = len(missing_channels) - min(5, len(missing_channels))
                    suffix = f" …(+{more} more)" if more > 0 else ""
                    logger.warning(
                        f"⚠️ Guild '{guild.name}': missing View/Send in {len(missing_channels)} channel(s): {sample}{suffix}"
                    )
        except Exception:
            logger.exception("Permission check failed during on_ready")

    async def _channel_perms_check(self, ctx: commands.Context) -> bool:
        """Global check for prefix commands to ensure the bot can reply.

        If the bot lacks Send Messages in the current text channel, attempts to
        DM the user a friendly notice and prevents command execution.
        """
        try:
            # Only applies to guild text channels; DMs are fine
            if hasattr(ctx, "guild") and ctx.guild and isinstance(ctx.channel, discord.TextChannel):
                me = ctx.guild.me
                perms = ctx.channel.permissions_for(me)

                # If the bot cannot view the channel, the command wouldn't reach here
                if not perms.view_channel:
                    return False

                if not perms.send_messages:
                    # Try to notify the user via DM; ignore failures
                    try:
                        await ctx.author.send(
                            f"I can't send messages in {ctx.channel.mention}. "
                            "Ask an admin to grant me 'View Channel' and 'Send Messages' permissions."
                        )
                    except Exception:
                        pass

                    logger.warning(
                        f"Prefix command blocked: missing Send Messages in #{ctx.channel} (guild: {ctx.guild.name})"
                    )
                    return False

            return True
        except Exception:
            # On any error, allow command to proceed to avoid false negatives
            logger.exception("Global channel perms check error")
            return True


async def main():
    bot = ModBot()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
cogs = [
    "cogs.moderation",
    "cogs.channels",
    "cogs.messages",
    "cogs.roles",
    "cogs.utilities",
    "cogs.setup",
    "cogs.welcome",
]
