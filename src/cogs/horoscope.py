"""Daily horoscope and Thai weekday-color slash commands."""

from datetime import datetime
import logging
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from ..config import PROKERALA_CLIENT_ID, PROKERALA_CLIENT_SECRET
from ..services.daily_color import (
    DailyColor,
    DailyColorServiceError,
    SOURCE_LICENSE_URL,
    SOURCE_PAGE_URL,
    THAI_WEEKDAYS,
    ThaiDailyColorService,
)
from ..services.prokerala import ProkeralaService, ProkeralaServiceError
from ..ui import EmbedColor, make_embed, set_embed_author


logger = logging.getLogger("javis.horoscope")
BANGKOK_TIMEZONE = ZoneInfo("Asia/Bangkok")
DISCORD_FIELD_LIMIT = 1024
PROKERALA_SOURCE_URL = "https://api.prokerala.com/"

ZODIAC_SIGNS = {
    "aries": ("♈", "ราศีเมษ", "13 เม.ย. – 13 พ.ค."),
    "taurus": ("♉", "ราศีพฤษภ", "14 พ.ค. – 13 มิ.ย."),
    "gemini": ("♊", "ราศีเมถุน", "14 มิ.ย. – 14 ก.ค."),
    "cancer": ("♋", "ราศีกรกฎ", "15 ก.ค. – 16 ส.ค."),
    "leo": ("♌", "ราศีสิงห์", "17 ส.ค. – 16 ก.ย."),
    "virgo": ("♍", "ราศีกันย์", "17 ก.ย. – 16 ต.ค."),
    "libra": ("♎", "ราศีตุล", "17 ต.ค. – 15 พ.ย."),
    "scorpio": ("♏", "ราศีพิจิก", "16 พ.ย. – 15 ธ.ค."),
    "sagittarius": ("♐", "ราศีธนู", "16 ธ.ค. – 13 ม.ค."),
    "capricorn": ("♑", "ราศีมังกร", "14 ม.ค. – 12 ก.พ."),
    "aquarius": ("♒", "ราศีกุมภ์", "13 ก.พ. – 13 มี.ค."),
    "pisces": ("♓", "ราศีมีน", "14 มี.ค. – 12 เม.ย."),
}


def truncate_field(text: str) -> str:
    if len(text) <= DISCORD_FIELD_LIMIT:
        return text
    return text[: DISCORD_FIELD_LIMIT - 3].rstrip() + "..."


def color_source_text() -> str:
    return (
        f"[Wikipedia: Colors of the day in Thailand]({SOURCE_PAGE_URL}) "
        f"([CC BY-SA 4.0]({SOURCE_LICENSE_URL}))"
    )


class HoroscopeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.horoscope_service = ProkeralaService(
            PROKERALA_CLIENT_ID,
            PROKERALA_CLIENT_SECRET,
            bot.http,
        )
        self.daily_color_service = ThaiDailyColorService(bot.http)

    @app_commands.command(
        name="horoscope",
        description="เปิดคำทำนายดวงรายวันตามราศีของคุณ",
    )
    @app_commands.describe(zodiac="เลือกราศีของคุณตามช่วงวันเกิด")
    @app_commands.choices(
        zodiac=[
            app_commands.Choice(
                name=f"{emoji} {name} ({date_range})",
                value=value,
            )
            for value, (emoji, name, date_range) in ZODIAC_SIGNS.items()
        ]
    )
    async def horoscope(self, interaction: discord.Interaction, zodiac: str):
        if not self.horoscope_service.is_configured:
            embed = make_embed(
                self.bot,
                "Horoscope",
                title="🔑 ตั้งค่า Prokerala อีกนิดนะ",
                description="ตอนนี้ยังเปิดคำทำนายไม่ได้ เพราะยังไม่ได้ใส่ Prokerala credentials นะ",
                color=EmbedColor.WARNING,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        now = datetime.now(BANGKOK_TIMEZONE)

        try:
            reading = await self.horoscope_service.get_daily_horoscope(
                zodiac,
                now,
            )
        except ProkeralaServiceError:
            logger.exception("Horoscope request failed")
            await interaction.followup.send(
                embed=make_embed(
                    self.bot,
                    "Horoscope",
                    title="😅 ดวงวันนี้ยังเดินทางมาไม่ถึง",
                    description="Prokerala เงียบไปนิดนึง รอสักครู่แล้วลองเปิดคำทำนายใหม่อีกทีนะ",
                    color=EmbedColor.ERROR,
                ),
                ephemeral=True,
            )
            return

        daily_color = await self._get_daily_color(now.weekday())
        embed = self._build_horoscope_embed(
            zodiac,
            now,
            reading,
            daily_color,
        )
        await interaction.followup.send(embed=embed)

    async def _get_daily_color(self, weekday: int) -> DailyColor | None:
        try:
            return await self.daily_color_service.get_color(weekday)
        except DailyColorServiceError:
            logger.exception("Daily color request failed")
            return None

    def _build_horoscope_embed(
        self,
        zodiac: str,
        now: datetime,
        reading: dict[str, str],
        daily_color: DailyColor | None,
    ) -> discord.Embed:
        emoji, sign_name, date_range = ZODIAC_SIGNS[zodiac]
        day_name = THAI_WEEKDAYS[now.weekday()]
        embed = discord.Embed(
            description=(
                f"คำทำนายสำหรับ **{sign_name}** ({date_range})\n"
                f"ประจำ**{day_name}ที่ {now.strftime('%d/%m/%Y')}**\n\n"
                f"🔮 {reading['general']}"
            ),
            color=daily_color.embed_color if daily_color else 0x8E44AD,
        )
        set_embed_author(embed, self.bot, f"Horoscope • {emoji} {sign_name}")
        embed.add_field(
            name="💕 ความรัก",
            value=truncate_field(reading["love"]),
            inline=False,
        )
        embed.add_field(
            name="💼 งานและการเรียน",
            value=truncate_field(reading["career"]),
            inline=False,
        )
        embed.add_field(
            name="🌿 สุขภาพ",
            value=truncate_field(reading["health"]),
            inline=False,
        )
        if daily_color:
            embed.add_field(
                name="🍀 สีประจำวัน",
                value=f"**{daily_color.color_name_th}**",
                inline=False,
            )

        sources = f"[Prokerala Astrology API]({PROKERALA_SOURCE_URL})"
        if daily_color:
            sources += f"\n{color_source_text()}"
        embed.add_field(
            name="📖 แหล่งข้อมูล",
            value=sources,
            inline=False,
        )
        embed.add_field(
            name="✨ ข้อความถึงคุณ",
            value=(
                "คำทำนายนี้มีไว้เพิ่มสีสันและกำลังใจ "
                "อ่านเอาสนุกและเก็บไว้เป็นกำลังใจของวันนี้ก็พอนะ"
            ),
            inline=False,
        )
        return embed

    @app_commands.command(
        name="lucky-shirt",
        description="ดูสีประจำวันตามธรรมเนียมไทยจากแหล่งอ้างอิง",
    )
    async def lucky_shirt(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        now = datetime.now(BANGKOK_TIMEZONE)

        try:
            daily_color = await self.daily_color_service.get_color(now.weekday())
        except DailyColorServiceError:
            logger.exception("Daily color request failed")
            await interaction.followup.send(
                embed=make_embed(
                    self.bot,
                    "Lucky Color",
                    title="😅 สียังมาไม่ถึง",
                    description="แหล่งข้อมูลเงียบไปนิดนึง รอสักครู่แล้วลองใหม่อีกทีนะ",
                    color=EmbedColor.ERROR,
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            description=(
                f"สีตามธรรมเนียมไทยประจำ**{daily_color.day_name_th}"
                f"ที่ {now.strftime('%d/%m/%Y')}** คือ\n\n"
                f"## {daily_color.color_name_th}"
            ),
            color=daily_color.embed_color,
        )
        set_embed_author(embed, self.bot, "Lucky Color • วันนี้ใส่สีอะไรดี?")
        embed.add_field(
            name="🌐 ชื่อสีจากต้นฉบับ",
            value=daily_color.source_color_name,
            inline=False,
        )
        embed.add_field(
            name="✨ หยิบมาใช้ได้ง่าย ๆ",
            value=(
                "ไม่มีเสื้อสีนี้ก็ไม่เป็นไร ลองใช้กับกระเป๋า "
                "เครื่องประดับ หรือของชิ้นเล็ก ๆ แทนก็ได้นะ"
            ),
            inline=False,
        )
        embed.add_field(
            name="📖 แหล่งข้อมูล",
            value=color_source_text(),
            inline=False,
        )
        embed.add_field(
            name="🔮 หมายเหตุ",
            value=(
                "สีประจำวันเป็นธรรมเนียมและความเชื่อส่วนบุคคล "
                "หยิบมาเพิ่มสีสันและความมั่นใจให้วันนี้ก็พอ"
            ),
            inline=False,
        )
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(HoroscopeCog(bot))
