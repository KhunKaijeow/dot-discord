"""Per-guild sheapgamer RSS notifications."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import xml.etree.ElementTree as ET

import aiohttp
from bs4 import BeautifulSoup
import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..ui import EmbedColor, make_embed


logger = logging.getLogger("discord.x_notifier")

LEGACY_DATA_FILE = Path("data/x_notifier.json")
FEED_URL = "https://rss.app/feeds/COiTZRnT26oDqrJf.xml"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
SEEN_ITEM_LIMIT = 100


class XNotifierCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.database = bot.database
        self.check_x_feed.start()

    def cog_unload(self) -> None:
        self.check_x_feed.cancel()

    async def _migrate_legacy_state(self) -> None:
        if not LEGACY_DATA_FILE.exists():
            return
        try:
            data = json.loads(LEGACY_DATA_FILE.read_text(encoding="utf-8"))
            channel_id = data.get("channel_id")
            channel = self.bot.get_channel(channel_id) if channel_id else None
            guild = getattr(channel, "guild", None)
            if guild is None:
                return
            settings = await asyncio.to_thread(
                self.database.get_automation_settings,
                guild.id,
            )
            if settings["x_channel_id"] is None:
                await asyncio.to_thread(
                    self.database.update_automation_settings,
                    guild.id,
                    x_channel_id=channel_id,
                )
                await asyncio.to_thread(
                    self.database.remember_notifier_items,
                    guild.id,
                    "x",
                    [str(guid) for guid in data.get("last_seen_guids", []) if guid],
                    keep_limit=SEEN_ITEM_LIMIT,
                )
                logger.info("Migrated legacy sheapgamer state for guild %s", guild.id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            logger.exception("Could not migrate legacy sheapgamer state")

    async def fetch_feed_items(self) -> list[ET.Element]:
        try:
            async with self.bot.external_http.get(FEED_URL, timeout=REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    logger.warning("sheapgamer RSS returned HTTP %s", response.status)
                    return []
                root = ET.fromstring(await response.text())
                return root.findall(".//item")
        except (aiohttp.ClientError, TimeoutError, ET.ParseError):
            logger.exception("Could not fetch sheapgamer RSS")
            return []

    @staticmethod
    def item_guid(item: ET.Element) -> str | None:
        return item.findtext("guid")

    @staticmethod
    def create_feed_embed(item: ET.Element) -> discord.Embed:
        title = item.findtext("title") or "ข่าวใหม่จาก sheapgamer"
        link = item.findtext("link") or "https://x.com/sheapgamer"
        raw_description = item.findtext("description") or ""
        media = item.find("{http://search.yahoo.com/mrss/}content")
        image_url = media.attrib.get("url") if media is not None else None
        cleaned_description = ""
        if raw_description:
            soup = BeautifulSoup(raw_description, "html.parser")
            if not image_url:
                image = soup.find("img")
                image_url = image.get("src") if image else None
            cleaned_description = soup.get_text(separator="\n").strip()[:1000]
        embed = discord.Embed(
            title=title[:256],
            url=link,
            description=cleaned_description,
            color=EmbedColor.GOLD,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name="sheapgamer (เกมถูกบอกด้วย)",
            icon_url="https://static.xx.fbcdn.net/rsrc.php/yz/r/KFyVIAWzntM.ico",
            url="https://x.com/sheapgamer",
        )
        if image_url:
            embed.set_image(url=image_url)
        return embed

    async def _deliver_to_guild(self, settings: dict, items: list[ET.Element]) -> None:
        guild_id = settings["guild_id"]
        channel = self.bot.get_channel(settings["x_channel_id"])
        if channel is None:
            logger.warning("sheapgamer channel is unavailable for guild %s", guild_id)
            return
        seen = await asyncio.to_thread(
            self.database.seen_notifier_items,
            guild_id,
            "x",
        )
        current_guids = [guid for item in items if (guid := self.item_guid(item))]
        if not seen:
            await asyncio.to_thread(
                self.database.remember_notifier_items,
                guild_id,
                "x",
                current_guids,
                keep_limit=SEEN_ITEM_LIMIT,
            )
            logger.info("Initialized sheapgamer state for guild %s", guild_id)
            return
        posted = 0
        for item in reversed(items):
            guid = self.item_guid(item)
            if not guid or guid in seen:
                continue
            try:
                await channel.send(embed=self.create_feed_embed(item))
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Could not post sheapgamer update in guild %s", guild_id)
                return
            await asyncio.to_thread(
                self.database.remember_notifier_items,
                guild_id,
                "x",
                [guid],
                keep_limit=SEEN_ITEM_LIMIT,
            )
            seen.add(guid)
            posted += 1
        if posted:
            logger.info("Posted %s sheapgamer updates in guild %s", posted, guild_id)

    @tasks.loop(minutes=5)
    async def check_x_feed(self) -> None:
        settings = await asyncio.to_thread(
            self.database.configured_automation_settings,
            "x_channel_id",
        )
        if not settings:
            return
        items = await self.fetch_feed_items()
        if not items:
            return
        for row in settings:
            await self._deliver_to_guild(row, items)

    @check_x_feed.before_loop
    async def before_check_x_feed(self) -> None:
        await self.bot.wait_until_ready()
        await self._migrate_legacy_state()

    @app_commands.command(name="x-setup", description="ตั้งห้องรับข่าวใหม่จาก sheapgamer")
    @app_commands.describe(channel="ห้องแชทที่ต้องการรับแจ้งเตือน")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def x_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            return
        await asyncio.to_thread(
            self.database.update_automation_settings,
            interaction.guild.id,
            x_channel_id=channel.id,
        )
        embed = make_embed(
            self.bot,
            "sheapgamer",
            title="✅ ตั้งห้องข่าวให้แล้ว",
            description=f"มีโพสต์ใหม่เมื่อไร ผมจะรีบเอาไปบอกที่ {channel.mention} เลย",
            color=EmbedColor.SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="x-disable", description="ปิดระบบตามข่าว sheapgamer ของ Server นี้")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def x_disable(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        settings = await asyncio.to_thread(
            self.database.get_automation_settings,
            interaction.guild.id,
        )
        if settings["x_channel_id"] is None:
            await interaction.response.send_message(
                "ระบบตามข่าว sheapgamer ปิดอยู่แล้วนะ",
                ephemeral=True,
            )
            return
        await asyncio.to_thread(
            self.database.update_automation_settings,
            interaction.guild.id,
            x_channel_id=None,
        )
        await interaction.response.send_message(
            "✅ ปิดระบบตามข่าว sheapgamer ให้แล้ว",
            ephemeral=True,
        )

    @app_commands.command(name="x-status", description="ดูสถานะระบบตามข่าว sheapgamer")
    async def x_status(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        settings = await asyncio.to_thread(
            self.database.get_automation_settings,
            interaction.guild.id,
        )
        channel_id = settings["x_channel_id"]
        channel = self.bot.get_channel(channel_id) if channel_id else None
        count = await asyncio.to_thread(
            self.database.notifier_seen_count,
            interaction.guild.id,
            "x",
        )
        if channel_id:
            channel_text = channel.mention if channel else f"หาไม่เจอ (ID `{channel_id}`)"
            status_text = "🟢 เปิดใช้งานอยู่"
        else:
            channel_text = "ยังไม่ได้เลือก"
            status_text = "⚪ ปิดใช้งานอยู่"
        embed = make_embed(
            self.bot,
            "sheapgamer",
            title="🔔 สถานะการติดตามข่าว",
            description=status_text,
            color=EmbedColor.INFO,
        )
        embed.add_field(name="📍 ห้อง", value=channel_text, inline=True)
        embed.add_field(name="🗂️ โพสต์ที่จำไว้", value=f"`{count}`", inline=True)
        if not channel_id:
            embed.add_field(
                name="เริ่มใช้งาน",
                value="ใช้ `/x-setup` เพื่อเลือกห้องรับข่าว",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)


async def setup(bot) -> None:
    await bot.add_cog(XNotifierCog(bot))
