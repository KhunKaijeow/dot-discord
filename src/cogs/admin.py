"""Permission-gated interactive administration panel."""

from __future__ import annotations

import asyncio
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

from ..ui import EmbedColor, make_embed


logger = logging.getLogger("discord.admin")


def can_manage_guild(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return bool(
        interaction.guild
        and isinstance(member, discord.Member)
        and member.guild_permissions.manage_guild
    )


class ScheduleModal(discord.ui.Modal, title="ตั้งเวลา Morning Digest"):
    hour = discord.ui.TextInput(label="ชั่วโมง (0-23)", default="8", max_length=2)
    minute = discord.ui.TextInput(label="นาที (0-59)", default="0", max_length=2)
    timezone_name = discord.ui.TextInput(label="Timezone", default="Asia/Bangkok", max_length=64)

    def __init__(self, database, guild_id: int):
        super().__init__()
        self.database = database
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hour, minute = int(self.hour.value), int(self.minute.value)
            timezone_name = self.timezone_name.value.strip()
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError
            ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError):
            await interaction.response.send_message("เวลา/Timezone ไม่ถูกต้อง", ephemeral=True)
            return
        await asyncio.to_thread(
            self.database.update_settings, self.guild_id,
            digest_hour=hour, digest_minute=minute, timezone=timezone_name,
            last_digest_date=None,
        )
        await interaction.response.send_message("✅ บันทึกตารางเวลาแล้ว", ephemeral=True)


class SettingsView(discord.ui.View):
    def __init__(self, bot, owner_id: int, guild_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.owner_id = owner_id
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        allowed = interaction.user.id == self.owner_id and can_manage_guild(interaction)
        if not allowed:
            await interaction.response.send_message("คุณไม่มีสิทธิ์ใช้แผงควบคุมนี้", ephemeral=True)
        return allowed

    @discord.ui.button(label="ตั้งห้อง Digest ที่นี่", style=discord.ButtonStyle.primary, emoji="☀️")
    async def digest_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await asyncio.to_thread(
            self.bot.database.update_settings, self.guild_id,
            digest_channel_id=interaction.channel_id, digest_enabled=1, last_digest_date=None,
        )
        await interaction.response.send_message("✅ ตั้งห้อง Morning Digest เป็นห้องนี้แล้ว", ephemeral=True)

    @discord.ui.button(label="ตั้งห้อง Alert ที่นี่", style=discord.ButtonStyle.primary, emoji="🔔")
    async def alert_channel(self, interaction: discord.Interaction, _: discord.ui.Button):
        await asyncio.to_thread(self.bot.database.update_settings, self.guild_id, alert_channel_id=interaction.channel_id)
        await interaction.response.send_message("✅ ตั้งห้อง Alert เป็นห้องนี้แล้ว", ephemeral=True)

    @discord.ui.button(label="ตั้งเวลา", style=discord.ButtonStyle.secondary, emoji="🕗")
    async def schedule(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(ScheduleModal(self.bot.database, self.guild_id))

    @discord.ui.button(label="เปิด/ปิด Digest", style=discord.ButtonStyle.danger, emoji="⏻")
    async def toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        row = await asyncio.to_thread(self.bot.database.get_settings, self.guild_id)
        enabled = 0 if row["digest_enabled"] else 1
        if enabled and not row["digest_channel_id"]:
            await interaction.response.send_message("เลือกห้อง Digest ก่อนนะ แล้วค่อยเปิดใช้งาน", ephemeral=True)
            return
        await asyncio.to_thread(self.bot.database.update_settings, self.guild_id, digest_enabled=enabled)
        await interaction.response.send_message(f"✅ {'เปิด' if enabled else 'ปิด'} Morning Digest แล้ว", ephemeral=True)


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="settings", description="เปิดแผงตั้งค่าบอทสำหรับผู้ดูแล")
    @app_commands.default_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction):
        if not can_manage_guild(interaction):
            await interaction.response.send_message("เมนูนี้ให้ผู้ดูแลเซิร์ฟเวอร์ใช้นะ", ephemeral=True)
            return
        try:
            row = await asyncio.to_thread(self.bot.database.get_settings, interaction.guild.id)
        except Exception:
            logger.exception("Could not load guild settings for guild %s", interaction.guild.id)
            await interaction.response.send_message(
                "เปิดการตั้งค่าไม่สำเร็จ ลองเช็กสิทธิ์เขียนโฟลเดอร์ `data/` ให้หน่อยนะ",
                ephemeral=True,
            )
            return
        embed = make_embed(
            self.bot,
            "Settings",
            title="⚙️ ตั้งค่าบอทในเซิร์ฟเวอร์นี้",
            description=(
                f"**Morning Digest** {'🟢 เปิดอยู่' if row['digest_enabled'] else '⚪ ปิดอยู่'}\n"
                f"**เวลาส่ง** `{row['digest_hour']:02d}:{row['digest_minute']:02d}` • `{row['timezone']}`\n\n"
                "เลือกตั้งค่าต่อจากปุ่มด้านล่างได้เลย หน้านี้เห็นเฉพาะคุณนะ"
            ),
            color=EmbedColor.PRIMARY,
        )
        await interaction.response.send_message(
            embed=embed, view=SettingsView(self.bot, interaction.user.id, interaction.guild.id), ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
