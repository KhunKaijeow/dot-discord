"""Operational status command without exposing secrets or internal errors."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import platform

import discord
from discord import app_commands
from discord.ext import commands

from .music import FFMPEG_EXECUTABLE, YTDL_OPTIONS, music_states
from ..ui import EmbedColor, make_embed


class HealthCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="bot-status", description="ดูสถานะและความพร้อมของบอท")
    async def status_command(self, interaction: discord.Interaction):
        uptime = datetime.now(timezone.utc) - self.bot.started_at
        counts = await asyncio.to_thread(self.bot.database.counts)
        queued = sum(len(state.queue) for state in music_states.values())
        embed = make_embed(
            self.bot,
            "Status",
            title="🩺 ทุกระบบเป็นยังไงบ้าง",
            description="ภาพรวมสถานะตอนนี้ ดูได้แบบเร็ว ๆ ตรงนี้เลย",
            color=EmbedColor.SUCCESS,
        )
        embed.add_field(name="📡 Discord", value=f"`{self.bot.latency * 1000:.0f} ms`", inline=True)
        embed.add_field(name="⏱️ ออนไลน์มาแล้ว", value=f"`{int(uptime.total_seconds() // 3600)} ชม.`", inline=True)
        embed.add_field(name="🏠 เซิร์ฟเวอร์", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="🗂️ งานที่จำไว้", value=f"Reminder `{counts['reminders']}` • Alert `{counts['alerts']}` • Digest `{counts['digests']}`", inline=False)
        embed.add_field(name="🎵 เพลง", value=f"คิว `{queued}` • FFmpeg `{'พร้อม' if FFMPEG_EXECUTABLE else 'ยังไม่พร้อม'}`", inline=False)
        if interaction.permissions.manage_guild:
            js_ready = bool(YTDL_OPTIONS["js_runtimes"])
            embed.add_field(
                name="🛠️ Runtime สำหรับแอดมิน",
                value=(
                    f"Python `{platform.python_version()}` • "
                    f"JS `{'พร้อม' if js_ready else 'ยังไม่พร้อม'}` • "
                    f"Database `v{counts['schema_version']}`"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(HealthCog(bot))
