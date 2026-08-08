"""Self-service commands for inspecting and deleting personal data."""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from ..ui import EmbedColor, make_embed


def format_counts(counts: dict[str, int]) -> str:
    return (
        f"Reminder `{counts['reminders']}` รายการ\n"
        f"Price Alert `{counts['alerts']}` รายการ"
    )


class PrivacyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.database = bot.database

    @app_commands.command(name="my-data", description="ดูข้อมูลส่วนตัวที่บอทบันทึกไว้")
    async def my_data(self, interaction: discord.Interaction) -> None:
        counts = await asyncio.to_thread(
            self.database.user_data_counts,
            interaction.user.id,
        )
        embed = make_embed(
            self.bot,
            "Privacy",
            title="🔐 ข้อมูลของคุณ",
            description=(
                "รวมข้อมูลจากทุก Server ที่คุณใช้ Javis • หน้านี้เห็นเฉพาะคุณ"
            ),
            color=EmbedColor.INFO,
        )
        embed.add_field(name="⏰ Reminder", value=f"`{counts['reminders']}`", inline=True)
        embed.add_field(name="🔔 Price Alert", value=f"`{counts['alerts']}`", inline=True)
        embed.add_field(
            name="ℹ️ ข้อมูลชั่วคราว",
            value="ประวัติ AI ไม่ถูกเก็บในฐานข้อมูล",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="my-data-delete",
        description="ลบ Reminder และ Price Alert ทั้งหมดของคุณ",
    )
    @app_commands.describe(confirm="เลือก True เพื่อยืนยันว่าต้องการลบข้อมูลถาวร")
    async def my_data_delete(
        self,
        interaction: discord.Interaction,
        confirm: bool = False,
    ) -> None:
        if not confirm:
            counts = await asyncio.to_thread(
                self.database.user_data_counts,
                interaction.user.id,
            )
            await interaction.response.send_message(
                "รายการที่จะถูกลบถาวร:\n"
                f"{format_counts(counts)}\n\n"
                "หากต้องการดำเนินการ ให้เรียก `/my-data-delete` แล้วเลือก `confirm: True`",
                ephemeral=True,
            )
            return

        removed = await asyncio.to_thread(
            self.database.delete_user_data,
            interaction.user.id,
        )
        embed = make_embed(
            self.bot,
            "Privacy",
            title="✅ ลบข้อมูลส่วนตัวแล้ว",
            description="ลบข้อมูลถาวรเรียบร้อยและไม่สามารถย้อนกลับได้",
            color=EmbedColor.SUCCESS,
        )
        embed.add_field(name="⏰ Reminder", value=f"`{removed['reminders']}`", inline=True)
        embed.add_field(name="🔔 Price Alert", value=f"`{removed['alerts']}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(PrivacyCog(bot))
