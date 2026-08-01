"""Persistent reminder commands and delivery worker."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands, tasks


DURATION_RE = re.compile(r"^(\d{1,6})([smhdw])$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(value: str, *, minimum: int = 1, maximum: int = 31_536_000) -> int:
    match = DURATION_RE.fullmatch(value.strip().lower())
    if not match:
        raise ValueError("Invalid duration")
    seconds = int(match.group(1)) * UNIT_SECONDS[match.group(2)]
    if not minimum <= seconds <= maximum:
        raise ValueError("Duration outside allowed range")
    return seconds


class ReminderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.database = bot.database
        self.deliver_reminders.start()

    def cog_unload(self) -> None:
        self.deliver_reminders.cancel()

    async def _create(self, interaction: discord.Interaction, due_at: datetime,
                      message: str, repeat_seconds: int | None = None) -> None:
        if not interaction.guild or not interaction.channel_id:
            await interaction.response.send_message("คำสั่งนี้ใช้ได้ภายใน Server เท่านั้น", ephemeral=True)
            return
        clean_message = message.strip()
        if not 1 <= len(clean_message) <= 1000:
            await interaction.response.send_message("ข้อความต้องมีความยาว 1–1,000 ตัวอักษร", ephemeral=True)
            return
        reminder_id = await asyncio.to_thread(
            self.database.create_reminder, interaction.user.id, interaction.guild.id,
            interaction.channel_id, clean_message, due_at, repeat_seconds,
        )
        timestamp = int(due_at.timestamp())
        repeat_text = f" • ซ้ำทุก {repeat_seconds:,} วินาที" if repeat_seconds else ""
        await interaction.response.send_message(
            embed=discord.Embed(
                title="⏰ ตั้งเตือนเรียบร้อย",
                description=f"ID `{reminder_id}` • <t:{timestamp}:F> (<t:{timestamp}:R>){repeat_text}\n\n{clean_message}",
                color=0x3498DB,
            ), ephemeral=True,
        )

    @app_commands.command(name="remind", description="ตั้งเวลาเตือนแบบถาวร เช่น 30m, 2h, 7d")
    async def remind(self, interaction: discord.Interaction, duration: str, message: str):
        try:
            seconds = parse_duration(duration)
        except ValueError:
            await interaction.response.send_message("รูปแบบเวลาไม่ถูกต้อง ใช้ `30s`, `10m`, `2h`, `7d` หรือ `2w`", ephemeral=True)
            return
        await self._create(interaction, datetime.now(timezone.utc) + timedelta(seconds=seconds), message)

    @app_commands.command(name="remind-at", description="ตั้งเตือนตามวันเวลาใน Timezone ของ Server")
    @app_commands.describe(when="รูปแบบ YYYY-MM-DD HH:MM", message="ข้อความแจ้งเตือน")
    async def remind_at(self, interaction: discord.Interaction, when: str, message: str):
        if not interaction.guild:
            await interaction.response.send_message("คำสั่งนี้ใช้ได้ภายใน Server เท่านั้น", ephemeral=True)
            return
        settings = await asyncio.to_thread(self.database.get_settings, interaction.guild.id)
        try:
            zone = ZoneInfo(settings["timezone"])
            due_at = datetime.strptime(when.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=zone).astimezone(timezone.utc)
            if due_at <= datetime.now(timezone.utc):
                raise ValueError
        except (ValueError, ZoneInfoNotFoundError):
            await interaction.response.send_message("วันเวลาไม่ถูกต้องหรือผ่านไปแล้ว ใช้รูปแบบ `YYYY-MM-DD HH:MM`", ephemeral=True)
            return
        await self._create(interaction, due_at, message)

    @app_commands.command(name="remind-every", description="ตั้งการแจ้งเตือนซ้ำแบบถาวร")
    async def remind_every(self, interaction: discord.Interaction, interval: str, message: str):
        try:
            seconds = parse_duration(interval, minimum=60)
        except ValueError:
            await interaction.response.send_message("รอบแจ้งเตือนต้องอยู่ระหว่าง 1 นาทีถึง 1 ปี", ephemeral=True)
            return
        await self._create(interaction, datetime.now(timezone.utc) + timedelta(seconds=seconds), message, seconds)

    @app_commands.command(name="reminders", description="ดูรายการแจ้งเตือนของคุณ")
    async def reminders(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        rows = await asyncio.to_thread(self.database.list_reminders, interaction.user.id, interaction.guild.id)
        text = "\n".join(
            f"`#{row['id']}` <t:{int(datetime.fromisoformat(row['due_at']).timestamp())}:R> — {row['message'][:80]}"
            for row in rows
        ) or "ยังไม่มีรายการแจ้งเตือน"
        await interaction.response.send_message(embed=discord.Embed(title="⏰ Reminder ของคุณ", description=text, color=0x3498DB), ephemeral=True)

    @app_commands.command(name="reminder-cancel", description="ยกเลิก Reminder ด้วย ID")
    async def reminder_cancel(self, interaction: discord.Interaction, reminder_id: int):
        deleted = await asyncio.to_thread(self.database.delete_reminder, reminder_id, interaction.user.id)
        await interaction.response.send_message("✅ ยกเลิกแล้ว" if deleted else "ไม่พบ Reminder นี้หรือไม่ใช่ของคุณ", ephemeral=True)

    @tasks.loop(seconds=15)
    async def deliver_reminders(self):
        rows = await asyncio.to_thread(self.database.due_reminders, datetime.now(timezone.utc))
        for row in rows:
            channel = self.bot.get_channel(row["channel_id"])
            if channel is None:
                continue
            try:
                user = self.bot.get_user(row["user_id"])
                mention = user.mention if user else f"<@{row['user_id']}>"
                await channel.send(
                    content=mention,
                    embed=discord.Embed(title="🔔 ถึงเวลาแล้ว", description=row["message"], color=0xE67E22),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except (discord.Forbidden, discord.HTTPException):
                continue
            repeat = row["repeat_seconds"]
            next_due = datetime.now(timezone.utc) + timedelta(seconds=repeat) if repeat else None
            await asyncio.to_thread(self.database.finish_reminder, row["id"], repeat, next_due)

    @deliver_reminders.before_loop
    async def before_delivery(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ReminderCog(bot))
