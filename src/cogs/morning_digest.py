"""Per-guild scheduled morning digest built from the existing dashboard."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from .dashboard import channel_permission_problem
from ..ui import EmbedColor, make_embed, set_embed_author


logger = logging.getLogger("discord.morning_digest")


class MorningDigestCog(commands.Cog):
    digest = app_commands.Group(name="digest", description="จัดการ Morning Digest")

    def __init__(self, bot):
        self.bot = bot
        self.database = bot.database
        self.digest_worker.start()

    def cog_unload(self):
        self.digest_worker.cancel()

    async def _build(self, city: str = "Bangkok") -> discord.Embed:
        dashboard = self.bot.get_cog("DashboardCog")
        if dashboard is None:
            raise RuntimeError("Dashboard is unavailable")
        embed = await dashboard.build_dashboard_embed()
        embed.title = "☀️ Morning Digest"
        embed.description = "สรุปข้อมูลสำคัญสำหรับเริ่มต้นวันใหม่"
        set_embed_author(embed, self.bot, "Morning Digest")
        timeout = aiohttp.ClientTimeout(total=12)
        try:
            async with self.bot.external_http.get(
                f"https://wttr.in/{quote(city, safe='')}?format=j1&lang=th",
                timeout=timeout,
            ) as response:
                payload = await response.json(content_type=None) if response.status == 200 else {}
            current = payload.get("current_condition", [{}])[0]
            if current:
                embed.insert_field_at(
                    1,
                    name=f"🌤️ อากาศ • {city}",
                    value=(
                        f"อุณหภูมิ `{current.get('temp_C', 'N/A')}°C`  •  "
                        f"ความชื้น `{current.get('humidity', 'N/A')}%`  •  "
                        f"ลม `{current.get('windspeedKmph', 'N/A')} km/h`"
                    ),
                    inline=False,
                )
        except (aiohttp.ClientError, TimeoutError, ValueError, IndexError):
            pass
        return embed

    @digest.command(name="setup", description="ตั้งห้องและเวลาส่ง Morning Digest")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_digest(self, interaction: discord.Interaction, channel: discord.TextChannel,
                           hour: app_commands.Range[int, 0, 23] = 8,
                           minute: app_commands.Range[int, 0, 59] = 0,
                           timezone_name: str = "Asia/Bangkok", city: str = "Bangkok"):
        if not interaction.guild or not interaction.permissions.manage_guild:
            await interaction.response.send_message("คำสั่งนี้สำหรับผู้ดูแล Server เท่านั้น", ephemeral=True)
            return
        try:
            ZoneInfo(timezone_name.strip())
        except (ZoneInfoNotFoundError, ValueError):
            await interaction.response.send_message("Timezone ไม่ถูกต้อง เช่น `Asia/Bangkok`", ephemeral=True)
            return
        city = city.strip()
        if not 1 <= len(city) <= 80 or any(char in city for char in "\r\n<>"):
            await interaction.response.send_message("ชื่อเมืองไม่ถูกต้อง", ephemeral=True)
            return
        problem = channel_permission_problem(interaction.guild, channel)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        try:
            await asyncio.to_thread(
                self.database.update_settings, interaction.guild.id,
                digest_enabled=1, digest_channel_id=channel.id, digest_hour=hour,
                digest_minute=minute, timezone=timezone_name.strip(), digest_city=city,
                last_digest_date=None,
            )
        except Exception:
            logger.exception("Digest setup failed for guild %s", interaction.guild.id)
            await interaction.response.send_message(
                "บันทึก Morning Digest ไม่สำเร็จ ลองใหม่อีกครั้งหรือตรวจ `/setup-check`",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"✅ Morning Digest จะส่งที่ {channel.mention} เวลา `{hour:02d}:{minute:02d}` ({timezone_name})",
            ephemeral=True,
        )

    @digest.command(name="preview", description="ดูตัวอย่าง Morning Digest")
    async def preview(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            city = "Bangkok"
            if interaction.guild:
                city = (await asyncio.to_thread(self.database.get_settings, interaction.guild.id))["digest_city"]
            await interaction.followup.send(embed=await self._build(city), ephemeral=True)
        except Exception:
            logger.exception("Digest preview failed")
            await interaction.followup.send("Digest สะดุดนิดหน่อย ลองเปิดตัวอย่างใหม่อีกทีนะ", ephemeral=True)

    @digest.command(name="disable", description="ปิด Morning Digest")
    @app_commands.default_permissions(manage_guild=True)
    async def disable(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.permissions.manage_guild:
            await interaction.response.send_message("คำสั่งนี้สำหรับผู้ดูแล Server เท่านั้น", ephemeral=True)
            return
        await asyncio.to_thread(self.database.update_settings, interaction.guild.id, digest_enabled=0)
        await interaction.response.send_message("✅ ปิด Morning Digest แล้ว", ephemeral=True)

    @digest.command(name="status", description="ดูการตั้งค่า Morning Digest")
    async def status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        row = await asyncio.to_thread(self.database.get_settings, interaction.guild.id)
        channel = self.bot.get_channel(row["digest_channel_id"]) if row["digest_channel_id"] else None
        embed = make_embed(
            self.bot,
            "Morning Digest",
            title="☀️ การตั้งค่า Morning Digest",
            description=(
                "🟢 เปิดใช้งานอยู่" if row["digest_enabled"]
                else "⚪ ปิดใช้งานอยู่"
            ),
            color=EmbedColor.INFO,
        )
        embed.add_field(
            name="⏰ เวลาส่ง",
            value=f"`{row['digest_hour']:02d}:{row['digest_minute']:02d}`\n`{row['timezone']}`",
            inline=True,
        )
        embed.add_field(
            name="📍 ห้อง",
            value=channel.mention if channel else "ยังไม่ได้เลือก",
            inline=True,
        )
        embed.add_field(name="🌤️ เมือง", value=f"`{row['digest_city']}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tasks.loop(minutes=1)
    async def digest_worker(self):
        try:
            settings = await asyncio.to_thread(self.database.all_digest_settings)
        except Exception:
            logger.exception("Could not load digest schedules")
            return
        for row in settings:
            try:
                now = datetime.now(ZoneInfo(row["timezone"]))
            except (ZoneInfoNotFoundError, ValueError):
                logger.warning("Invalid digest timezone for guild %s", row["guild_id"])
                continue
            today = now.date().isoformat()
            if now.hour != row["digest_hour"] or now.minute < row["digest_minute"] or row["last_digest_date"] == today:
                continue
            channel = self.bot.get_channel(row["digest_channel_id"])
            if channel is None:
                continue
            try:
                await channel.send(embed=await self._build(row["digest_city"]))
            except (discord.Forbidden, discord.HTTPException, RuntimeError):
                logger.exception("Could not deliver digest for guild %s", row["guild_id"])
                continue
            except Exception:
                logger.exception("Digest build failed for guild %s", row["guild_id"])
                continue
            try:
                await asyncio.to_thread(
                    self.database.update_settings,
                    row["guild_id"],
                    last_digest_date=today,
                )
            except Exception:
                logger.exception("Could not mark digest delivered for guild %s", row["guild_id"])

    @digest_worker.before_loop
    async def before_digest(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(MorningDigestCog(bot))
