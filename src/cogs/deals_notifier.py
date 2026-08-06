"""Per-guild GamerPower giveaway notifications."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..ui import EmbedColor, make_embed


logger = logging.getLogger("discord.deals_notifier")

LEGACY_DATA_FILE = Path("data/deals_notifier.json")
API_URL = "https://www.gamerpower.com/api/giveaways?type=game"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
SEEN_ITEM_LIMIT = 200


class DealsNotifierCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.database = bot.database
        self.check_deals.start()

    def cog_unload(self) -> None:
        self.check_deals.cancel()

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
            if settings["deals_channel_id"] is None:
                await asyncio.to_thread(
                    self.database.update_automation_settings,
                    guild.id,
                    deals_channel_id=channel_id,
                )
                await asyncio.to_thread(
                    self.database.remember_notifier_items,
                    guild.id,
                    "deals",
                    [str(item_id) for item_id in data.get("posted_ids", []) if item_id],
                    keep_limit=SEEN_ITEM_LIMIT,
                )
                logger.info("Migrated legacy deals state for guild %s", guild.id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            logger.exception("Could not migrate legacy deals state")

    async def fetch_active_giveaways(self) -> list[dict]:
        try:
            async with self.bot.http.get(API_URL, timeout=REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    logger.warning("GamerPower returned HTTP %s", response.status)
                    return []
                payload = await response.json()
                return payload if isinstance(payload, list) else []
        except (aiohttp.ClientError, TimeoutError, ValueError):
            logger.exception("Could not fetch GamerPower giveaways")
            return []

    @staticmethod
    def create_giveaway_embed(item: dict) -> discord.Embed:
        title = item.get("title", "Game Giveaway")
        worth = item.get("worth", "N/A")
        description = item.get("description", "กดรับสิทธิ์ได้ฟรีตามลิงก์")
        instructions = item.get("instructions", "")
        platforms = item.get("platforms", "PC")
        end_date = item.get("end_date", "จนกว่าสิทธิ์จะหมด")
        url = item.get("open_giveaway_url", "https://www.gamerpower.com")
        embed = discord.Embed(
            title=f"🎁 แจกเกมฟรี! {title}",
            url=url,
            description=description,
            color=EmbedColor.PRIMARY,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="🎮 แพลตฟอร์ม", value=f"`{platforms}`", inline=True)
        embed.add_field(name="💰 มูลค่าปกติ", value=f"~~{worth}~~ **ฟรี!**", inline=True)
        embed.add_field(name="📅 สิ้นสุด", value=f"`{end_date}`", inline=True)
        if instructions:
            embed.add_field(
                name="📝 วิธีรับสิทธิ์",
                value=instructions[:500],
                inline=False,
            )
        image = item.get("image")
        thumbnail = item.get("thumbnail")
        if image:
            embed.set_image(url=image)
        elif thumbnail:
            embed.set_thumbnail(url=thumbnail)
        embed.set_author(
            name="GamerPower Giveaway",
            icon_url="https://www.gamerpower.com/favicon.ico",
        )
        return embed

    async def _deliver_to_guild(self, settings: dict, items: list[dict]) -> None:
        guild_id = settings["guild_id"]
        channel = self.bot.get_channel(settings["deals_channel_id"])
        if channel is None:
            logger.warning("Deals channel is unavailable for guild %s", guild_id)
            return
        seen = await asyncio.to_thread(
            self.database.seen_notifier_items,
            guild_id,
            "deals",
        )
        current_ids = [str(item["id"]) for item in items if item.get("id") is not None]
        if not seen:
            await asyncio.to_thread(
                self.database.remember_notifier_items,
                guild_id,
                "deals",
                current_ids,
                keep_limit=SEEN_ITEM_LIMIT,
            )
            logger.info("Initialized deals state for guild %s", guild_id)
            return
        posted = 0
        for item in reversed(items):
            item_id = str(item.get("id", ""))
            if not item_id or item_id in seen:
                continue
            try:
                await channel.send(embed=self.create_giveaway_embed(item))
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Could not post giveaway in guild %s", guild_id)
                return
            await asyncio.to_thread(
                self.database.remember_notifier_items,
                guild_id,
                "deals",
                [item_id],
                keep_limit=SEEN_ITEM_LIMIT,
            )
            seen.add(item_id)
            posted += 1
        if posted:
            logger.info("Posted %s giveaways in guild %s", posted, guild_id)

    @tasks.loop(hours=1)
    async def check_deals(self) -> None:
        settings = await asyncio.to_thread(
            self.database.configured_automation_settings,
            "deals_channel_id",
        )
        if not settings:
            return
        items = await self.fetch_active_giveaways()
        if not items:
            return
        for row in settings:
            await self._deliver_to_guild(row, items)

    @check_deals.before_loop
    async def before_check_deals(self) -> None:
        await self.bot.wait_until_ready()
        await self._migrate_legacy_state()

    @app_commands.command(name="deals-setup", description="ตั้งห้องสำหรับแจ้งเตือนเกมแจกฟรี")
    @app_commands.describe(channel="ห้องแชทที่ต้องการให้รับแจ้งเตือนเกมแจกฟรี")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def deals_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            return
        await asyncio.to_thread(
            self.database.update_automation_settings,
            interaction.guild.id,
            deals_channel_id=channel.id,
        )
        embed = make_embed(
            self.bot,
            "Free Games",
            title="🎁 พร้อมล่าเกมฟรีแล้ว",
            description=f"ถ้ามีเกมแจกใหม่ ผมจะรีบเอาไปบอกที่ {channel.mention} เลย",
            color=EmbedColor.SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="deals-disable", description="ปิดแจ้งเตือนเกมแจกฟรีของ Server นี้")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def deals_disable(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        settings = await asyncio.to_thread(
            self.database.get_automation_settings,
            interaction.guild.id,
        )
        if settings["deals_channel_id"] is None:
            await interaction.response.send_message(
                "ระบบแจ้งเตือนเกมฟรีปิดอยู่แล้วนะ",
                ephemeral=True,
            )
            return
        await asyncio.to_thread(
            self.database.update_automation_settings,
            interaction.guild.id,
            deals_channel_id=None,
        )
        await interaction.response.send_message(
            "✅ ปิดแจ้งเตือนเกมแจกฟรีให้แล้ว",
            ephemeral=True,
        )

    @app_commands.command(name="deals-check", description="แสดงดีลเกมแจกฟรีล่าสุดทันที")
    async def deals_check(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        items = await self.fetch_active_giveaways()
        if not items:
            await interaction.followup.send("🎁 ตอนนี้ยังไม่มีเกมแจกฟรี เดี๋ยวมีแล้วผมบอกนะ")
            return
        await interaction.followup.send("🎁 **เจอเกมฟรีล่าสุดมาให้แล้ว:**")
        for item in items[:3]:
            await interaction.channel.send(embed=self.create_giveaway_embed(item))


async def setup(bot) -> None:
    await bot.add_cog(DealsNotifierCog(bot))
