"""
Setup Cog (SLASH COMMANDS)
Handles server configuration
"""
import discord
from discord.ext import commands
from discord import app_commands
from utils.embeds import create_success_embed, create_error_embed


class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _defer(self, interaction: discord.Interaction, *, ephemeral: bool = True) -> None:
        if interaction.response.is_done():
            return
        try:
            await interaction.response.defer(ephemeral=ephemeral)
        except Exception:
            pass

    setup = app_commands.Group(name="setup", description="Server setup & configuration")

    @setup.command(name="logchannel", description="Set the mod log channel.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def setup_logchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self._defer(interaction, ephemeral=True)
        await self.bot.db.update_server_setting(interaction.guild.id, "log_channel", channel.id)
        await interaction.followup.send(embed=create_success_embed(f"Mod log channel set to {channel.mention}!"), ephemeral=True)

    @setup.command(name="welcomechannel", description="Set the welcome channel.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def setup_welcomechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self._defer(interaction, ephemeral=True)
        await self.bot.db.update_server_setting(interaction.guild.id, "welcome_channel", channel.id)
        await interaction.followup.send(embed=create_success_embed(f"Welcome channel set to {channel.mention}!"), ephemeral=True)

    @setup.command(name="config", description="View current server configuration.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def setup_config(self, interaction: discord.Interaction):
        await self._defer(interaction, ephemeral=True)
        settings = await self.bot.db.get_server_settings(interaction.guild.id)

        log_channel = interaction.guild.get_channel(settings.get("log_channel")) if settings.get("log_channel") else None
        welcome_channel = interaction.guild.get_channel(settings.get("welcome_channel")) if settings.get("welcome_channel") else None

        embed = discord.Embed(title="⚙️ Server Configuration", color=discord.Color.blue())
        embed.add_field(name="Mod Log Channel", value=(log_channel.mention if log_channel else "Not set"), inline=False)
        embed.add_field(name="Welcome Channel", value=(welcome_channel.mention if welcome_channel else "Not set"), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message

        if isinstance(error, app_commands.CommandInvokeError) and getattr(error, "original", None):
            error = error.original  # type: ignore[assignment]

        if isinstance(error, app_commands.MissingPermissions):
            return await send(embed=create_error_embed("You need Administrator permission."), ephemeral=True)

        await send(embed=create_error_embed(str(error)), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
