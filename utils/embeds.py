"""
Embed utility functions for creating consistent Discord embeds
"""
import discord
from typing import Optional


class EmbedFactory:
    """Factory class for creating common embed types"""
    
    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        """Create a success embed (green)"""
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green()
        )
    
    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        """Create an error embed (red)"""
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red()
        )
    
    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        """Create an info embed (blue)"""
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue()
        )
    
    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        """Create a warning embed (orange)"""
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.orange()
        )
    
    @staticmethod
    def moderation_action(
        action: str,
        moderator: discord.Member,
        target: discord.Member,
        reason: Optional[str] = None
    ) -> discord.Embed:
        """Create a moderation action embed"""
        embed = discord.Embed(
            title=f"Moderation: {action.title()}",
            color=discord.Color.orange()
        )
        embed.add_field(name="Target", value=target.mention, inline=True)
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        return embed


def create_success_embed(message: str) -> discord.Embed:
    """Create a simple success embed"""
    return discord.Embed(
        description=f"✅ {message}",
        color=discord.Color.green()
    )


def create_error_embed(message: str) -> discord.Embed:
    """Create a simple error embed"""
    return discord.Embed(
        description=f"❌ {message}",
        color=discord.Color.red()
    )


def create_info_embed(message: str) -> discord.Embed:
    """Create a simple info embed"""
    return discord.Embed(
        description=f"ℹ️ {message}",
        color=discord.Color.blue()
    )


def create_mod_embed(
    action: str,
    moderator: discord.Member,
    target: discord.Member,
    reason: Optional[str] = None
) -> discord.Embed:
    """Create a moderation action embed"""
    return EmbedFactory.moderation_action(action, moderator, target, reason)

