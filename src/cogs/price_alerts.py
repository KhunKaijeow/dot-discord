"""Persistent, validated stock/crypto/gold price alerts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..services.market_data import get_market_price, normalize_symbol


logger = logging.getLogger("discord.price_alerts")


class PriceAlertsCog(commands.Cog):
    price_alert = app_commands.Group(name="price-alert", description="จัดการการแจ้งเตือนราคา")

    def __init__(self, bot):
        self.bot = bot
        self.database = bot.database
        self.check_prices.start()

    def cog_unload(self):
        self.check_prices.cancel()

    @price_alert.command(name="add", description="เพิ่มเงื่อนไขแจ้งเตือนราคา")
    @app_commands.choices(
        asset_type=[app_commands.Choice(name=n, value=v) for n, v in (("หุ้น", "stock"), ("คริปโต", "crypto"), ("ทองคำ", "gold"))],
        condition=[app_commands.Choice(name="สูงกว่า", value="above"), app_commands.Choice(name="ต่ำกว่า", value="below")],
    )
    async def add(self, interaction: discord.Interaction, asset_type: str, symbol: str,
                  condition: str, target_price: float, repeat: bool = False):
        if not interaction.guild or not interaction.channel_id:
            await interaction.response.send_message("คำสั่งนี้ใช้ได้ภายใน Server เท่านั้น", ephemeral=True)
            return
        if not 0 < target_price <= 1_000_000_000:
            await interaction.response.send_message("ราคาเป้าหมายไม่ถูกต้อง", ephemeral=True)
            return
        try:
            normalized, current = await get_market_price(asset_type, symbol)
            settings = await asyncio.to_thread(self.database.get_settings, interaction.guild.id)
            delivery_channel_id = settings["alert_channel_id"] or interaction.channel_id
            alert_id = await asyncio.to_thread(
                self.database.create_alert, interaction.user.id, interaction.guild.id,
                delivery_channel_id, asset_type, normalized, condition, target_price, repeat,
            )
        except ValueError as error:
            message = "คุณมี Alert ครบ 20 รายการแล้ว" if "limit" in str(error).lower() else "สัญลักษณ์ไม่ถูกต้องหรือดึงราคาไม่ได้"
            await interaction.response.send_message(message, ephemeral=True)
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔔 เพิ่ม Price Alert แล้ว",
                description=f"ID `{alert_id}` • `{normalized}` {condition} `${target_price:,.4f}`\nราคาปัจจุบัน `${current:,.4f}`",
                color=0x2ECC71,
            ), ephemeral=True,
        )

    @price_alert.command(name="list", description="ดู Price Alert ของคุณ")
    async def list_alerts(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        rows = await asyncio.to_thread(self.database.list_alerts, interaction.user.id, interaction.guild.id)
        text = "\n".join(
            f"`#{row['id']}` {row['asset_type']} `{row['symbol']}` {row['condition']} `${row['target_price']:,.4f}`"
            for row in rows
        ) or "ยังไม่มี Price Alert"
        await interaction.response.send_message(embed=discord.Embed(title="🔔 Price Alerts", description=text, color=0x3498DB), ephemeral=True)

    @price_alert.command(name="remove", description="ลบ Price Alert ด้วย ID")
    async def remove(self, interaction: discord.Interaction, alert_id: int):
        deleted = await asyncio.to_thread(self.database.delete_alert, alert_id, interaction.user.id)
        await interaction.response.send_message("✅ ลบ Price Alert แล้ว" if deleted else "ไม่พบ Alert นี้หรือไม่ใช่ของคุณ", ephemeral=True)

    @tasks.loop(minutes=5)
    async def check_prices(self):
        rows = await asyncio.to_thread(self.database.all_alerts)
        prices: dict[tuple[str, str], float | None] = {}
        for row in rows:
            key = (row["asset_type"], row["symbol"])
            if key not in prices:
                try:
                    _, prices[key] = await get_market_price(*key)
                except Exception:
                    logger.warning("Price lookup failed for %s", key)
                    prices[key] = None
            price = prices[key]
            if price is None:
                continue
            triggered = price >= row["target_price"] if row["condition"] == "above" else price <= row["target_price"]
            if not triggered:
                continue
            if row["repeat_enabled"] and row["last_triggered_at"]:
                last = datetime.fromisoformat(row["last_triggered_at"])
                if (datetime.now(timezone.utc) - last).total_seconds() < 3600:
                    continue
            channel = self.bot.get_channel(row["channel_id"])
            if channel is None:
                continue
            try:
                await channel.send(
                    content=f"<@{row['user_id']}>",
                    embed=discord.Embed(
                        title="🚨 Price Alert ทำงานแล้ว",
                        description=f"`{row['symbol']}` ราคา `${price:,.4f}` ถึงเงื่อนไข {row['condition']} `${row['target_price']:,.4f}`",
                        color=0xF1C40F,
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except (discord.Forbidden, discord.HTTPException):
                continue
            await asyncio.to_thread(self.database.mark_alert_triggered, row["id"], bool(row["repeat_enabled"]))

    @check_prices.before_loop
    async def before_prices(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(PriceAlertsCog(bot))
