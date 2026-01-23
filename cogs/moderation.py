"""
Moderation Cog (SLASH COMMANDS)
Handles kick, ban, warn, timeout, and other moderation commands
"""

from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta
from utils.embeds import create_error_embed
from utils.confirmations import ConfirmView


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user

        if member == interaction.guild.owner:
            return await interaction.response.send_message(embed=create_error_embed("You cannot kick the server owner."), ephemeral=True)

        if member.top_role >= author.top_role and author.id != interaction.guild.owner_id:
            return await interaction.response.send_message(
                embed=create_error_embed("You cannot kick someone with a higher or equal role."),
                ephemeral=True,
            )

        try:
            await member.kick(reason=f"{reason} | Kicked by {author} ({author.id})")
            await self.bot.db.log_action(interaction.guild.id, "kick", member.id, author.id, reason)

            embed = discord.Embed(
                title="Member Kicked",
                description=f"{member.mention} has been kicked.\n**Moderator:** {author.mention}\n**Reason:** {reason}",
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed)
            await self._post_modlog(interaction.guild, embed)

        except discord.Forbidden:
            await interaction.response.send_message(embed=create_error_embed("I don't have permission to kick this member."), ephemeral=True)

    # ---------- BAN ----------
    @app_commands.command(name="ban", description="Ban a member from the server (with confirmation).")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user

        if member == interaction.guild.owner:
            return await interaction.response.send_message(embed=create_error_embed("You cannot ban the server owner."), ephemeral=True)

        if member.top_role >= author.top_role and author.id != interaction.guild.owner_id:
            return await interaction.response.send_message(
                embed=create_error_embed("You cannot ban someone with a higher or equal role."),
                ephemeral=True,
            )

        # Confirmation UI
        view = ConfirmView(author)
        await interaction.response.send_message(
            content=f"Are you sure you want to ban {member.mention}?",
            view=view,
            ephemeral=True,
        )
        await view.wait()

        # We need to edit the original response message
        try:
            msg = await interaction.original_response()
        except Exception:
            msg = None

        if not view.value:
            if msg:
                return await msg.edit(content="❌ Ban cancelled.", view=None)
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
                await interaction.followup.send(embed=embed, ephemeral=True)

            await self._post_modlog(interaction.guild, embed)

        except discord.Forbidden:
            if msg:
                await msg.edit(content="❌ I don't have permission to ban this member.", view=None)
            else:
                await interaction.followup.send(embed=create_error_embed("I don't have permission to ban this member."), ephemeral=True)

    # ---------- UNBAN (by user ID) ----------
    @app_commands.command(name="unban", description="Unban a user by their user ID.")
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(self, interaction: discord.Interaction, user_id: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user

        # allow passing "<@123>" or "123"
        cleaned = user_id.strip().replace("<@", "").replace(">", "").replace("!", "")
        if not cleaned.isdigit():
            return await interaction.response.send_message(embed=create_error_embed("Please provide a valid user ID."), ephemeral=True)

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
            await interaction.response.send_message(embed=embed)
            await self._post_modlog(interaction.guild, embed)

        except discord.NotFound:
            await interaction.response.send_message(embed=create_error_embed("User not found or not banned."), ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(embed=create_error_embed("I don't have permission to unban users."), ephemeral=True)

    # ---------- WARN ----------
    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user

        if member.top_role >= author.top_role and author.id != interaction.guild.owner_id:
            return await interaction.response.send_message(
                embed=create_error_embed("You cannot warn someone with a higher or equal role."),
                ephemeral=True,
            )

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
        await interaction.response.send_message(embed=embed)
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

        # Auto action
        warn_threshold = self.bot.config["moderation"]["warn_threshold"]
        auto_action = self.bot.config["moderation"]["warn_threshold_action"]

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
            return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

        warnings = await self.bot.db.get_warnings(interaction.guild.id, member.id)

        if not warnings:
            return await interaction.response.send_message(f"{member.mention} has no warnings.", ephemeral=True)

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

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------- CLEAR WARNINGS ----------
    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

        cleared = await self.bot.db.clear_warnings(interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ Cleared {cleared} warning(s) for {member.mention}.", ephemeral=True)

    # ---------- TIMEOUT ----------
    @app_commands.command(name="timeout", description="Timeout a member (duration in minutes).")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: int,
        reason: str = "No reason provided",
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user

        if member.top_role >= author.top_role and author.id != interaction.guild.owner_id:
            return await interaction.response.send_message(
                embed=create_error_embed("You cannot timeout someone with a higher or equal role."),
                ephemeral=True,
            )

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
            await interaction.response.send_message(embed=embed)
            await self._post_modlog(interaction.guild, embed)

        except discord.Forbidden:
            await interaction.response.send_message(embed=create_error_embed("I don't have permission to timeout this member."), ephemeral=True)

    # ---------- UNTIMEOUT ----------
    @app_commands.command(name="untimeout", description="Remove timeout from a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def untimeout(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)

        author = interaction.user

        try:
            await member.timeout(None, reason=f"Timeout removed by {author} ({author.id})")
            await self.bot.db.log_action(interaction.guild.id, "untimeout", member.id, author.id, None)

            embed = discord.Embed(
                title="Timeout Removed",
                description=f"Timeout removed from {member.mention}.\n**Moderator:** {author.mention}",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed)
            await self._post_modlog(interaction.guild, embed)

        except discord.Forbidden:
            await interaction.response.send_message(embed=create_error_embed("I don't have permission to remove timeout."), ephemeral=True)

    # ---------- Error handling for this cog ----------
    @kick.error
    @ban.error
    @unban.error
    @warn.error
    @warnings.error
    @clearwarnings.error
    @timeout.error
    @untimeout.error
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            return await interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
        await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
