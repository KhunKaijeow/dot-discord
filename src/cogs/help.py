"""Interactive command directory for Javis."""

from __future__ import annotations

from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from ..ui import EmbedColor, make_embed


@dataclass(frozen=True, slots=True)
class HelpCategory:
    key: str
    label: str
    emoji: str
    summary: str
    commands: tuple[tuple[str, str], ...]


HELP_CATEGORIES = (
    HelpCategory(
        "ai",
        "AI และเครื่องมือภาษา",
        "✨",
        "ถาม AI สร้างภาพ แปลภาษา และใช้เครื่องมือกับข้อความ",
        (
            ("/ask", "ถามหรือคุยต่อเนื่องกับ Typhoon AI"),
            ("/reset-chat", "ล้างประวัติ AI ของห้องปัจจุบัน"),
            ("/draw", "สร้างภาพจากข้อความด้วย AI"),
            ("/translate", "แปลข้อความเป็นภาษาที่เลือก"),
            ("Apps → AI", "คลิกขวาข้อความเพื่อสรุป แปลไทย หรืออธิบาย"),
        ),
    ),
    HelpCategory(
        "music",
        "เพลงและเพลย์ลิสต์",
        "🎵",
        "เล่นเพลง จัดการคิว และบันทึกเพลย์ลิสต์ส่วนตัว",
        (
            ("/play", "เล่นจากชื่อเพลง, YouTube หรือ Spotify"),
            ("/pause · /resume · /skip", "พัก เล่นต่อ หรือข้ามเพลง"),
            ("/queue · /now-playing", "ดูคิวและเพลงที่กำลังเล่น"),
            ("/volume · /loop · /shuffle", "ปรับเสียง เล่นซ้ำ และสุ่มคิว"),
            ("/remove · /clear-queue · /stop", "ลบเพลง ล้างคิว หรือหยุดเล่น"),
            ("/playlist-save · /playlist-load", "บันทึกหรือโหลดเพลย์ลิสต์"),
            ("/playlist-list · /playlist-delete", "ดูหรือลบเพลย์ลิสต์ส่วนตัว"),
        ),
    ),
    HelpCategory(
        "market",
        "ตลาดและการแจ้งเตือนราคา",
        "📈",
        "ดูหุ้น คริปโต ทองคำ กราฟ และตั้งเงื่อนไขราคา",
        (
            ("/stock · /stock-popular", "ดูราคาหุ้นหรือรายชื่อหุ้นยอดนิยม"),
            ("/crypto", "ดูราคาและกราฟคริปโต"),
            ("/gold · /gold-analysis", "ดูราคาและวิเคราะห์ทองคำ"),
            ("/price-alert add", "ตั้งแจ้งเตือนเมื่อราคาสูงหรือต่ำกว่าเป้า"),
            ("/price-alert list · remove", "ดูหรือลบ Price Alert"),
        ),
    ),
    HelpCategory(
        "information",
        "ข่าวและข้อมูลประจำวัน",
        "🌤️",
        "เช็กข่าว อากาศ เกม ดวง และสีประจำวัน",
        (
            ("/news", "ดูข่าวล่าสุดหรือค้นตามหัวข้อ"),
            ("/weather", "ดูสภาพอากาศตามเมือง"),
            ("/valorant-status", "ตรวจสถานะเซิร์ฟเวอร์ Valorant"),
            ("/horoscope", "ดูดวงรายวันครบ 12 ราศี"),
            ("/lucky-shirt", "ดูสีประจำวันตามธรรมเนียมไทย"),
        ),
    ),
    HelpCategory(
        "reminders",
        "Reminder",
        "⏰",
        "ตั้ง ดู และยกเลิกการแจ้งเตือนแบบครั้งเดียวหรือทำซ้ำ",
        (
            ("/remind", "ตั้งเตือนหลังเวลาที่กำหนด เช่น 10m"),
            ("/remind-at", "ตั้งเตือนตามวันและเวลา"),
            ("/remind-every", "ตั้งแจ้งเตือนแบบทำซ้ำ"),
            ("/reminders", "ดู Reminder ที่ยังทำงานอยู่"),
            ("/reminder-cancel", "ยกเลิก Reminder ด้วย ID"),
        ),
    ),
    HelpCategory(
        "automation",
        "ระบบอัตโนมัติ",
        "🔔",
        "ตั้ง Dashboard, Digest และห้องรับการแจ้งเตือน",
        (
            ("/dashboard-setup · update · disable", "จัดการ Daily Dashboard"),
            ("/digest setup · preview", "ตั้งค่าและดูตัวอย่าง Morning Digest"),
            ("/digest status · disable", "ดูสถานะหรือปิด Morning Digest"),
            ("/deals-setup · check · disable", "จัดการแจ้งเตือนเกมแจกฟรี"),
            ("/x-setup · status · disable", "จัดการแจ้งเตือน sheapgamer"),
        ),
    ),
    HelpCategory(
        "management",
        "การตั้งค่าและความเป็นส่วนตัว",
        "⚙️",
        "ตรวจสถานะ ตั้งค่า Server และจัดการข้อมูลของคุณ",
        (
            ("/settings", "เปิดแผงตั้งค่าสำหรับผู้ดูแล Server"),
            ("/setup-check", "ตรวจ permission, config และ runtime"),
            ("/bot-status", "ดู latency, uptime และสถานะระบบ"),
            ("/my-data", "ดูจำนวนข้อมูลส่วนตัวที่บอทบันทึก"),
            ("/my-data-delete", "ลบข้อมูลส่วนตัวที่บอทบันทึก"),
        ),
    ),
)

