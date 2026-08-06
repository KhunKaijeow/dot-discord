"""Shared visual language for Discord embeds."""

from enum import IntEnum

import discord


class EmbedColor(IntEnum):
    PRIMARY = 0x7C5CFC
    INFO = 0x5865F2
    SUCCESS = 0x57F287
    WARNING = 0xFEE75C
    ERROR = 0xED4245
    MUSIC = 0xEB459E
    MARKET_UP = 0x2ECC71
    MARKET_DOWN = 0xE74C3C
    GOLD = 0xF1C40F


def set_embed_author(embed: discord.Embed, bot, section: str) -> discord.Embed:
    """Apply the shared Javis author treatment and return the embed."""
    avatar_url = bot.user.display_avatar.url if bot.user else None
    embed.set_author(name=f"Javis • {section}", icon_url=avatar_url)
    return embed


def make_embed(
    bot,
    section: str,
    *,
    title: str | None = None,
    description: str | None = None,
    color: int = EmbedColor.PRIMARY,
    **kwargs,
) -> discord.Embed:
    """Create a footer-free embed with the shared Javis visual treatment."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        **kwargs,
    )
    return set_embed_author(embed, bot, section)


def make_notice_embed(
    bot,
    section: str,
    message: str,
    *,
    color: int = EmbedColor.INFO,
) -> discord.Embed:
    """Create a compact embed for a short public status or error message."""
    return make_embed(bot, section, description=message, color=color)
