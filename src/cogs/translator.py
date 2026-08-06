"""Translation slash commands."""

import discord
from discord import app_commands
from discord.ext import commands

from ..services.translation import TranslationService, TranslationServiceError
from ..ui import EmbedColor, make_embed


class TranslatorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.translation_service = TranslationService(bot.external_http)

    @app_commands.command(
        name="translate",
        description="แปลข้อความเป็นภาษาที่ต้องการด้วย Google Translate",
    )
    @app_commands.describe(
        text="ข้อความที่ต้องการแปล",
        to_language="ภาษาปลายทาง (ค่าเริ่มต้น: English)",
    )
    @app_commands.choices(
        to_language=[
            app_commands.Choice(name="English (อังกฤษ)", value="en"),
            app_commands.Choice(name="Thai (ไทย)", value="th"),
            app_commands.Choice(name="Japanese (ญี่ปุ่น)", value="ja"),
            app_commands.Choice(name="Korean (เกาหลี)", value="ko"),
            app_commands.Choice(name="Chinese (จีน)", value="zh-CN"),
            app_commands.Choice(name="French (ฝรั่งเศส)", value="fr"),
            app_commands.Choice(name="German (เยอรมัน)", value="de"),
            app_commands.Choice(name="Spanish (สเปน)", value="es"),
            app_commands.Choice(name="Russian (รัสเซีย)", value="ru"),
        ]
    )
    async def translate(
        self,
        interaction: discord.Interaction,
        text: str,
        to_language: str = "en",
    ):
        await interaction.response.defer(thinking=True)

        try:
            translated_text, detected_language = (
                await self.translation_service.translate(text, to_language)
            )
        except TranslationServiceError:
            embed = make_embed(
                self.bot,
                "Translate",
                title="😅 รอบนี้แปลไม่สำเร็จ",
                description=(
                    "ตอนนี้บริการแปลภาษาเงียบไปนิดนึง "
                    "พักแป๊บแล้วลองส่งมาใหม่อีกทีนะ"
                ),
                color=EmbedColor.ERROR,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = make_embed(
            self.bot,
            "Translate",
            title="🌐 แปลให้แล้วนะ",
            description=(
                f"`{detected_language.upper()}` "
                f"➡️ `{to_language.upper()}`"
            ),
            color=EmbedColor.PRIMARY,
        )
        embed.add_field(
            name="📥 ต้นฉบับ",
            value=f"> {text}",
            inline=False,
        )
        embed.add_field(
            name="✨ คำแปล",
            value=translated_text,
            inline=False,
        )
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(TranslatorCog(bot))
