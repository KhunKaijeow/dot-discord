"""Self-service deployment and permission diagnostics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..config import (
    PROKERALA_CLIENT_ID,
    PROKERALA_CLIENT_SECRET,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    TOGETHER_API_KEY,
    TYPHOON_API_KEY,
    VALORANT_API_KEY,
)
from ..services.database_migrations import LATEST_SCHEMA_VERSION
from ..ui import EmbedColor, make_embed
from .music import EJS_AVAILABLE, FFMPEG_EXECUTABLE, YTDL_OPTIONS


logger = logging.getLogger("javis.setup_check")


@dataclass(frozen=True, slots=True)
class CheckItem:
    label: str
    ok: bool
    detail: str
    required: bool = True

    def render(self) -> str:
        icon = "✅" if self.ok else ("❌" if self.required else "⚠️")
        return f"{icon} **{self.label}:** {self.detail}"


def _is_configured(*values: str | None) -> bool:
    return all(bool(value and value.strip()) for value in values)


def permission_checks(interaction: discord.Interaction) -> list[CheckItem]:
    user_permissions = interaction.permissions
    app_permissions = interaction.app_permissions
    bot_member = interaction.guild.me if interaction.guild else None
    guild_permissions = (
        bot_member.guild_permissions if bot_member else discord.Permissions.none()
    )
    return [
        CheckItem(
            "สิทธิ์ผู้เรียก",
            user_permissions.manage_guild,
            "มี Manage Server" if user_permissions.manage_guild else "ขาด Manage Server",
        ),
        CheckItem(
            "View Channel",
            app_permissions.view_channel,
            "พร้อม" if app_permissions.view_channel else "บอทมองไม่เห็นห้องนี้",
        ),
        CheckItem(
            "Send Messages",
            app_permissions.send_messages,
            "พร้อม" if app_permissions.send_messages else "บอทส่งข้อความในห้องนี้ไม่ได้",
        ),
        CheckItem(
            "Embed Links",
            app_permissions.embed_links,
            "พร้อม" if app_permissions.embed_links else "Embed จะแสดงไม่สมบูรณ์",
        ),
        CheckItem(
            "Attach Files",
            app_permissions.attach_files,
            "พร้อม" if app_permissions.attach_files else "กราฟและรูปภาพอาจส่งไม่ได้",
            required=False,
        ),
        CheckItem(
            "Connect Voice",
            guild_permissions.connect,
            (
                "พร้อมระดับ Server"
                if guild_permissions.connect
                else "Role บอทยังไม่มีสิทธิ์ Connect"
            ),
            required=False,
        ),
        CheckItem(
            "Speak",
            guild_permissions.speak,
            "พร้อมระดับ Server" if guild_permissions.speak else "Role บอทยังไม่มีสิทธิ์ Speak",
            required=False,
        ),
    ]


def integration_checks() -> list[CheckItem]:
    spotify_ready = _is_configured(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    horoscope_ready = _is_configured(
        PROKERALA_CLIENT_ID,
        PROKERALA_CLIENT_SECRET,
    )
    return [
        CheckItem(
            "Typhoon AI",
            _is_configured(TYPHOON_API_KEY),
            "ตั้งค่าแล้ว" if TYPHOON_API_KEY else "ขาด TYPHOON_API_KEY",
        ),
        CheckItem(
            "Together AI",
            _is_configured(TOGETHER_API_KEY),
            "พร้อมวาดภาพ" if TOGETHER_API_KEY else "ยังไม่ได้ตั้งค่า",
            required=False,
        ),
        CheckItem(
            "Spotify Playlist",
            spotify_ready,
            "ตั้งค่าครบ" if spotify_ready else "ยังตั้งค่าไม่ครบ",
            required=False,
        ),
        CheckItem(
            "Horoscope",
            horoscope_ready,
            "ตั้งค่าครบ" if horoscope_ready else "ยังตั้งค่าไม่ครบ",
            required=False,
        ),
        CheckItem(
            "VALORANT",
            _is_configured(VALORANT_API_KEY),
            "ตั้งค่าแล้ว" if VALORANT_API_KEY else "ยังไม่ได้ตั้งค่า",
            required=False,
        ),
    ]


class SetupCheckCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup-check", description="ตรวจสิทธิ์ Config และความพร้อมของบอท")
    @app_commands.guild_only()
    async def setup_check(self, interaction: discord.Interaction) -> None:
        permissions = permission_checks(interaction)
        try:
            counts = await asyncio.to_thread(self.bot.database.counts)
            schema_version = int(counts["schema_version"])
            database_ok = schema_version == LATEST_SCHEMA_VERSION
            database_detail = f"schema v{schema_version}/{LATEST_SCHEMA_VERSION}"
        except Exception:
            logger.exception("Setup check could not read database status")
            database_ok = False
            database_detail = "เปิดหรืออ่านฐานข้อมูลไม่สำเร็จ"

        sync_state = self.bot.command_sync_succeeded
        core = [
            CheckItem("Database", database_ok, database_detail),
            CheckItem(
                "HTTP Client",
                self.bot.external_http.is_started,
                (
                    "connection pool พร้อม"
                    if self.bot.external_http.is_started
                    else "ยังไม่เริ่มทำงาน"
                ),
            ),
            CheckItem(
                "Slash Commands",
                sync_state is True,
                (
                    f"sync แล้ว {self.bot.command_sync_count} คำสั่ง"
                    if sync_state is True
                    else (
                        "sync ไม่สำเร็จ"
                        if sync_state is False
                        else "ยังไม่มีผลการ sync"
                    )
                ),
            ),
            CheckItem(
                "Gateway Intents",
                True,
                "Standard Intents เพียงพอสำหรับ Slash Commands ปัจจุบัน",
            ),
        ]
        runtime = [
            CheckItem(
                "FFmpeg",
                bool(FFMPEG_EXECUTABLE),
                "พร้อมเล่นเสียง" if FFMPEG_EXECUTABLE else "ไม่พบ executable",
                required=False,
            ),
        CheckItem(
            "JavaScript Runtime",
                bool(YTDL_OPTIONS["js_runtimes"]),
                (
                    "พร้อมสำหรับ YouTube"
                    if YTDL_OPTIONS["js_runtimes"]
                    else "ไม่พบ Deno/Node/QuickJS"
                ),
            required=False,
        ),
        CheckItem(
            "yt-dlp EJS",
            EJS_AVAILABLE,
            "พร้อมแก้ YouTube challenge" if EJS_AVAILABLE else "ไม่พบ yt-dlp-ejs",
            required=False,
        ),
        ]
        integrations = integration_checks()
        all_items = [*permissions, *core, *runtime, *integrations]
        failures = [item for item in all_items if item.required and not item.ok]
        warnings = [item for item in all_items if not item.required and not item.ok]

        if failures:
            title = "❌ ยังมีจุดที่ต้องแก้ก่อน"
            color = EmbedColor.ERROR
        elif warnings:
            title = "⚠️ ระบบหลักพร้อม มี Feature เสริมที่ยังไม่ครบ"
            color = EmbedColor.WARNING
        else:
            title = "✅ พร้อมใช้งานครบทุกระบบ"
            color = EmbedColor.SUCCESS

        embed = make_embed(
            self.bot,
            "Setup Check",
            title=title,
            description=(
                f"ปัญหาหลัก `{len(failures)}` จุด • คำเตือน `{len(warnings)}` จุด\n"
                "ผลตรวจนี้ไม่แสดง Token หรือ API Key"
            ),
            color=color,
        )
        embed.add_field(
            name="🔐 Permissions",
            value="\n".join(item.render() for item in permissions),
            inline=False,
        )
        embed.add_field(
            name="🧩 Core",
            value="\n".join(item.render() for item in core),
            inline=False,
        )
        embed.add_field(
            name="🎵 Voice Runtime",
            value="\n".join(item.render() for item in runtime),
            inline=False,
        )
        embed.add_field(
            name="🔌 Integrations",
            value="\n".join(item.render() for item in integrations),
            inline=False,
        )
        if failures:
            embed.add_field(
                name="🛠️ แก้ตรงไหนก่อน",
                value="\n".join(f"• {item.label}: {item.detail}" for item in failures),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(SetupCheckCog(bot))
