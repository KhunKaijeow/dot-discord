import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("discord.deals_notifier")

DATA_FILE = "data/deals_notifier.json"
API_URL = "https://www.gamerpower.com/api/giveaways?type=game"

class DealsNotifierCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = None
        self.posted_ids = []
        self.load_state()
        self.check_deals.start()

    def cog_unload(self):
        self.check_deals.cancel()

    def load_state(self):
        """Loads target channel and list of posted giveaways from storage."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.channel_id = data.get("channel_id")
                    self.posted_ids = data.get("posted_ids", [])
            except Exception as e:
                logger.error(f"Error loading state from {DATA_FILE}: {e}")
        else:
            self.channel_id = None
            self.posted_ids = []

    def save_state(self):
        """Saves current state to JSON."""
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "channel_id": self.channel_id,
                    "posted_ids": self.posted_ids[-100:]  # Keep last 100 to prevent file growth
                }, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Error saving state to {DATA_FILE}: {e}")

    async def fetch_active_giveaways(self):
        """Fetches active giveaways from GamerPower API."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch giveaways: Status {response.status}")
                        return []
                    return await response.json()
        except Exception as e:
            logger.error(f"Error calling GamerPower API: {e}")
            return []

    def create_giveaway_embed(self, item):
        """Creates a beautiful Discord Embed for a game giveaway."""
        title = item.get("title", "Game Giveaway")
        worth = item.get("worth", "N/A")
        thumbnail = item.get("thumbnail")
        image = item.get("image")
        description = item.get("description", "กดรับสิทธิ์ได้ฟรีตามลิงก์")
        instructions = item.get("instructions", "")
        platforms = item.get("platforms", "PC")
        end_date = item.get("end_date", "จนกว่าสิทธิ์จะหมด")
        gamerpower_url = item.get("open_giveaway_url", "https://www.gamerpower.com")

        embed = discord.Embed(
            title=f"🎁 แจกเกมฟรี!: {title}",
            url=gamerpower_url,
            description=description,
            color=0x9b59b6,  # Purple theme
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="🎮 แพลตฟอร์ม", value=f"`{platforms}`", inline=True)
        embed.add_field(name="💰 มูลค่าปกติ", value=f"~~{worth}~~ **ฟรี!**", inline=True)
        embed.add_field(name="📅 ระยะเวลาสิ้นสุด", value=f"`{end_date}`", inline=True)

        if instructions:
            # Truncate instruction if too long
            if len(instructions) > 500:
                instructions = instructions[:497] + "..."
            embed.add_field(name="📝 ขั้นตอนการรับสิทธิ์", value=instructions, inline=False)

        if image:
            embed.set_image(url=image)
        elif thumbnail:
            embed.set_thumbnail(url=thumbnail)

        embed.set_author(name="GamerPower Giveaway", icon_url="https://www.gamerpower.com/favicon.ico")
        return embed

    @tasks.loop(hours=1.0)
    async def check_deals(self):
        """Periodically check for new giveaways and post them."""
        if not self.channel_id:
            return

        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            logger.warning(f"Giveaways alert channel ID {self.channel_id} not found.")
            return

        items = await self.fetch_active_giveaways()
        if not items or not isinstance(items, list):
            return

        # Reverse list to process older giveaways first
        items.reverse()

        # If posted_ids is empty, initialize with current items to prevent spamming old deals
        if not self.posted_ids:
            self.posted_ids = [item.get("id") for item in items if item.get("id") is not None]
            self.save_state()
            logger.info("Initialized posted_ids with current active giveaways.")
            return

        new_deals_posted = 0
        for item in items:
            giveaway_id = item.get("id")
            if not giveaway_id or giveaway_id in self.posted_ids:
                continue

            embed = self.create_giveaway_embed(item)
            await channel.send(embed=embed)
            self.posted_ids.append(giveaway_id)
            new_deals_posted += 1

        if new_deals_posted > 0:
            self.save_state()
            logger.info(f"Posted {new_deals_posted} new game giveaways to channel {self.channel_id}")

    @check_deals.before_loop
    async def before_check_deals(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="deals-setup", description="ตั้งห้องสำหรับแจ้งเตือนเกมแจกฟรี")
    @app_commands.describe(channel="ห้องแชทที่ต้องการให้รับแจ้งเตือนเกมแจกฟรี")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    async def deals_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.channel_id = channel.id
        self.save_state()
        embed = discord.Embed(
            description=f"✅ **ตั้งค่าเรียบร้อย!** บอทจะคอยส่งแจ้งเตือนเมื่อมีเกมแจกฟรีที่ช่อง {channel.mention}",
            color=0x2ecc71
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="deals-check", description="ดึงข้อมูลดีลเกมแจกฟรีล่าสุดมาแสดงทันที")
    async def deals_check(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        items = await self.fetch_active_giveaways()
        
        if not items or not isinstance(items, list):
            await interaction.followup.send("😅 ขออภัย ในขณะนี้ไม่สามารถติดต่อเซิร์ฟเวอร์ดึงข้อมูลดีลเกมได้ครับ")
            return

        # Show up to top 3 active giveaways
        giveaways_to_show = items[:3]
        
        if not giveaways_to_show:
            await interaction.followup.send("🎁 ตอนนี้ยังไม่มีเกมแจกฟรีที่เปิดใช้งานอยู่ครับ")
            return

        await interaction.followup.send("🎁 **ดีลเกมแจกฟรีล่าสุด 3 รายการประจำวันนี้:**")
        for item in giveaways_to_show:
            embed = self.create_giveaway_embed(item)
            # Remove footer to comply with user preference
            await interaction.channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(DealsNotifierCog(bot))
