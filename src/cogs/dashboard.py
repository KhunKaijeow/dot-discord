"""Per-guild daily market and news dashboard."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone
import json
import logging
from pathlib import Path
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
import yfinance as yf

from ..ui import EmbedColor, make_embed, set_embed_author


logger = logging.getLogger("discord.dashboard")

LEGACY_DATA_FILE = Path("data/dashboard.json")
NEWS_FEED_URL = "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th"
BANGKOK_TIMEZONE = ZoneInfo("Asia/Bangkok")
DASHBOARD_UPDATE_TIME = time(hour=8, minute=0, tzinfo=BANGKOK_TIMEZONE)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)


def fetch_financial_metrics() -> dict[str, dict | None]:
    """Fetch the market values used by every guild dashboard."""
    metrics: dict[str, dict | None] = {}
    tickers = {
        "Gold": "GC=F",
        "SPY": "SPY",
        "SET": "^SET",
        "USDTHB": "USDTHB=X",
    }
    try:
        for name, symbol in tickers.items():
            history = yf.Ticker(symbol).history(period="5d")
            if history.empty:
                metrics[name] = None
                continue
            current_price = history["Close"].iloc[-1]
            previous_close = history["Close"].iloc[-2] if len(history) > 1 else current_price
            change = current_price - previous_close
            metrics[name] = {
                "price": current_price,
                "change": change,
                "pct_change": (change / previous_close) * 100,
            }
    except Exception:
        logger.exception("Could not fetch dashboard market metrics")
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
            async with self.bot.http.get(
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
        metrics = await asyncio.to_thread(fetch_financial_metrics)
        finance_text = "\n".join(
            (
                self.format_metric("ราคาทองคำโลก (GC=F)", "$", " / oz", metrics.get("Gold")),
                self.format_metric("อัตราแลกเปลี่ยน (USD/THB)", "", " THB", metrics.get("USDTHB")),
                self.format_metric("ดัชนี S&P 500 ETF (SPY)", "$", "", metrics.get("SPY")),
                self.format_metric("ดัชนีตลาดหุ้นไทย (^SET)", "", "", metrics.get("SET")),
            )
        )
        headlines = await self.fetch_top_news()
        news_text = (
            "\n\n".join(
                f"{index}. [{title[:85]}]({link})"
                for index, (title, link) in enumerate(headlines, 1)
            )
            or "• *ยังไม่มีข้อมูลข่าวในตอนนี้*"
        )
        now = datetime.now(timezone.utc)
        embed = discord.Embed(
            title="📊 ภาพรวมวันนี้",
            description=f"ข้อมูลชุดนี้อัปเดตเมื่อ <t:{int(now.timestamp())}:R>",
            color=EmbedColor.PRIMARY,
            timestamp=now,
        )
        embed.add_field(name="🏛️ ตลาดตอนนี้", value=finance_text, inline=False)
        embed.add_field(name="📰 ข่าวที่น่าสนใจ", value=news_text, inline=False)
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
        settings = await asyncio.to_thread(
            self.database.configured_automation_settings,
            "dashboard_channel_id",
        )
        settings = [row for row in settings if row["dashboard_message_id"] is not None]
        if not settings:
            return
        embed = await self.build_dashboard_embed()
        for row in settings:
            await self._update_saved_dashboard(row, embed)

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
        await interaction.response.defer(thinking=True)
        message = await channel.send(embed=await self.build_dashboard_embed())
        await asyncio.to_thread(
            self.database.update_automation_settings,
            interaction.guild.id,
            dashboard_channel_id=channel.id,
            dashboard_message_id=message.id,
        )
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
        embed = await self.build_dashboard_embed()
        try:
            message = await channel.fetch_message(settings["dashboard_message_id"])
            await message.edit(embed=embed)
            await interaction.followup.send("✅ อัปเดตบอร์ดให้สดใหม่แล้วนะ")
        except discord.NotFound:
            message = await channel.send(embed=embed)
            await asyncio.to_thread(
                self.database.update_automation_settings,
                interaction.guild.id,
                dashboard_message_id=message.id,
            )
            await interaction.followup.send("หาโพสต์เดิมไม่เจอ เลยสร้างบอร์ดใหม่ให้แล้วนะ ✨")
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Could not manually update dashboard for guild %s", interaction.guild.id)
            await interaction.followup.send("😅 บอร์ดสะดุดนิดหน่อย ลองอัปเดตใหม่อีกทีนะ")


async def setup(bot) -> None:
    await bot.add_cog(DashboardCog(bot))
