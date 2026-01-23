"""
Messages Cog
Handles message purging and message utilities
"""
from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands
from utils.embeds import create_success_embed, create_error_embed


class Messages(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _max_purge_amount(self) -> int:
        try:
            return int(self.bot.config.get("moderation", {}).get("max_purge_amount", 100))
        except Exception:
            return 100

    @commands.command(name='purge')
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def purge(self, ctx, amount: int):
        """Delete multiple messages (up to configured max)"""
        max_amount = self._max_purge_amount()
        if amount < 1:
            await ctx.send(embed=create_error_embed("Amount must be at least 1."))
            return
        if amount > max_amount:
            await ctx.send(embed=create_error_embed(f"Cannot delete more than {max_amount} messages at once."))
            return
        if not hasattr(ctx.channel, "purge"):
            await ctx.send(embed=create_error_embed("This command can only be used in a text-based channel."))
            return

        try:
            await ctx.message.delete()
            deleted = await ctx.channel.purge(limit=amount)
            msg = await ctx.send(embed=create_success_embed(f"Deleted {len(deleted)} messages."))
            await msg.delete(delay=3)
            await self.bot.db.log_action(ctx.guild.id, "purge", ctx.author.id, ctx.author.id, f"Purged {len(deleted)} messages")
        except discord.Forbidden:
            await ctx.send(embed=create_error_embed("I don't have permission to delete messages."))
        except discord.HTTPException:
            await ctx.send(embed=create_error_embed("Failed to delete messages. Messages might be too old."))

    @commands.command(name='clear')
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def clear(self, ctx, amount: int, member: discord.Member = None):
        """Delete messages from a specific user or all messages (up to configured max)"""
        max_amount = self._max_purge_amount()
        if amount < 1:
            await ctx.send(embed=create_error_embed("Amount must be at least 1."))
            return
        if amount > max_amount:
            await ctx.send(embed=create_error_embed(f"Cannot delete more than {max_amount} messages at once."))
            return
        if not hasattr(ctx.channel, "purge"):
            await ctx.send(embed=create_error_embed("This command can only be used in a text-based channel."))
            return

        try:
            await ctx.message.delete()

            def check(msg):
                return True if member is None else (msg.author == member)

            deleted = await ctx.channel.purge(limit=amount, check=check)

            msg = await ctx.send(
                embed=create_success_embed(
                    f"Deleted {len(deleted)} messages from {member.mention}." if member else f"Deleted {len(deleted)} messages."
                )
            )
            await msg.delete(delay=3)

            target = f" from {member} ({member.id})" if member else ""
            await self.bot.db.log_action(ctx.guild.id, "clear", ctx.author.id, ctx.author.id, f"Cleared {len(deleted)} messages{target}")
        except discord.Forbidden:
            await ctx.send(embed=create_error_embed("I don't have permission to delete messages."))
        except discord.HTTPException:
            await ctx.send(embed=create_error_embed("Failed to delete messages. Messages might be too old."))

    @commands.command(name='pin')
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def pin(self, ctx, message_id: int):
        """Pin a message by ID"""
        try:
            message = await ctx.channel.fetch_message(message_id)
            await message.pin()
            await ctx.send(embed=create_success_embed("Message pinned successfully!"), delete_after=3)
        except discord.NotFound:
            await ctx.send(embed=create_error_embed("Message not found."))
        except discord.Forbidden:
            await ctx.send(embed=create_error_embed("I don't have permission to pin messages."))
        except discord.HTTPException:
            await ctx.send(embed=create_error_embed("Failed to pin message. Channel might have too many pinned messages."))
    
    @commands.command(name='unpin')
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def unpin(self, ctx, message_id: int):
        """Unpin a message by ID"""
        try:
            message = await ctx.channel.fetch_message(message_id)
            await message.unpin()
            await ctx.send(embed=create_success_embed("Message unpinned successfully!"), delete_after=3)
        except discord.NotFound:
            await ctx.send(embed=create_error_embed("Message not found."))
        except discord.Forbidden:
            await ctx.send(embed=create_error_embed("I don't have permission to unpin messages."))
    
    @commands.command(name='announce')
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def announce(self, ctx, channel: discord.TextChannel, *, message: str):
        """Send an announcement to a channel"""
        embed = discord.Embed(
            title="📢 Announcement",
            description=message,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Announced by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        
        try:
            await channel.send(embed=embed)
            await ctx.send(embed=create_success_embed(f"Announcement sent to {channel.mention}!"))
        except discord.Forbidden:
            await ctx.send(embed=create_error_embed(f"I don't have permission to send messages in {channel.mention}."))
    
    @commands.command(name='embed')
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def create_embed(self, ctx, title: str, *, description: str):
        """Create a custom embed"""
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Created by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        
        await ctx.send(embed=embed)


class ModGroup(app_commands.Group):
    """Slash commands: /mod ..."""
    def __init__(self, bot):
        super().__init__(name="mod", description="Moderation commands")
        self.bot = bot

    async def _defer(self, interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
        if interaction.response.is_done():
            return
        try:
            await interaction.response.defer(ephemeral=ephemeral)
        except Exception:
            pass

    def _max_purge_amount(self) -> int:
        try:
            return int(self.bot.config.get("moderation", {}).get("max_purge_amount", 100))
        except Exception:
            return 100

    @app_commands.command(name="purge", description="Delete messages in bulk.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 500]):
        max_amount = self._max_purge_amount()
        if amount > max_amount:
            return await interaction.response.send_message(
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
            if interaction.guild:
                await self.bot.db.log_action(
                    interaction.guild.id,
                    "purge",
                    interaction.user.id,
                    interaction.user.id,
                    f"Purged {len(deleted)} messages (slash)",
                )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=create_error_embed("I don't have permission to delete messages here."),
                ephemeral=True,
            )
        except discord.HTTPException:
            await interaction.followup.send(
                embed=create_error_embed("Failed to delete messages. Messages might be too old."),
                ephemeral=True,
            )

    @app_commands.command(name="say", description="Make the bot send a message.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def say(
        self,
        interaction: discord.Interaction,
        message: str,
        channel: discord.TextChannel | None = None,
    ):
        await self._defer(interaction, ephemeral=True)

        target_channel = channel or interaction.channel
        if target_channel is None or not isinstance(target_channel, discord.TextChannel):
            return await interaction.followup.send(
                embed=create_error_embed("This command can only target a server text channel."),
                ephemeral=True,
            )

        if interaction.guild is None:
            return await interaction.followup.send(
                embed=create_error_embed("This command can only be used in a server."),
                ephemeral=True,
            )

        me = interaction.guild.me
        if me is None:
            return await interaction.followup.send(
                embed=create_error_embed("Bot member not ready yet. Try again."),
                ephemeral=True,
            )

        perms = target_channel.permissions_for(me)
        if not (perms.view_channel and perms.send_messages):
            return await interaction.followup.send(
                embed=create_error_embed(f"I can't send messages in {target_channel.mention}."),
                ephemeral=True,
            )

        # Safety: avoid accidental @everyone/@here/role pings
        allowed_mentions = discord.AllowedMentions.none()

        try:
            sent = await target_channel.send(content=message, allowed_mentions=allowed_mentions)
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=create_error_embed("I don't have permission to send messages there."),
                ephemeral=True,
            )
        except discord.HTTPException:
            return await interaction.followup.send(
                embed=create_error_embed("Failed to send message due to a Discord API error."),
                ephemeral=True,
            )

        await interaction.followup.send(
            embed=create_success_embed(f"Sent. {sent.jump_url}"),
            ephemeral=True,
        )

    @purge.error
    async def purge_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        if isinstance(error, app_commands.MissingPermissions):
            return await send(embed=create_error_embed("You need Manage Messages permission."), ephemeral=True)
        await send(embed=create_error_embed(str(error)), ephemeral=True)

    @say.error
    async def say_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        if isinstance(error, app_commands.MissingPermissions):
            return await send(embed=create_error_embed("You need Manage Messages permission."), ephemeral=True)
        await send(embed=create_error_embed(str(error)), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Messages(bot))

    # Reload-safe: remove existing group if present, then add
    try:
        bot.tree.remove_command("mod")
    except Exception:
        pass
    bot.tree.add_command(ModGroup(bot))


async def teardown(bot):
    # Reload-safe cleanup
    try:
        bot.tree.remove_command("mod")
    except Exception:
        pass

