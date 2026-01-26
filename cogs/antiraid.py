from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from collections import deque

from utils.embeds import create_error_embed, create_success_embed


class AntiRaid(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.join_cache: dict[int, deque[datetime]] = {}
        self.raid_enabled: dict[int, bool] = {}

    # ---------- JOIN MONITOR ----------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.guild:
            return

        cfg = self.bot.config.get("antiraid", {})
        if not cfg.get("enabled", False):
            return

        guild_id = member.guild.id
        now = datetime.utcnow()

        # init cache
        if guild_id not in self.join_cache:
            self.join_cache[guild_id] = deque()

        joins = self.join_cache[guild_id]
        joins.append(now)

        # clear old joins
        interval = cfg.get("join_interval_seconds", 15)
        while joins and (now - joins[0]).total_seconds() > interval:
            joins.popleft()

        # account age check
        min_days = cfg.get("min_account_age_days", 0)
        account_age_days = (now - member.created_at.replace(tzinfo=None)).days

        # RAID DETECTED
        if len(joins) >= cfg.get("join_threshold", 5) or account_age_days < min_days:
            await self._handle_raid(member, account_age_days)

    # ---------- RAID RESPONSE ----------
    async def _handle_raid(self, member: discord.Member, account_age_days: int):
        cfg = self.bot.config["antiraid"]
        guild = member.guild

        # Timeout new member
        try:
            await member.timeout(
                timedelta(minutes=cfg.get("auto_timeout_minutes", 10)),
                reason="Anti-Raid protection"
            )
        except Exception:
            pass

        # Enable slowmode (first text channel only, safe)
        for channel in guild.text_channels:
            try:
                if channel.slowmode_delay == 0:
                    await channel.edit(
                        slowmode_delay=cfg.get("slowmode_seconds", 15),
                        reason="Anti-Raid slowmode"
                    )
                break
            except Exception:
                continue

        # Alert staff
        await self._send_alert(
            guild,
            member,
            account_age_days
        )

    async def _send_alert(self, guild: discord.Guild, member: discord.Member, age: int):
        settings = await self.bot.db.get_server_config(guild.id)
        if not settings:
            return

        log_channel_id = settings.get("mod_log_channel_id")
        if not log_channel_id:
            return

        channel = guild.get_channel(log_channel_id)
        if not channel:
            return

        embed = discord.Embed(
            title="🚨 Anti-Raid Triggered",
            description=(
                f"Suspicious join detected.\n\n"
                f"**User:** {member.mention}\n"
                f"**Account Age:** {age} days\n"
                f"**Action:** Auto-timeout + slowmode"
            ),
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )

        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    # ---------- MANUAL CONTROLS ----------
    @app_commands.command(name="raid", description="Control anti-raid mode")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def raid(self, interaction: discord.Interaction, mode: str):
        mode = mode.lower()
        guild_id = interaction.guild.id

        if mode not in ("on", "off", "status"):
            return await interaction.response.send_message(
                "❌ Usage: `/raid on | off | status`",
                ephemeral=True
            )

        if mode == "status":
            enabled = self.raid_enabled.get(guild_id, True)
            return await interaction.response.send_message(
                f"🛡️ Anti-Raid is **{'ON' if enabled else 'OFF'}**",
                ephemeral=True
            )

        self.raid_enabled[guild_id] = (mode == "on")

        await interaction.response.send_message(
            embed=create_success_embed(f"Anti-Raid turned **{mode.upper()}**"),
            ephemeral=True
        )

    @raid.error
    async def raid_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            return await interaction.response.send_message(
                "❌ Admin only.",
                ephemeral=True
            )
        await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiRaid(bot))
