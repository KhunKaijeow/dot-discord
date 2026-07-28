import discord
from discord.ext import commands, tasks
from discord import app_commands
import yfinance as yf
import asyncio
import os
import json
import logging
from datetime import datetime
import xml.etree.ElementTree as ET
import aiohttp

logger = logging.getLogger("discord.dashboard")

DATA_FILE = "data/dashboard.json"
NEWS_FEED_URL = "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th"

def fetch_financial_metrics():
    """Sync function to fetch financial indices from yfinance."""
    metrics = {}
    try:
        # Fetch Gold (GC=F), S&P 500 ETF (SPY), SET Index (^SET), USD/THB (USDTHB=X)
        tickers = {
            "Gold": "GC=F",
            "SPY": "SPY",
            "SET": "^SET",
            "USDTHB": "USDTHB=X"
        }
        for name, symbol in tickers.items():
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
                prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
                change = current_price - prev_close
                pct_change = (change / prev_close) * 100
                metrics[name] = {
                    "price": current_price,
                    "change": change,
                    "pct_change": pct_change
                }
            else:
                metrics[name] = None
    except Exception as e:
        logger.error(f"Error fetching financial metrics: {e}")
    return metrics

class DashboardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = None
        self.message_id = None
        self.load_state()
        self.update_dashboard_loop.start()

    def cog_unload(self):
        self.update_dashboard_loop.cancel()

    def load_state(self):
        """Loads dashboard channel and message ID from storage."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.channel_id = data.get("channel_id")
                    self.message_id = data.get("message_id")
            except Exception as e:
                logger.error(f"Error loading dashboard state: {e}")
        else:
            self.channel_id = None
            self.message_id = None

    def save_state(self):
        """Saves current state to JSON."""
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "channel_id": self.channel_id,
                    "message_id": self.message_id
                }, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Error saving dashboard state: {e}")

    async def fetch_top_news(self):
        """Fetches top 3 headlines from Google News RSS."""
        news_list = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(NEWS_FEED_URL) as response:
                    if response.status == 200:
                        xml_content = await response.text()
                        root = ET.fromstring(xml_content)
                        items = root.findall('.//item')[:3]
                        for item in items:
                            title = item.find("title").text
                            link = item.find("link").text
                            news_list.append((title, link))
        except Exception as e:
            logger.error(f"Error fetching news for dashboard: {e}")
        return news_list

    def format_metric(self, name, symbol_prefix, symbol_suffix, data):
        """Helper to format yfinance metric rows."""
        if not data:
            return f"• **{name}:** `N/A`"
        price = data["price"]
        change = data["change"]
        pct_change = data["pct_change"]
        sign = "+" if change > 0 else ""
        icon = "📈" if change > 0 else ("📉" if change < 0 else "↔️")
        
        return f"{icon} **{name}:** `{symbol_prefix}{price:,.2f}{symbol_suffix}` ({sign}{pct_change:.2f}%)"

    async def build_dashboard_embed(self):
        """Gathers data and builds the dashboard embed."""
        # 1. Fetch finance data
        metrics = await asyncio.to_thread(fetch_financial_metrics)
        
        gold_str = self.format_metric("ราคาทองคำโลก (GC=F)", "$", " / oz", metrics.get("Gold"))
        usdthb_str = self.format_metric("อัตราแลกเปลี่ยน (USD/THB)", "", " THB", metrics.get("USDTHB"))
        spy_str = self.format_metric("ดัชนี S&P 500 ETF (SPY)", "$", "", metrics.get("SPY"))
        set_str = self.format_metric("ดัชนีตลาดหุ้นไทย (^SET)", "", "", metrics.get("SET"))

        finance_text = f"{gold_str}\n{usdthb_str}\n{spy_str}\n{set_str}"

        # 2. Fetch top news
        news = await self.fetch_top_news()
        news_lines = []
        if news:
            for idx, (title, link) in enumerate(news, 1):
                # Clean title source suffix if needed or keep it simple
                news_lines.append(f"{idx}. [{title[:85]}...]({link})")
            news_text = "\n\n".join(news_lines)
        else:
            news_text = "• *ไม่มีข้อมูลข่าวสารชั่วคราว*"

        # 3. Build Embed
        embed = discord.Embed(
            title="📊 บอร์ดรายงานข้อมูลสรุปประจำวัน (Daily Dashboard)",
            description=f"อัปเดตข้อมูลอัตโนมัติล่าสุดเมื่อ: <t:{int(datetime.utcnow().timestamp())}:R>",
            color=0x34495e,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="🏛️ ดัชนีการเงินและการลงทุนล่าสุด", value=finance_text, inline=False)
        embed.add_field(name="📰 สรุปข่าวเด่นร้อนแรงล่าสุด", value=news_text, inline=False)

        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        embed.set_author(name="Javis Server Monitor", icon_url=avatar_url)
        return embed

    @tasks.loop(minutes=30.0)
    async def update_dashboard_loop(self):
        """Automatically updates the dashboard message every 30 minutes."""
        if not self.channel_id or not self.message_id:
            return

        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            logger.warning(f"Dashboard channel ID {self.channel_id} not found.")
            return

        try:
            message = await channel.fetch_message(self.message_id)
            embed = await self.build_dashboard_embed()
            await message.edit(embed=embed)
            logger.info("Successfully auto-updated the Daily Dashboard message.")
        except discord.NotFound:
            # Message was deleted, we recreate it
            embed = await self.build_dashboard_embed()
            new_msg = await channel.send(embed=embed)
            self.message_id = new_msg.id
            self.save_state()
            logger.info("Dashboard message not found. Re-created and saved new message ID.")
        except Exception as e:
            logger.error(f"Error updating dashboard message: {e}")

    @update_dashboard_loop.before_loop
    async def before_update_dashboard_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="dashboard-setup", description="เปิดใช้งานและติดตั้งหน้าจอบอร์ดสรุปรายงานประจำวัน")
    @app_commands.describe(channel="ห้องแชทที่ต้องการเปิดหน้าจอบอร์ด")
    @app_commands.default_permissions(manage_channels=True)
    async def dashboard_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(thinking=True)
        self.channel_id = channel.id
        
        # Build and send initial dashboard message
        embed = await self.build_dashboard_embed()
        message = await channel.send(embed=embed)
        
        self.message_id = message.id
        self.save_state()

        confirm_embed = discord.Embed(
            description=f"✅ **เปิดใช้งานบอร์ดข้อมูลสำเร็จ!** บอร์ดจะทำการอัปเดตตัวเองอัตโนมัติในช่อง {channel.mention} ทุก ๆ 30 นาทีครับ",
            color=0x2ecc71
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

    @app_commands.command(name="dashboard-update", description="สั่งบังคับให้บอร์ดสรุปอัปเดตข้อมูลทันที")
    async def dashboard_update(self, interaction: discord.Interaction):
        if not self.channel_id or not self.message_id:
            await interaction.response.send_message("❌ **บอร์ดยังไม่ถูกติดตั้ง!** กรุณาใช้คำสั่ง `/dashboard-setup` ก่อนครับ", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            await interaction.followup.send("❌ **ไม่พบห้องสำหรับบอร์ดข้อมูล!** กรุณาตั้งค่าห้องด้วยคำสั่ง `/dashboard-setup` อีกครั้งครับ", ephemeral=True)
            return

        try:
            message = await channel.fetch_message(self.message_id)
            embed = await self.build_dashboard_embed()
            await message.edit(embed=embed)
            await interaction.followup.send("✅ **อัปเดตข้อมูลบนบอร์ดเรียบร้อยแล้วครับ!**")
        except discord.NotFound:
            embed = await self.build_dashboard_embed()
            new_msg = await channel.send(embed=embed)
            self.message_id = new_msg.id
            self.save_state()
            await interaction.followup.send("⚠️ **ไม่พบข้อความบอร์ดเดิม!** จึงได้ทำการสร้างข้อความบอร์ดใหม่และอัปเดตข้อมูลเรียบร้อยครับ")
        except Exception as e:
            logger.error(f"Error manually updating dashboard: {e}")
            await interaction.followup.send("😅 ขออภัย เกิดข้อผิดพลาดในการอัปเดตข้อมูลบอร์ด")

async def setup(bot):
    await bot.add_cog(DashboardCog(bot))
