from __future__ import annotations

import re
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from collections import deque, defaultdict

from utils.embeds import create_error_embed, create_success_embed


INVITE_REGEX = re.compile(r"(discord\.gg/|discord\.com/invite/|discordapp\.com/invite/)", re.IGNORECASE)

# Comprehensive URL detection regex
URL_REGEX = re.compile(
    r"(?:(?:https?|ftp)://|www\.)[^\s/$.?#].[^\s]*|"  # http://, https://, ftp://, www.
    r"(?:[a-zA-Z0-9-]+\.)+(?:com|net|org|io|gg|xyz|tk|ml|ga|cf|gq|cc|tv|me|co|us|uk|de|fr|ru|cn|jp|br|in|au|nl|pl|es|it|se|no|fi|dk|be|ch|at|cz|gr|pt|ro|hu|sk|bg|hr|lt|lv|ee|si|cy|mt|lu|is|ie|nz|za|sg|my|th|vn|id|ph|hk|kr|tw|pk|bd|eg|ng|ke|gh|tz|ug|zw|ma|dz|tn|ly|sd|et|ao|mz|zm|bw|na|zr|cm|ci|sn|ml|bf|ne|td|so|rw|bi|dj|er|cf|gw|gm|sl|lr|tg|bj|mr|cv|st|gn|mw|ls|sz|km|sc|mu|re|yt|mg|sr|gy|fk|gs|sh|pn|nu|tk|wf|pf|nc|pg|vu|sb|fj|ki|nr|tv|as|ws|to|pw|mp|gu|um|vi|pr|do|bs|jm|tt|bb|gd|lc|vc|dm|kn|ag|ms|vg|tc|ky|bm|gl|fo|sj|ax|im|je|gg|va|sm|li|mc|ad|gi|mt|al|mk|rs|ba|me|xk|am|az|ge|tr|cy|sy|iq|ir|af|pk|tj|tm|uz|kz|kg|mn|cn|kp|kr|jp|tw|hk|mo|ph|my|sg|bn|th|la|kh|vn|mm|bd|np|bt|lk|mv|io|cc|cx|nf|ck|nu|tk|to|tv|ws|ki|nr|pw|fm|mh|mp|gu|as|pr|vi|vg|tc|ky|bm|ai|ms|gp|mq|yt|re|pm|bl|mf|wf|pf|nc|vu|sb|fj|pg|nr|tv)/"  # domain.tld/
    r"[^\s]*|"
    r"(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:/[^\s]*)?",  # IP addresses
    re.IGNORECASE | re.MULTILINE
)


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # spam tracking
        self.msg_times: dict[tuple[int, int], deque[datetime]] = defaultdict(deque)   # (guild_id, user_id) -> times
        self.last_msgs: dict[tuple[int, int], deque[tuple[str, datetime]]] = defaultdict(deque)  # content history
        
        # violation tracking for progressive punishment
        self.violation_counts: dict[tuple[int, int], int] = defaultdict(int)  # (guild_id, user_id) -> count

    # -------------------------
    # Helpers
    # -------------------------
    def _is_exempt(self, guild_id: int, member: discord.Member, channel_id: int) -> bool:
        cfg_auto = self.bot.config.get("automod", {})
        exempt_roles = set(cfg_auto.get("exempt_role_ids", []))
        exempt_channels = set(cfg_auto.get("exempt_channel_ids", []))

        if channel_id in exempt_channels:
            return True

        if any(r.id in exempt_roles for r in getattr(member, "roles", [])):
            return True

        if member.guild_permissions.administrator:
            return True

        return False

    async def _timeout(self, member: discord.Member, minutes: int, reason: str):
        try:
            await member.timeout(timedelta(minutes=minutes), reason=reason)
        except Exception:
            pass

    async def _warn_and_log(self, guild_id: int, target_id: int, mod_id: int, reason: str, action_type: str):
        # mod_id = bot user id (system)
        try:
            await self.bot.db.add_warning(guild_id, target_id, mod_id, reason)
        except Exception:
            pass

        try:
            await self.bot.db.log_action(guild_id, action_type, target_id, mod_id, reason)
        except Exception:
            pass

    async def _delete_message(self, message: discord.Message):
        try:
            await message.delete()
        except Exception:
            pass

    # -------------------------
    # Core listener
    # -------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        if message.author.bot:
            return
        if not isinstance(message.author, discord.Member):
            return

        guild_id = message.guild.id
        member = message.author

        cfg_auto = self.bot.config.get("automod", {})
        cfg_spam = self.bot.config.get("antispam", {})

        if not cfg_auto.get("enabled", False) and not cfg_spam.get("enabled", False):
            return

        if self._is_exempt(guild_id, member, message.channel.id):
            return

        # Bot ID for logging as "system"
        bot_user_id = self.bot.user.id if self.bot.user else 0

        violations = []

        # -------------------------
        # AutoMod checks
        # -------------------------
        if cfg_auto.get("enabled", False):
            content = (message.content or "").strip()

            # mentions
            max_mentions = int(cfg_auto.get("max_mentions", 5))
            if max_mentions > 0:
                mention_count = len(message.mentions) + len(message.role_mentions)
                if mention_count >= max_mentions:
                    violations.append(f"Too many mentions ({mention_count} >= {max_mentions})")

            # invites
            if cfg_auto.get("block_discord_invites", True) and INVITE_REGEX.search(content):
                violations.append("Discord invite link detected")

            # links - block for members with only "Member" role
            member_role_name = cfg_auto.get("member_role_name", "Member")
            user_roles = [r for r in member.roles if r.name != "@everyone"]
            
            # If user has only the Member role (or no roles), block all links
            is_member_only = len(user_roles) == 0 or (len(user_roles) == 1 and user_roles[0].name.lower() == member_role_name.lower())
            
            if URL_REGEX.search(content):
                if is_member_only:
                    violations.append("Links not allowed for members")
                elif cfg_auto.get("block_links", False):
                    violations.append("Link detected")

            # blocked words (simple contains)
            blocked_words = [w.lower() for w in cfg_auto.get("blocked_words", []) if isinstance(w, str)]
            lowered = content.lower()
            for w in blocked_words:
                if w and w in lowered:
                    violations.append(f"Blocked word detected: {w}")
                    break

        # If automod violation → apply action
        if violations and cfg_auto.get("enabled", False):
            # Always delete the message first
            await self._delete_message(message)

            # Track violations
            key = (guild_id, member.id)
            self.violation_counts[key] += 1
            violation_count = self.violation_counts[key]

            # Progressive punishment: 1st = warn, 2nd = timeout, 3rd = kick
            if violation_count == 1:
                # 1st violation: Warn only
                await self._warn_and_log(
                    guild_id=guild_id,
                    target_id=member.id,
                    mod_id=bot_user_id,
                    reason=f"[1st Warning] {' | '.join(violations)}",
                    action_type="automod_warn"
                )
                try:
                    embed = discord.Embed(
                        title="Warning AutoMod",
                        description=f"**Violation:** {' | '.join(violations)}\n\n**Warning {violation_count}/3**\nNext violation = timeout.",
                        color=discord.Color.orange()
                    )
                    await member.send(embed=embed)
                except Exception:
                    pass

            elif violation_count == 2:
                # 2nd violation: Timeout
                timeout_minutes = int(cfg_auto.get("repeat_timeout_minutes", 10))
                await self._timeout(member, timeout_minutes, reason=f"AutoMod: 2nd violation")
                await self._warn_and_log(
                    guild_id=guild_id,
                    target_id=member.id,
                    mod_id=bot_user_id,
                    reason=f"[2nd Warning - Timeout {timeout_minutes}min] {' | '.join(violations)}",
                    action_type="automod_timeout"
                )
                try:
                    embed = discord.Embed(
                        title="Timeout AutoMod",
                        description=f"**Violation:** {' | '.join(violations)}\n\n**Warning {violation_count}/3**\nTimed out for {timeout_minutes} min.\nNext violation = kick.",
                        color=discord.Color.red()
                    )
                    await member.send(embed=embed)
                except Exception:
                    pass

            else:
                # 3rd+ violation: Kick
                try:
                    try:
                        embed = discord.Embed(
                            title="Kicked AutoMod",
                            description=f"**Violation:** {' | '.join(violations)}\n\nKicked from **{message.guild.name}** for repeated violations.",
                            color=discord.Color.dark_red()
                        )
                        await member.send(embed=embed)
                    except Exception:
                        pass
                    
                    await member.kick(reason=f"AutoMod: 3rd violation - {' | '.join(violations)}")
                    await self._warn_and_log(
                        guild_id=guild_id,
                        target_id=member.id,
                        mod_id=bot_user_id,
                        reason=f"[3rd Warning - Kicked] {' | '.join(violations)}",
                        action_type="automod_kick"
                    )
                    self.violation_counts[key] = 0
                except discord.Forbidden:
                    timeout_minutes = int(cfg_auto.get("repeat_timeout_minutes", 10))
                    await self._timeout(member, timeout_minutes, reason="AutoMod: Multiple violations")

            return  # stop here; don’t double-process as spam

        # -------------------------
        # Anti-Spam checks
        # -------------------------
        if cfg_spam.get("enabled", False):
            now = datetime.utcnow()
            key = (guild_id, member.id)

            # Rate limit
            max_messages = int(cfg_spam.get("max_messages", 6))
            per_seconds = int(cfg_spam.get("per_seconds", 8))

            times = self.msg_times[key]
            times.append(now)
            while times and (now - times[0]).total_seconds() > per_seconds:
                times.popleft()

            spam_triggered = len(times) >= max_messages

            # Duplicate spam window
            dup_window = int(cfg_spam.get("duplicate_window_seconds", 12))
            max_dups = int(cfg_spam.get("max_duplicates", 3))
            history = self.last_msgs[key]
            history.append((message.content or "", now))
            while history and (now - history[0][1]).total_seconds() > dup_window:
                history.popleft()

            # Count duplicates of the same content (ignore empty)
            content = (message.content or "").strip()
            if content:
                dup_count = sum(1 for c, _t in history if c.strip() == content)
                if dup_count >= max_dups:
                    spam_triggered = True

            if spam_triggered:
                spam_action = cfg_spam.get("spam_action", "timeout").lower()

                # delete recent message (at least the one that triggered)
                if spam_action in ("delete", "warn", "timeout"):
                    await self._delete_message(message)

                await self._warn_and_log(
                    guild_id=guild_id,
                    target_id=member.id,
                    mod_id=bot_user_id,
                    reason="Anti-spam triggered (rate/duplicate)",
                    action_type="antispam"
                )

                if spam_action == "timeout":
                    minutes = int(cfg_spam.get("spam_timeout_minutes", 5))
                    await self._timeout(member, minutes, reason="Anti-spam timeout")

                return

    # -------------------------
    # Slash controls
    # -------------------------
    @app_commands.command(name="automod", description="Control AutoMod + AntiSpam")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def automod(self, interaction: discord.Interaction, mode: str):
        mode = mode.lower().strip()

        if mode not in ("on", "off", "status"):
            return await interaction.response.send_message(
                "❌ Usage: `/automod on | off | status`",
                ephemeral=True,
            )

        if mode == "status":
            a = self.bot.config.get("automod", {}).get("enabled", False)
            s = self.bot.config.get("antispam", {}).get("enabled", False)
            return await interaction.response.send_message(
                f"🛡️ AutoMod: **{'ON' if a else 'OFF'}** | AntiSpam: **{'ON' if s else 'OFF'}**",
                ephemeral=True,
            )

        # Toggle both
        self.bot.config.setdefault("automod", {})["enabled"] = (mode == "on")
        self.bot.config.setdefault("antispam", {})["enabled"] = (mode == "on")

        await interaction.response.send_message(
            embed=create_success_embed(f"AutoMod + AntiSpam turned **{mode.upper()}**"),
            ephemeral=True,
        )

    @automod.error
    async def automod_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
