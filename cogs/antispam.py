from __future__ import annotations

import discord
from discord.ext import commands
from datetime import datetime, timedelta
from collections import defaultdict, deque

from utils.embeds import create_error_embed


class AntiSpam(commands.Cog):
    """
    Anti-spam system:
    - Always deletes spam messages immediately
    - Keyword/link/invite spam => instant delete
    - Rate spam + duplicate spam => delete
    - Strike escalation:
        1..warn_before_timeout => warn (DM)
        > warn_before_timeout => timeout (DM)
    - Strikes reset after N minutes of clean behavior
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # message rate tracking: (guild_id, user_id) -> deque[timestamp]
        self.msg_times: dict[tuple[int, int], deque[datetime]] = defaultdict(deque)

        # duplicate tracking: (guild_id, user_id) -> deque[(content, timestamp)]
        self.msg_history: dict[tuple[int, int], deque[tuple[str, datetime]]] = defaultdict(deque)

        # strikes: (guild_id, user_id) -> (count, last_strike_time)
        self.strikes: dict[tuple[int, int], tuple[int, datetime]] = {}

    # -------------------------
    # Config helpers
    # -------------------------
    def _cfg(self) -> dict:
        return self.bot.config.get("antispam", {})

    def _enabled(self) -> bool:
        # default True if not present
        return bool(self._cfg().get("enabled", True))

    def _reset_after(self) -> int:
        return int(self._cfg().get("strikes_reset_minutes", 10))

    def _warn_before_timeout(self) -> int:
        return int(self._cfg().get("warn_before_timeout", 2))

    def _timeout_minutes(self) -> int:
        return int(self._cfg().get("timeout_minutes", 5))

    # Keywords / links to delete instantly
    def _spam_keywords(self) -> list[str]:
        # You can add more here
        return [
            "scam",
            "free nitro",
            "airdrop",
            "claim",
            "giveaway",
            "discord.gg/",
            "discord.com/invite",
            "http://",
            "https://",
        ]

    # -------------------------
    # Actions
    # -------------------------
    async def _delete(self, message: discord.Message) -> None:
        try:
            await message.delete()
            print(f"[ANTISPAM] ✅ Deleted: {message.author} -> {message.content!r}")
        except discord.Forbidden:
            print("[ANTISPAM] ❌ Forbidden: Missing Manage Messages (or channel perms/role order).")
        except discord.NotFound:
            print("[ANTISPAM] ⚠️ NotFound: Message already deleted.")
        except discord.HTTPException as e:
            print(f"[ANTISPAM] ❌ HTTPException while deleting: {e}")
        except Exception as e:
            print(f"[ANTISPAM] ❌ Unknown delete error: {e}")

    async def _log_warn(self, guild_id: int, user_id: int, reason: str) -> None:
        bot_user_id = self.bot.user.id if self.bot.user else 0
        try:
            await self.bot.db.add_warning(guild_id, user_id, bot_user_id, reason)
        except Exception:
            pass
        try:
            await self.bot.db.log_action(guild_id, "antispam_warn", user_id, bot_user_id, reason)
        except Exception:
            pass

    async def _log_timeout(self, guild_id: int, user_id: int, reason: str, minutes: int) -> None:
        bot_user_id = self.bot.user.id if self.bot.user else 0
        try:
            await self.bot.db.log_action(guild_id, "antispam_timeout", user_id, bot_user_id, f"{reason} | {minutes}m")
        except Exception:
            pass

    async def _timeout(self, member: discord.Member, minutes: int, reason: str) -> None:
        try:
            await member.timeout(timedelta(minutes=minutes), reason=reason)
            print(f"[ANTISPAM] ⏳ Timed out {member} for {minutes}m | {reason}")
        except discord.Forbidden:
            print("[ANTISPAM] ❌ Forbidden: Missing Timeout permissions (Moderate Members).")
        except Exception as e:
            print(f"[ANTISPAM] ❌ Timeout error: {e}")

    # -------------------------
    # Strike tracking
    # -------------------------
    def _get_strike(self, key: tuple[int, int]) -> int:
        reset_minutes = self._reset_after()
        now = datetime.utcnow()

        if key not in self.strikes:
            return 0

        count, last_time = self.strikes[key]
        if (now - last_time).total_seconds() > reset_minutes * 60:
            self.strikes.pop(key, None)
            return 0

        return count

    def _add_strike(self, key: tuple[int, int]) -> int:
        now = datetime.utcnow()
        current = self._get_strike(key)
        new_count = current + 1
        self.strikes[key] = (new_count, now)
        return new_count

    # -------------------------
    # Spam detection
    # -------------------------
    def _is_keyword_spam(self, content: str) -> bool:
        if not content:
            return False
        c = content.lower()
        return any(k in c for k in self._spam_keywords())

    def _is_rate_spam(self, key: tuple[int, int]) -> bool:
        cfg = self._cfg()
        max_messages = int(cfg.get("max_messages", 6))
        per_seconds = int(cfg.get("per_seconds", 8))

        now = datetime.utcnow()
        q = self.msg_times[key]
        q.append(now)

        while q and (now - q[0]).total_seconds() > per_seconds:
            q.popleft()

        return len(q) >= max_messages

    def _is_duplicate_spam(self, key: tuple[int, int], content: str) -> bool:
        cfg = self._cfg()
        window = int(cfg.get("duplicate_window_seconds", 12))
        max_dups = int(cfg.get("max_duplicates", 3))

        now = datetime.utcnow()
        h = self.msg_history[key]
        h.append((content, now))

        while h and (now - h[0][1]).total_seconds() > window:
            h.popleft()

        if not content.strip():
            return False

        dup_count = sum(1 for c, _t in h if c.strip() == content.strip())
        return dup_count >= max_dups

    # -------------------------
    # Listener
    # -------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self._enabled():
            return
        if not message.guild:
            return
        if message.author.bot:
            return
        if not isinstance(message.author, discord.Member):
            return

        member = message.author

        # Admin bypass
        if member.guild_permissions.administrator:
            return

        guild_id = message.guild.id
        key = (guild_id, member.id)

        content = (message.content or "").strip()

        # DEBUG proof (leave for now; remove later)
        print("CONTENT:", repr(content))

        # ✅ KEYWORD/LINK SPAM CHECK FIRST (instant)
        keyword_spam = self._is_keyword_spam(content)

        # Other spam types
        rate_spam = self._is_rate_spam(key)
        dup_spam = self._is_duplicate_spam(key, content)

        if not (keyword_spam or rate_spam or dup_spam):
            return

        # Always delete
        await self._delete(message)

        # Strike escalation
        strikes = self._add_strike(key)
        warn_before_timeout = self._warn_before_timeout()

        reasons = []
        if keyword_spam:
            reasons.append("keyword/link spam")
        if rate_spam:
            reasons.append("rate spam")
        if dup_spam:
            reasons.append("duplicate spam")
        reason_text = " + ".join(reasons) if reasons else "spam"

        # WARN
        if strikes <= warn_before_timeout:
            await self._log_warn(guild_id, member.id, f"AntiSpam: {reason_text} (strike {strikes})")
            try:
                await member.send(
                    embed=create_error_embed(
                        f"Anti-spam warning ({strikes}/{warn_before_timeout})",
                        f"Your message was removed for: **{reason_text}**.\nNext offenses may result in a timeout."
                    )
                )
            except Exception:
                pass
            return

        # TIMEOUT
        minutes = self._timeout_minutes()
        await self._timeout(member, minutes, f"AntiSpam: {reason_text} (strike {strikes})")
        await self._log_timeout(guild_id, member.id, f"AntiSpam: {reason_text} (strike {strikes})", minutes)

        try:
            await member.send(
                embed=create_error_embed(
                    "You have been timed out",
                    f"Reason: **{reason_text}**\nDuration: **{minutes} minutes**"
                )
            )
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiSpam(bot))