CATEGORIES_BY_KEY = {category.key: category for category in HELP_CATEGORIES}


def build_help_embed(bot, category_key: str | None = None) -> discord.Embed:
    """Build the overview or one category page."""
    if category_key is None:
        embed = make_embed(
            bot,
            "Help",
            title="👋 ให้ผมช่วยอะไรดี?",
            description=(
                "เลือกหมวดจากเมนูด้านล่างเพื่อดูคำสั่งทั้งหมด\n"
                "เริ่มพิมพ์ `/` ในช่องแชทเพื่อดูตัวเลือกและรายละเอียดของแต่ละคำสั่ง"
            ),
            color=EmbedColor.PRIMARY,
        )
        for category in HELP_CATEGORIES:
            embed.add_field(
                name=f"{category.emoji} {category.label}",
                value=category.summary,
                inline=False,
            )
        return embed

    category = CATEGORIES_BY_KEY[category_key]
    command_lines = "\n".join(
        f"**`{command}`** — {description}"
        for command, description in category.commands
    )
    return make_embed(
        bot,
        "Help",
        title=f"{category.emoji} {category.label}",
        description=f"{category.summary}\n\n{command_lines}",
        color=EmbedColor.INFO,
    )


class HelpCategorySelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label="ภาพรวม",
                value="overview",
                emoji="🏠",
                description="กลับไปหน้ารวมหมวดคำสั่ง",
            ),
            *[
                discord.SelectOption(
                    label=category.label,
                    value=category.key,
                    emoji=category.emoji,
                    description=category.summary,
                )
                for category in HELP_CATEGORIES
            ],
        ]
        super().__init__(
            placeholder="เลือกหมวดคำสั่ง…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        category_key = None if self.values[0] == "overview" else self.values[0]
        await interaction.response.edit_message(
            embed=build_help_embed(self.view.bot, category_key),
            view=self.view,
        )


class HelpView(discord.ui.View):
    def __init__(self, bot, owner_id: int) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.owner_id = owner_id
        self.add_item(HelpCategorySelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "เปิด `/help` ของคุณเองเพื่อเลือกหมวดคำสั่งนะ",
            ephemeral=True,
        )
        return False


class HelpCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="ดูรายการคำสั่งและวิธีใช้งานบอท")
    async def help_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            embed=build_help_embed(self.bot),
            view=HelpView(self.bot, interaction.user.id),
            ephemeral=True,
        )


async def setup(bot) -> None:
    await bot.add_cog(HelpCog(bot))
