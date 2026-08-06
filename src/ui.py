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


NOTICE_TITLES = {
    EmbedColor.SUCCESS: "✅ ดำเนินการเรียบร้อย",
    EmbedColor.WARNING: "⚠️ มีเรื่องให้ตรวจสอบ",
    EmbedColor.ERROR: "❌ ดำเนินการไม่สำเร็จ",
    EmbedColor.INFO: "ℹ️ แจ้งให้ทราบ",
}

NOTICE_EMOJI_PREFIXES = (
    "✅ ", "⚠️ ", "❌ ", "😅 ", "🎁 ", "🎧 ", "🎵 ",
    "⏸️ ", "▶️ ", "⏭️ ", "👋 ", "🔊 ", "🔁 ", "🔀 ",
    "🗑️ ", "🧹 ", "🛠️ ",
)


def truncate_text(value: str, limit: int) -> str:
    """Fit user or API text into a Discord component limit."""
    if limit < 2:
        raise ValueError("limit must be at least 2")
    clean_value = str(value).strip()
    if len(clean_value) <= limit:
        return clean_value
    return clean_value[: limit - 1].rstrip() + "…"


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
    clean_message = message.strip()
    for prefix in NOTICE_EMOJI_PREFIXES:
        if clean_message.startswith(prefix):
            clean_message = clean_message.removeprefix(prefix)
            break
    try:
        normalized_color = EmbedColor(color)
    except ValueError:
        normalized_color = EmbedColor.INFO
    title = NOTICE_TITLES.get(normalized_color, NOTICE_TITLES[EmbedColor.INFO])
    return make_embed(
        bot,
        section,
        title=title,
        description=clean_message,
        color=color,
    )
