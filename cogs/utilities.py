"""
Utilities Cog
Handles utility commands like ping, info, etc.
"""
import discord
from discord.ext import commands
import time
import platform

from utils.embeds import EmbedFactory



class Utilities(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='ping')
    async def ping(self, ctx):
        """Check bot latency"""
        start_time = time.time()
        message = await ctx.send("Pinging...")
        end_time = time.time()
        
        api_latency = round(self.bot.latency * 1000, 2)
        bot_latency = round((end_time - start_time) * 1000, 2)
        
        embed = discord.Embed(
            title="🏓 Pong!",
            color=discord.Color.green()
        )
        embed.add_field(name="API Latency", value=f"{api_latency}ms", inline=True)
        embed.add_field(name="Bot Latency", value=f"{bot_latency}ms", inline=True)
        
        await message.edit(content=None, embed=embed)
    
    @commands.command(name='serverinfo', aliases=['si'])
    @commands.guild_only()
    async def serverinfo(self, ctx):
        """Display server information"""
        guild = ctx.guild
        
        embed = discord.Embed(
            title=f"{guild.name}",
            description=guild.description if guild.description else "No description",
            color=discord.Color.blue()
        )
        
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        # Basic info
        embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
        embed.add_field(name="Server ID", value=guild.id, inline=True)
        embed.add_field(name="Created At", value=discord.utils.format_dt(guild.created_at, 'F'), inline=False)
        
        # Counts
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Channels", value=len(guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        
        # Boosts
        embed.add_field(name="Boost Level", value=f"Level {guild.premium_tier}", inline=True)
        embed.add_field(name="Boosts", value=guild.premium_subscription_count, inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.command(name='userinfo', aliases=['ui'])
    @commands.guild_only()
    async def userinfo(self, ctx, member: discord.Member = None):
        """Display user information"""
        if member is None:
            member = ctx.author
        
        embed = discord.Embed(
            title=f"User Information",
            color=member.color
        )
        
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        
        embed.add_field(name="Username", value=str(member), inline=True)
        embed.add_field(name="Display Name", value=member.display_name, inline=True)
        embed.add_field(name="ID", value=member.id, inline=True)
        
        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, 'F'), inline=False)
        embed.add_field(name="Joined Server", value=discord.utils.format_dt(member.joined_at, 'F'), inline=False)
        
        # Roles
        roles = [role.mention for role in member.roles[1:]]  # Exclude @everyone
        if roles:
            embed.add_field(
                name=f"Roles ({len(roles)})",
                value=', '.join(roles[:10]) if len(roles) <= 10 else f"{', '.join(roles[:10])}... and {len(roles) - 10} more",
                inline=False
            )
        
        # Status
        status_emoji = {
            discord.Status.online: "🟢",
            discord.Status.idle: "🟡",
            discord.Status.dnd: "🔴",
            discord.Status.offline: "⚫"
        }
        embed.add_field(name="Status", value=f"{status_emoji.get(member.status, '⚫')} {str(member.status).title()}", inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.command(name='avatar', aliases=['av'])
    async def avatar(self, ctx, member: discord.Member = None):
        """Display user's avatar"""
        if member is None:
            member = ctx.author
        
        embed = discord.Embed(
            title=f"{member}'s Avatar",
            color=member.color
        )
        
        if member.avatar:
            embed.set_image(url=member.avatar.url)
            embed.add_field(name="Avatar URL", value=f"[Click here]({member.avatar.url})")
        else:
            embed.description = "This user has no custom avatar."
        
        await ctx.send(embed=embed)
    
    @commands.command(name='botinfo')
    async def botinfo(self, ctx):
        """Display bot information"""
        embed = discord.Embed(
            title="Bot Information",
            description="Discord Moderation Bot",
            color=discord.Color.blue()
        )
        
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)
        
        embed.add_field(name="Bot Name", value=self.bot.user.name, inline=True)
        embed.add_field(name="Bot ID", value=self.bot.user.id, inline=True)
        embed.add_field(name="Servers", value=len(self.bot.guilds), inline=True)
        embed.add_field(name="Users", value=sum(g.member_count for g in self.bot.guilds), inline=True)
        embed.add_field(name="Python Version", value=platform.python_version(), inline=True)
        embed.add_field(name="discord.py Version", value=discord.__version__, inline=True)
        
        await ctx.send(embed=embed)

    @commands.command(name='health')
    async def health(self, ctx):
        """Show bot health diagnostics for prefix commands"""
        # Resolve prefix from context and config
        current_prefix = getattr(ctx, 'prefix', None)
        configured_prefix = self.bot.config.get("bot", {}).get("command_prefix", "!") if hasattr(self.bot, 'config') else None

        # Intents and flags
        message_content_enabled = getattr(self.bot.intents, 'message_content', False)
        case_insensitive = getattr(self.bot, 'case_insensitive', False)

        # Loaded cogs
        loaded_cogs = list(self.bot.cogs.keys())

        embed = discord.Embed(title="Bot Health", color=discord.Color.blurple())
        embed.add_field(name="Prefix (ctx)", value=str(current_prefix), inline=True)
        embed.add_field(name="Prefix (config)", value=str(configured_prefix), inline=True)
        embed.add_field(name="Case Insensitive", value="Yes" if case_insensitive else "No", inline=True)
        embed.add_field(name="Message Content Intent", value="Enabled" if message_content_enabled else "Disabled", inline=True)
        embed.add_field(name="Loaded Cogs", value=", ".join(loaded_cogs) or "None", inline=False)

        # Channel permission quick check
        if ctx.guild:
            me = ctx.guild.me
            perms = ctx.channel.permissions_for(me)
            perms_ok = perms.view_channel and perms.send_messages
            embed.add_field(name="Channel Permissions", value=("OK" if perms_ok else "Missing read/send"), inline=True)

        await ctx.send(embed=embed)
    
    @commands.command(name='help')
    async def help_command(self, ctx, command: str = None):
        """Display help information"""
        if command:
            cmd = self.bot.get_command(command)
            if cmd:
                embed = discord.Embed(
                    title=f"Help: {cmd.name}",
                    description=cmd.help or "No description available",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Usage", value=f"`{ctx.prefix}{cmd.name} {cmd.signature}`", inline=False)
                if cmd.aliases:
                    embed.add_field(name="Aliases", value=", ".join(cmd.aliases), inline=False)
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"Command `{command}` not found.")
            return
        
        embed = discord.Embed(
            title="📚 Bot Commands",
            description=f"Use `{ctx.prefix}help <command>` for detailed information",
            color=discord.Color.blue()
        )
        
        # Moderation
        embed.add_field(
            name="⚖️ Moderation",
            value="`kick`, `ban`, `unban`, `warn`, `warnings`, `timeout`, `untimeout`, `clearwarnings`",
            inline=False
        )
        
        # Messages
        embed.add_field(
            name="💬 Messages",
            value="`purge`, `clear`, `pin`, `unpin`, `announce`, `embed`",
            inline=False
        )
        
        # Channels
        embed.add_field(
            name="📁 Channels",
            value="`createchannel`, `deletechannel`, `lockchannel`, `unlockchannel`, `slowmode`, `setchannelname`, `setchanneltopic`",
            inline=False
        )
        
        # Roles
        embed.add_field(
            name="🎭 Roles",
            value="`addrole`, `removerole`, `createrole`, `deleterole`, `rolecolor`, `rolemembers`, `roleinfo`",
            inline=False
        )
        
        # Utilities
        embed.add_field(
            name="🔧 Utilities",
            value="`ping`, `serverinfo`, `userinfo`, `avatar`, `botinfo`, `help`",
            inline=False
        )
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Utilities(bot))

