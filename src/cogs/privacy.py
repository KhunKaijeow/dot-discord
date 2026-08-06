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
        f"Price Alert `{counts['alerts']}` รายการ\n"
        f"Saved Playlist `{counts['playlists']}` รายการ "
        f"(`{counts['playlist_tracks']}` เพลง)"
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
            title="🗂️ ข้อมูลที่ผมจำไว้ให้คุณ",
            description=(
                f"{format_counts(counts)}\n\n"
                "ข้อมูลชุดนี้รวมทุก Server ที่คุณใช้บอท และมีเพียงคุณที่เห็นข้อความนี้\n"
                "ประวัติ AI และคิวเพลงเป็นข้อมูลชั่วคราวต่อห้อง จึงไม่รวมในรายการนี้"
            ),
            color=EmbedColor.INFO,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="my-data-delete",
        description="ลบ Reminder, Price Alert และ Saved Playlist ทั้งหมดของคุณ",
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
            title="✅ ล้างข้อมูลส่วนตัวให้แล้ว",
            description=(
                f"{format_counts(removed)}\n\n"
                "ลบข้อมูลถาวรเสร็จแล้วและย้อนกลับไม่ได้นะ "
                "ส่วนประวัติ AI และคิวเพลงเป็นข้อมูลชั่วคราวต่อห้อง"
            ),
            color=EmbedColor.SUCCESS,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(PrivacyCog(bot))
