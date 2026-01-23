"""
Moderation Cog (SLASH COMMANDS)
Handles kick, ban, warn, timeout, and other moderation commands
"""

from __future__ import annotations

import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta
from utils.embeds import create_error_embed, create_success_embed
from utils.confirmations import ConfirmView


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _db_call(self, coro, *, timeout: float = 10.0):
        """Run a DB coroutine with a timeout to avoid interactions hanging forever."""
        return await asyncio.wait_for(coro, timeout=timeout)

    async def _defer(self, interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
        """Defer safely to avoid 'This interaction failed' on slow operations."""
        if interaction.response.is_done():
            return
        try:
            await interaction.response.defer(ephemeral=ephemeral)
        except Exception:
            pass

    async def cog_load(self) -> None:
        """
        Optional: auto-sync slash commands so newly added ones actually appear.
        Configure with:
          bot.config["discord"]["sync_app_commands"] = True
          bot.config["discord"]["sync_guild_ids"] = [123, 456]   # optional (faster than global)
        """
        cfg = getattr(self.bot, "config", {}) or {}
        discord_cfg = cfg.get("discord", {}) if isinstance(cfg, dict) else {}
        if not isinstance(discord_cfg, dict) or not discord_cfg.get("sync_app_commands"):
            return

        guild_ids = discord_cfg.get("sync_guild_ids")
        try:
            if isinstance(guild_ids, (list, tuple)) and guild_ids:
                for gid in guild_ids:
                    await self.bot.tree.sync(guild=discord.Object(id=int(gid)))
            else:
                await self.bot.tree.sync()
        except Exception:
            # avoid blocking cog load if sync fails (rate limits / perms / transient errors)
            pass

    async def _respond(self, interaction: discord.Interaction, *, content: str | None = None,
                       embed: discord.Embed | None = None, ephemeral: bool = False, view=None):
        """Send via initial response if possible, else via followup (prevents InteractionResponded issues)."""
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        return await send(content=content, embed=embed, ephemeral=ephemeral, view=view)

    async def _post_modlog(self, guild: discord.Guild, embed: discord.Embed):
        settings = await self.bot.db.get_server_settings(guild.id)
        channel_id = settings.get("log_channel")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

    # ---------- KICK ----------
    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await self._respond(interaction, content="❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user

        if member == interaction.guild.owner:
            return await self._respond(interaction, embed=create_error_embed("You cannot kick the server owner."), ephemeral=True)

        if member.top_role >= author.top_role and author.id != interaction.guild.owner_id:
            return await self._respond(interaction, embed=create_error_embed("You cannot kick someone with a higher or equal role."), ephemeral=True)

        await self._defer(interaction, ephemeral=True)

        try:
            await member.kick(reason=f"{reason} | Kicked by {author} ({author.id})")
            await self.bot.db.log_action(interaction.guild.id, "kick", member.id, author.id, reason)

            embed = discord.Embed(
                title="Member Kicked",
                description=f"{member.mention} has been kicked.\n**Moderator:** {author.mention}\n**Reason:** {reason}",
                color=discord.Color.orange(),
            )
            await self._respond(interaction, embed=embed, ephemeral=False)
            await self._post_modlog(interaction.guild, embed)
        except discord.Forbidden:
            await self._respond(interaction, embed=create_error_embed("I don't have permission to kick this member."), ephemeral=True)
        except discord.HTTPException:
            await self._respond(interaction, embed=create_error_embed("Kick failed due to a Discord API error."), ephemeral=True)

    # ---------- BAN ----------
    @app_commands.command(name="ban", description="Ban a member from the server (with confirmation).")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await self._respond(interaction, content="❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user

        if member == interaction.guild.owner:
            return await self._respond(interaction, embed=create_error_embed("You cannot ban the server owner."), ephemeral=True)

        if member.top_role >= author.top_role and author.id != interaction.guild.owner_id:
            return await self._respond(interaction, embed=create_error_embed("You cannot ban someone with a higher or equal role."), ephemeral=True)

        view = ConfirmView(author)
        await self._respond(
            interaction,
            content=f"Are you sure you want to ban {member.mention}?",
            view=view,
            ephemeral=True,
        )
        await view.wait()

        try:
            msg = await interaction.original_response()
        except Exception:
            msg = None

        if view.value is not True:
            if msg:
                await msg.edit(content="❌ Ban cancelled.", view=None)
            return

        try:
            await member.ban(reason=f"{reason} | Banned by {author} ({author.id})")
            await self.bot.db.log_action(interaction.guild.id, "ban", member.id, author.id, reason)

            embed = discord.Embed(
                title="Member Banned",
                description=f"{member.mention} has been banned.\n**Moderator:** {author.mention}\n**Reason:** {reason}",
                color=discord.Color.red(),
            )
            if msg:
                await msg.edit(content=None, embed=embed, view=None)
            else:
                await self._respond(interaction, embed=embed, ephemeral=True)

            await self._post_modlog(interaction.guild, embed)
        except discord.Forbidden:
            err = "❌ I don't have permission to ban this member."
            if msg:
                await msg.edit(content=err, view=None)
            else:
                await self._respond(interaction, embed=create_error_embed(err), ephemeral=True)
        except discord.HTTPException:
            err = "❌ Ban failed due to a Discord API error."
            if msg:
                await msg.edit(content=err, view=None)
            else:
                await self._respond(interaction, embed=create_error_embed(err), ephemeral=True)

    # ---------- UNBAN (by user ID) ----------
    @app_commands.command(name="unban", description="Unban a user by their user ID.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(self, interaction: discord.Interaction, user_id: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await self._respond(interaction, content="❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user
        cleaned = user_id.strip().replace("<@", "").replace(">", "").replace("!", "")
        if not cleaned.isdigit():
            return await self._respond(interaction, embed=create_error_embed("Please provide a valid user ID."), ephemeral=True)

        await self._defer(interaction, ephemeral=True)

        uid = int(cleaned)
        try:
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user)
            await self.bot.db.log_action(interaction.guild.id, "unban", user.id, author.id, None)

            embed = discord.Embed(
                title="User Unbanned",
                description=f"{user.mention} has been unbanned.\n**Moderator:** {author.mention}",
                color=discord.Color.green(),
            )
            await self._respond(interaction, embed=embed, ephemeral=False)
            await self._post_modlog(interaction.guild, embed)
        except discord.NotFound:
            await self._respond(interaction, embed=create_error_embed("User not found or not banned."), ephemeral=True)
        except discord.Forbidden:
            await self._respond(interaction, embed=create_error_embed("I don't have permission to unban users."), ephemeral=True)
        except discord.HTTPException:
            await self._respond(interaction, embed=create_error_embed("Unban failed due to a Discord API error."), ephemeral=True)

    # ---------- WARN ----------
    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await self._respond(interaction, content="❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user

        if member.top_role >= author.top_role and author.id != interaction.guild.owner_id:
            return await self._respond(interaction, embed=create_error_embed("You cannot warn someone with a higher or equal role."), ephemeral=True)

        await self._defer(interaction, ephemeral=True)

        await self.bot.db.add_warning(interaction.guild.id, member.id, author.id, reason)
        await self.bot.db.log_action(interaction.guild.id, "warn", member.id, author.id, reason)

        warning_count = await self.bot.db.get_warning_count(interaction.guild.id, member.id)

        embed = discord.Embed(
            title="Member Warned",
            description=(
                f"{member.mention} has been warned.\n"
                f"**Total Warnings:** {warning_count}\n"
                f"**Moderator:** {author.mention}\n"
                f"**Reason:** {reason}"
            ),
            color=discord.Color.orange(),
        )
        await self._respond(interaction, embed=embed, ephemeral=False)
        await self._post_modlog(interaction.guild, embed)

        # Try DM
        try:
            dm_embed = discord.Embed(
                title=f"Warning in {interaction.guild.name}",
                description=f"**Reason:** {reason}\n**Total Warnings:** {warning_count}",
                color=discord.Color.orange(),
            )
            await member.send(embed=dm_embed)
        except Exception:
            pass

        # Auto action (harden config access so missing keys don't crash the command)
        mod_cfg = (getattr(self.bot, "config", {}) or {}).get("moderation", {})
        if not isinstance(mod_cfg, dict):
            mod_cfg = {}

        try:
            warn_threshold = int(mod_cfg.get("warn_threshold", 0))
        except Exception:
            warn_threshold = 0

        auto_action = str(mod_cfg.get("warn_threshold_action", "none")).lower()
        if warn_threshold <= 0 or auto_action == "none":
            return

        if warning_count >= warn_threshold and auto_action != "none":
            if auto_action == "timeout":
                duration = self.bot.config["moderation"]["warn_threshold_timeout_duration"]
                try:
                    await member.timeout(timedelta(minutes=duration), reason=f"Reached {warn_threshold} warnings")
                    await interaction.followup.send(
                        f"⚠️ {member.mention} has been timed out for reaching {warn_threshold} warnings.",
                        ephemeral=False,
                    )
                except discord.Forbidden:
                    await interaction.followup.send(embed=create_error_embed("I don't have permission to timeout this member."), ephemeral=True)

            elif auto_action == "kick":
                try:
                    await member.kick(reason=f"Reached {warn_threshold} warnings")
                    await interaction.followup.send(
                        f"⚠️ {member.mention} has been kicked for reaching {warn_threshold} warnings.",
                        ephemeral=False,
                    )
                except discord.Forbidden:
                    await interaction.followup.send(embed=create_error_embed("I don't have permission to kick this member."), ephemeral=True)

            elif auto_action == "ban":
                try:
                    await member.ban(reason=f"Reached {warn_threshold} warnings")
                    await interaction.followup.send(
                        f"⚠️ {member.mention} has been banned for reaching {warn_threshold} warnings.",
                        ephemeral=False,
                    )
                except discord.Forbidden:
                    await interaction.followup.send(embed=create_error_embed("I don't have permission to ban this member."), ephemeral=True)

    # ---------- WARNINGS LIST ----------
    @app_commands.command(name="warnings", description="View warnings for a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await self._respond(interaction, content="❌ This command can only be used in a server.", ephemeral=True)

        await self._defer(interaction, ephemeral=True)

        try:
            warnings = await self._db_call(self.bot.db.get_warnings(interaction.guild.id, member.id))
        except asyncio.TimeoutError:
            return await self._respond(interaction, embed=create_error_embed("DB timed out while fetching warnings. Try again."), ephemeral=True)

        if not warnings:
            return await self._respond(interaction, content=f"{member.mention} has no warnings.", ephemeral=True)

        embed = discord.Embed(
            title=f"Warnings for {member}",
            description=f"Total warnings: {len(warnings)}",
            color=discord.Color.orange(),
        )

        for i, warning in enumerate(warnings[:10], 1):
            mod_id = warning.get("mod_id")
            mod_name = f"<@{mod_id}>" if mod_id else "Unknown"

            embed.add_field(
                name=f"Warning {i}",
                value=(
                    f"**Reason:** {warning.get('reason') or 'No reason'}\n"
                    f"**By:** {mod_name}\n"
                    f"**Date:** {warning.get('timestamp')}"
                ),
                inline=False,
            )

        await self._respond(interaction, embed=embed, ephemeral=True)

    # ---------- CLEAR WARNINGS ----------
    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await self._respond(interaction, content="❌ This command can only be used in a server.", ephemeral=True)

        await self._defer(interaction, ephemeral=True)
        try:
            cleared = await self._db_call(self.bot.db.clear_warnings(interaction.guild.id, member.id))
        except asyncio.TimeoutError:
            return await self._respond(interaction, embed=create_error_embed("DB timed out while clearing warnings. Try again."), ephemeral=True)

        await self._respond(interaction, content=f"✅ Cleared {cleared} warning(s) for {member.mention}.", ephemeral=True)

    # ---------- TIMEOUT ----------
    @app_commands.command(name="timeout", description="Timeout a member (duration in minutes).")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, duration: int, reason: str = "No reason provided"):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await self._respond(interaction, content="❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user

        if member.top_role >= author.top_role and author.id != interaction.guild.owner_id:
            return await self._respond(interaction, embed=create_error_embed("You cannot timeout someone with a higher or equal role."), ephemeral=True)

        await self._defer(interaction, ephemeral=True)

        try:
            await member.timeout(timedelta(minutes=duration), reason=f"{reason} | Timed out by {author} ({author.id})")
            await self.bot.db.log_action(interaction.guild.id, "timeout", member.id, author.id, reason)

            embed = discord.Embed(
                title="Member Timed Out",
                description=(
                    f"{member.mention} has been timed out for {duration} minutes.\n"
                    f"**Moderator:** {author.mention}\n"
                    f"**Reason:** {reason}"
                ),
                color=discord.Color.orange(),
            )
            await self._respond(interaction, embed=embed, ephemeral=False)
            await self._post_modlog(interaction.guild, embed)
        except discord.Forbidden:
            await self._respond(interaction, embed=create_error_embed("I don't have permission to timeout this member."), ephemeral=True)
        except discord.HTTPException:
            await self._respond(interaction, embed=create_error_embed("Timeout failed due to a Discord API error."), ephemeral=True)

    # ---------- UNTIMEOUT ----------
    @app_commands.command(name="untimeout", description="Remove timeout from a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await self._respond(interaction, content="❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user
        await self._defer(interaction, ephemeral=True)

        try:
            await member.timeout(None, reason=f"Timeout removed by {author} ({author.id})")
            await self.bot.db.log_action(interaction.guild.id, "untimeout", member.id, author.id, None)

            embed = discord.Embed(
                title="Timeout Removed",
                description=f"Timeout removed from {member.mention}.\n**Moderator:** {author.mention}",
                color=discord.Color.green(),
            )
            await self._respond(interaction, embed=embed, ephemeral=False)
            await self._post_modlog(interaction.guild, embed)
        except discord.Forbidden:
            await self._respond(interaction, embed=create_error_embed("I don't have permission to remove timeout."), ephemeral=True)
        except discord.HTTPException:
            await self._respond(interaction, embed=create_error_embed("Untimeout failed due to a Discord API error."), ephemeral=True)

    # ---------- MUTE / UNMUTE (aliases for timeout) ----------
    @app_commands.command(name="mute", description="Mute a member (alias for timeout; duration in minutes).")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"):
        return await self.timeout(interaction, member, int(duration), reason)

    @app_commands.command(name="unmute", description="Unmute a member (alias for untimeout).")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        return await self.untimeout(interaction, member)

    # ---------- UNWARN ----------
    @app_commands.command(name="unwarn", description="Remove the most recent warning from a member (if supported by DB).")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def unwarn(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await self._respond(interaction, content="❌ This command can only be used in a server.", ephemeral=True)

        await self._defer(interaction, ephemeral=True)

        warnings = await self.bot.db.get_warnings(interaction.guild.id, member.id)
        if not warnings:
            return await self._respond(interaction, embed=create_error_embed("That member has no warnings."), ephemeral=True)

        latest = warnings[0]  # assumes newest-first; if your DB returns oldest-first, switch to warnings[-1]
        wid = latest.get("id") or latest.get("warning_id") or latest.get("_id")

        # Best-effort removal depending on DB API availability
        if wid is not None and hasattr(self.bot.db, "delete_warning"):
            await self.bot.db.delete_warning(interaction.guild.id, wid)
        elif hasattr(self.bot.db, "remove_warning"):
            await self.bot.db.remove_warning(interaction.guild.id, member.id)  # DB-specific
        else:
            return await self._respond(
                interaction,
                embed=create_error_embed("Unwarn is not supported by your DB backend. Use /clearwarnings instead."),
                ephemeral=True,
            )

        new_count = await self.bot.db.get_warning_count(interaction.guild.id, member.id)
        await self.bot.db.log_action(interaction.guild.id, "unwarn", member.id, interaction.user.id, "Removed latest warning")
        await self._respond(interaction, embed=create_success_embed(f"Removed 1 warning from {member.mention}. Now: {new_count}."), ephemeral=True)

    # ---------- FEATURES ----------
    @app_commands.command(name="features", description="List available moderation features in this bot.")
    @app_commands.guild_only()
    async def features(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Bot Features (loaded from this cog)",
            color=discord.Color.blurple(),
            description=(
                "**Moderation (slash):**\n"
                "- /kick (role checks, DB log, optional modlog)\n"
                "- /ban (confirmation UI, DB log, optional modlog)\n"
                "- /unban (by user ID/mention, DB log, optional modlog)\n"
                "- /warn (stores warnings, DB log, DM attempt, optional threshold auto-action)\n"
                "- /warnings (view warnings)\n"
                "- /clearwarnings (admin-only)\n"
                "- /timeout, /untimeout (DB log, optional modlog)\n\n"
                "**Operational:**\n"
                "- Optional slash command sync on cog load (config-driven)\n"
                "- Shared app-command error handler (safe followups)\n"
                "- Modlog posting to configured log channel\n"
            ),
        )
        await self._respond(interaction, embed=embed, ephemeral=True)

    # ---------- PURGE ----------
    @app_commands.command(name="purge", description="Delete messages in bulk (custom amount).")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 500]):
        if not interaction.guild:
            return await self._respond(interaction, content="❌ This command can only be used in a server.", ephemeral=True)

        # Respect optional configured max (defaults to 100)
        mod_cfg = (getattr(self.bot, "config", {}) or {}).get("moderation", {})
        if not isinstance(mod_cfg, dict):
            mod_cfg = {}
        try:
            max_amount = int(mod_cfg.get("max_purge_amount", 100))
        except Exception:
            max_amount = 100

        if amount > max_amount:
            return await self._respond(
                interaction,
                embed=create_error_embed(f"Max purge amount is {max_amount}."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        channel = interaction.channel
        if channel is None or not hasattr(channel, "purge"):
            return await interaction.followup.send(
                embed=create_error_embed("This command can only be used in a text-based channel."),
                ephemeral=True,
            )

        try:
            deleted = await channel.purge(limit=amount)
            await interaction.followup.send(
                embed=create_success_embed(f"Deleted **{len(deleted)}** messages."),
                ephemeral=True,
            )
            await self.bot.db.log_action(
                interaction.guild.id,
                "purge",
                interaction.user.id,
                interaction.user.id,
                f"Purged {len(deleted)} messages",
            )
        except discord.Forbidden:
            await interaction.followup.send(embed=create_error_embed("I don't have permission to delete messages here."), ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send(embed=create_error_embed("Failed to delete messages. Messages might be too old."), ephemeral=True)

    # ---------- Error handling for this cog ----------
    @kick.error
    @ban.error
    @unban.error
    @warn.error
    @warnings.error
    @clearwarnings.error
    @timeout.error
    @untimeout.error
    @features.error
    @purge.error
    @mute.error
    @unmute.error
    @unwarn.error
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # unwrap common wrapper so you see the real exception
        if isinstance(error, app_commands.CommandInvokeError) and getattr(error, "original", None):
            error = error.original  # type: ignore[assignment]

        if isinstance(error, app_commands.MissingPermissions):
            return await self._respond(interaction, content="❌ You don’t have permission to use this command.", ephemeral=True)

        # If you were already responded/deferred in a command, use followup safely
        return await self._respond(interaction, content=f"❌ Error: {error}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
