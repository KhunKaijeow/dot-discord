"""Per-guild daily market and news dashboard."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone
import json
import logging
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..ui import EmbedColor, make_embed, make_notice_embed, set_embed_author


logger = logging.getLogger("discord.dashboard")

LEGACY_DATA_FILE = Path("data/dashboard.json")
NEWS_FEED_URL = "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th"
BANGKOK_TIMEZONE = ZoneInfo("Asia/Bangkok")
DASHBOARD_UPDATE_TIME = time(hour=8, minute=0, tzinfo=BANGKOK_TIMEZONE)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
MARKET_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=12)
MARKET_SYMBOLS = {
    "Gold": "GC=F",
    "SPY": "SPY",
    "SET": "^SET",
    "USDTHB": "USDTHB=X",
}


def channel_permission_problem(
    guild: discord.Guild,
    channel: discord.TextChannel,
) -> str | None:
    """Return a user-facing problem when the bot cannot publish an embed."""
    bot_member = guild.me
    if bot_member is None:
        return "ตรวจสอบสมาชิกของบอทใน Server ไม่สำเร็จ"
    permissions = channel.permissions_for(bot_member)
    missing = []
    if not permissions.view_channel:
        missing.append("View Channel")
    if not permissions.send_messages:
        missing.append("Send Messages")
    if not permissions.embed_links:
        missing.append("Embed Links")
    if not missing:
        return None
    return f"บอทยังขาดสิทธิ์ใน {channel.mention}: {', '.join(missing)}"


def parse_chart_metric(payload: dict) -> dict[str, float]:
    """Extract the latest two valid closes from a Yahoo chart response."""
    try:
        result = payload["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        valid_closes = [float(value) for value in closes if value is not None]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError("Invalid Yahoo chart payload") from error
    if not valid_closes:
        raise ValueError("Yahoo chart has no closing prices")
    current_price = valid_closes[-1]
    previous_close = valid_closes[-2] if len(valid_closes) > 1 else current_price
    change = current_price - previous_close
    pct_change = (change / previous_close) * 100 if previous_close else 0.0
    return {
        "price": current_price,
        "change": change,
        "pct_change": pct_change,
    }


async def fetch_financial_metrics(http_client) -> dict[str, dict | None]:
    """Fetch dashboard metrics concurrently, preserving partial results."""
    async def fetch_one(name: str, symbol: str) -> tuple[str, dict | None]:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{quote(symbol, safe='')}"
        )
        try:
            async with http_client.get(
                url,
                params={"range": "5d", "interval": "1d"},
                timeout=MARKET_REQUEST_TIMEOUT,
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Yahoo chart returned HTTP %s for %s",
                        response.status,
                        symbol,
                    )
                    return name, None
                payload = await response.json(content_type=None)
            return name, parse_chart_metric(payload)
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
            logger.warning("Could not fetch dashboard metric %s", symbol, exc_info=True)
            return name, None

    results = await asyncio.gather(
        *(fetch_one(name, symbol) for name, symbol in MARKET_SYMBOLS.items())
    )
    metrics = dict(results)
    for name in MARKET_SYMBOLS:
        metrics.setdefault(name, None)
    return metrics


class DashboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.database = bot.database
        self.update_dashboard_loop.start()

    def cog_unload(self) -> None:
        self.update_dashboard_loop.cancel()

    async def _migrate_legacy_state(self) -> None:
        """Import the old single-guild JSON state when its channel is resolvable."""
        if not LEGACY_DATA_FILE.exists():
            return
        try:
            data = json.loads(LEGACY_DATA_FILE.read_text(encoding="utf-8"))
            channel_id = data.get("channel_id")
            message_id = data.get("message_id")
            channel = self.bot.get_channel(channel_id) if channel_id else None
            guild = getattr(channel, "guild", None)
            if guild is None:
                return
            settings = await asyncio.to_thread(
                self.database.get_automation_settings,
                guild.id,
            )
            if settings["dashboard_channel_id"] is None:
                await asyncio.to_thread(
                    self.database.update_automation_settings,
                    guild.id,
                    dashboard_channel_id=channel_id,
                    dashboard_message_id=message_id,
                )
                logger.info("Migrated legacy dashboard state for guild %s", guild.id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            logger.exception("Could not migrate legacy dashboard state")

    async def fetch_top_news(self) -> list[tuple[str, str]]:
        news: list[tuple[str, str]] = []
        try:
            async with self.bot.external_http.get(
                NEWS_FEED_URL,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status != 200:
                    return news
                root = ET.fromstring(await response.text())
            for item in root.findall(".//item")[:3]:
                title = item.findtext("title")
                link = item.findtext("link")
                if title and link:
                    news.append((title, link))
        except (aiohttp.ClientError, TimeoutError, ET.ParseError):
            logger.exception("Could not fetch dashboard news")
        return news

    @staticmethod
    def format_metric(name: str, prefix: str, suffix: str, data: dict | None) -> str:
        if not data:
            return f"• **{name}:** `N/A`"
        price = data["price"]
        change = data["change"]
        sign = "+" if change > 0 else ""
        icon = "📈" if change > 0 else ("📉" if change < 0 else "↔️")
        return (
            f"{icon} **{name}:** `{prefix}{price:,.2f}{suffix}` "
            f"({sign}{data['pct_change']:.2f}%)"
        )

    async def build_dashboard_embed(self) -> discord.Embed:
        metrics = await fetch_financial_metrics(self.bot.external_http)
        finance_text = "\n".join(
            (
                self.format_metric("Gold · GC=F", "$", " / oz", metrics.get("Gold")),
                self.format_metric("USD/THB", "", " THB", metrics.get("USDTHB")),
                self.format_metric("S&P 500 · SPY", "$", "", metrics.get("SPY")),
                self.format_metric("SET Index · ^SET", "", "", metrics.get("SET")),
            )
        )
        headlines = await self.fetch_top_news()
        news_text = (
            "\n".join(
                f"{index}. [{title[:85]}]({link})"
                for index, (title, link) in enumerate(headlines, 1)
            )
            or "• *ยังไม่มีข้อมูลข่าวในตอนนี้*"
        )
        now = datetime.now(timezone.utc)
        embed = discord.Embed(
            title="📊 Daily Dashboard",
            description=f"ตลาดและข่าวสำคัญ • อัปเดต <t:{int(now.timestamp())}:R>",
            color=EmbedColor.PRIMARY,
            timestamp=now,
        )
        embed.add_field(name="📈 ภาพรวมตลาด", value=finance_text, inline=False)
        embed.add_field(name="📰 ข่าวล่าสุด", value=news_text, inline=False)
        return set_embed_author(embed, self.bot, "Daily Dashboard")

    async def _update_saved_dashboard(
        self,
        settings: dict,
        embed: discord.Embed,
    ) -> None:
        guild_id = settings["guild_id"]
        channel = self.bot.get_channel(settings["dashboard_channel_id"])
        if channel is None:
            logger.warning("Dashboard channel is unavailable for guild %s", guild_id)
            return
        try:
            message = await channel.fetch_message(settings["dashboard_message_id"])
            await message.edit(embed=embed)
        except discord.NotFound:
            message = await channel.send(embed=embed)
            await asyncio.to_thread(
                self.database.update_automation_settings,
                guild_id,
                dashboard_message_id=message.id,
            )
            logger.info("Recreated dashboard for guild %s", guild_id)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Could not update dashboard for guild %s", guild_id)

    @tasks.loop(time=DASHBOARD_UPDATE_TIME)
    async def update_dashboard_loop(self) -> None:
        try:
            settings = await asyncio.to_thread(
                self.database.configured_automation_settings,
                "dashboard_channel_id",
            )
            settings = [
                row for row in settings
                if row["dashboard_message_id"] is not None
            ]
            if not settings:
                return
            embed = await self.build_dashboard_embed()
            for row in settings:
                await self._update_saved_dashboard(row, embed)
        except Exception:
            logger.exception("Dashboard worker cycle failed")

    @update_dashboard_loop.before_loop
    async def before_update_dashboard_loop(self) -> None:
        await self.bot.wait_until_ready()
        await self._migrate_legacy_state()

    @app_commands.command(name="dashboard-setup", description="ติดตั้งหน้าจอบอร์ดสรุปรายงานประจำวัน")
    @app_commands.describe(channel="ห้องแชทที่ต้องการเปิดหน้าจอบอร์ด")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def dashboard_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            return
        problem = channel_permission_problem(interaction.guild, channel)
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            embed = await self.build_dashboard_embed()
            message = await channel.send(embed=embed)
            await asyncio.to_thread(
                self.database.update_automation_settings,
                interaction.guild.id,
                dashboard_channel_id=channel.id,
                dashboard_message_id=message.id,
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Could not create dashboard in channel %s", channel.id)
            await interaction.followup.send(
                "สร้าง Dashboard ไม่สำเร็จ ตรวจสิทธิ์ View Channel, Send Messages และ Embed Links",
                ephemeral=True,
            )
            return
        except Exception:
            logger.exception("Dashboard setup failed for guild %s", interaction.guild.id)
            await interaction.followup.send(
                "สร้าง Dashboard ไม่สำเร็จ ลองใหม่อีกครั้งหรือตรวจ `/setup-check`",
                ephemeral=True,
            )
            return
        confirm_embed = make_embed(
            self.bot,
            "Daily Dashboard",
            title="✅ ตั้งบอร์ดให้แล้ว",
            description=(
                f"ผมจะอัปเดตข้อมูลใน {channel.mention} ทุกวันเวลา "
                "**08:00 น.** ตามเวลาไทยนะ"
            ),
            color=EmbedColor.SUCCESS,
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

    @app_commands.command(name="dashboard-update", description="อัปเดตข้อมูลบน Dashboard ทันที")
    async def dashboard_update(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        settings = await asyncio.to_thread(
            self.database.get_automation_settings,
            interaction.guild.id,
        )
        if not settings["dashboard_channel_id"] or not settings["dashboard_message_id"]:
            await interaction.response.send_message(
                "บอร์ดยังไม่ได้ตั้งไว้นะ ใช้ `/dashboard-setup` ก่อนหนึ่งครั้ง",
                ephemeral=True,
            )
            return
        channel = self.bot.get_channel(settings["dashboard_channel_id"])
        if channel is None:
            await interaction.response.send_message(
                "หาห้องของบอร์ดไม่เจอ ลองตั้งใหม่ด้วย `/dashboard-setup` นะ",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True)
        try:
            embed = await self.build_dashboard_embed()
            message = await channel.fetch_message(settings["dashboard_message_id"])
            await message.edit(embed=embed)
            await interaction.followup.send(
                embed=make_notice_embed(
                    self.bot, "Daily Dashboard", "✅ อัปเดตบอร์ดให้สดใหม่แล้วนะ",
                    color=EmbedColor.SUCCESS,
                )
            )
        except discord.NotFound:
            message = await channel.send(embed=embed)
            await asyncio.to_thread(
                self.database.update_automation_settings,
                interaction.guild.id,
                dashboard_message_id=message.id,
            )
            await interaction.followup.send(
                embed=make_notice_embed(
                    self.bot, "Daily Dashboard",
                    "หาโพสต์เดิมไม่เจอ เลยสร้างบอร์ดใหม่ให้แล้วนะ ✨",
                    color=EmbedColor.SUCCESS,
                )
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Could not manually update dashboard for guild %s", interaction.guild.id)
            await interaction.followup.send(
                embed=make_notice_embed(
                    self.bot, "Daily Dashboard",
                    "😅 บอร์ดสะดุดนิดหน่อย ลองอัปเดตใหม่อีกทีนะ",
                    color=EmbedColor.ERROR,
                )
            )
        except Exception:
            logger.exception("Dashboard update failed for guild %s", interaction.guild.id)
            await interaction.followup.send(
                embed=make_notice_embed(
                    self.bot, "Daily Dashboard",
                    "อัปเดตข้อมูลไม่สำเร็จ ลองใหม่อีกครั้งหรือตรวจ `/setup-check`",
                    color=EmbedColor.ERROR,
                ),
                ephemeral=True,
            )

    @app_commands.command(name="dashboard-disable", description="ปิด Daily Dashboard ของ Server นี้")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def dashboard_disable(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        settings = await asyncio.to_thread(
            self.database.get_automation_settings,
            interaction.guild.id,
        )
        if (
            settings["dashboard_channel_id"] is None
            and settings["dashboard_message_id"] is None
        ):
            await interaction.response.send_message(
                "Daily Dashboard ปิดอยู่แล้วนะ",
                ephemeral=True,
            )
            return
        await asyncio.to_thread(
            self.database.update_automation_settings,
            interaction.guild.id,
            dashboard_channel_id=None,
            dashboard_message_id=None,
        )
        await interaction.response.send_message(
            "✅ ปิด Daily Dashboard ให้แล้ว ข้อความเดิมยังเก็บไว้ในห้องนะ",
            ephemeral=True,
        )


async def setup(bot) -> None:
    await bot.add_cog(DashboardCog(bot))
