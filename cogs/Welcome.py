"""
Welcome Cog
Posts a welcome message when a member joins.
"""
import asyncio
import discord
from discord.ext import commands


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            settings = await asyncio.wait_for(self.bot.db.get_server_settings(member.guild.id), timeout=5.0)
            channel_id = settings.get("welcome_channel")
            if not channel_id:
                return

            channel = member.guild.get_channel(channel_id)
            if not channel:
                return

            await channel.send(f"👋 Welcome {member.mention} to **{member.guild.name}**!")
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(Welcome(bot))
