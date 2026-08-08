"""Operational status command without exposing secrets or internal errors."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import platform

import discord
from discord import app_commands
from discord.ext import commands

from ..ui import EmbedColor, make_embed


class HealthCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="bot-status", description="ดูสถานะและความพร้อมของบอท")
    async def status_command(self, interaction: discord.Interaction):
        uptime = datetime.now(timezone.utc) - self.bot.started_at
        counts = await asyncio.to_thread(self.bot.database.counts)
        embed = make_embed(
            self.bot,
            "Status",
            title="🩺 สถานะระบบ",
            description="ข้อมูล runtime ล่าสุดของ Javis",
            color=EmbedColor.SUCCESS,
        )
        embed.add_field(name="📡 Latency", value=f"`{self.bot.latency * 1000:.0f} ms`", inline=True)
        embed.add_field(name="⏱️ Uptime", value=f"`{int(uptime.total_seconds() // 3600)} ชม.`", inline=True)
        embed.add_field(name="🏠 Servers", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(
            name="🗂️ งานอัตโนมัติ",
            value=(
                f"Reminder `{counts['reminders']}`  •  "
                f"Alert `{counts['alerts']}`  •  Digest `{counts['digests']}`"
            ),
            inline=False,
        )
        if interaction.permissions.manage_guild:
            embed.add_field(
                name="🛠️ Runtime สำหรับแอดมิน",
                value=(
                    f"Python `{platform.python_version()}` • "
                    f"Database `v{counts['schema_version']}`"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(HealthCog(bot))
