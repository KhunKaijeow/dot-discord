import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import xml.etree.ElementTree as ET
import os
import json
import logging
from bs4 import BeautifulSoup
from datetime import datetime

logger = logging.getLogger("discord.x_notifier")

DATA_FILE = "data/x_notifier.json"
FEED_URL = "https://rss.app/feeds/COiTZRnT26oDqrJf.xml"

class XNotifierCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = None
        self.last_seen_guids = []
        self.load_state()
        self.check_x_feed.start()

    def cog_unload(self):
        self.check_x_feed.cancel()

    def load_state(self):
        """Loads the notification channel ID and last seen GUIDs from storage."""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.channel_id = data.get("channel_id")
                    self.last_seen_guids = data.get("last_seen_guids", [])
            except Exception as e:
                logger.error(f"Error loading state from {DATA_FILE}: {e}")
        else:
            self.channel_id = None
            self.last_seen_guids = []

    def save_state(self):
        """Saves current state to JSON."""
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "channel_id": self.channel_id,
                    "last_seen_guids": self.last_seen_guids[-30:]  # Keep last 30 to prevent file growth
                }, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Error saving state to {DATA_FILE}: {e}")

    @tasks.loop(minutes=5.0)
    async def check_x_feed(self):
        """Periodically checks the RSS feed for sheapgamer updates."""
        if not self.channel_id:
            return

        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            logger.warning(f"Notification channel with ID {self.channel_id} not found.")
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(FEED_URL) as response:
                    if response.status != 200:
                        logger.error(f"Failed to fetch RSS feed: HTTP status {response.status}")
                        return
                    
                    xml_content = await response.text()
                    
                    # Parse RSS XML
                    root = ET.fromstring(xml_content)
                    items = root.findall('.//item')
                    
                    if not items:
                        return

                    # Reversing items so we process and post the oldest updates first
                    items.reverse()

                    # If last_seen_guids is empty, it's either first run or state was cleared.
                    # We initialize with current items so we don't spam everything on startup.
                    if not self.last_seen_guids:
                        self.last_seen_guids = [item.find("guid").text for item in items if item.find("guid") is not None]
                        self.save_state()
                        logger.info("Initialized last_seen_guids with current feed items.")
                        return

                    new_items_posted = 0
                    for item in items:
                        guid_el = item.find("guid")
                        guid = guid_el.text if guid_el is not None else None
                        
                        if not guid or guid in self.last_seen_guids:
                            continue

                        # Extract details
                        title_el = item.find("title")
                        link_el = item.find("link")
                        desc_el = item.find("description")
                        
                        title = title_el.text if title_el is not None else "ข่าวสารใหม่จาก sheapgamer"
                        link = link_el.text if link_el is not None else "https://x.com/sheapgamer"
                        raw_desc = desc_el.text if desc_el is not None else ""

                        # Try to get image from media:content namespace or fallback to bs4 scraping from description
                        image_url = None
                        media_content = item.find('{http://search.yahoo.com/mrss/}content')
                        if media_content is not None:
                            image_url = media_content.attrib.get('url')

                        # Clean description using BeautifulSoup
                        cleaned_desc = ""
                        if raw_desc:
                            soup = BeautifulSoup(raw_desc, "html.parser")
                            
                            # Fallback image search in case media:content is missing
                            if not image_url:
                                img_el = soup.find('img')
                                if img_el:
                                    image_url = img_el.get('src')
                            
                            cleaned_desc = soup.get_text(separator="\n").strip()

                        # Truncate content to fit Discord Embed limit
                        if len(cleaned_desc) > 1000:
                            cleaned_desc = cleaned_desc[:997] + "..."

                        # Create embed
                        embed = discord.Embed(
                            title=title[:256],
                            url=link,
                            description=cleaned_desc,
                            color=0xffd700,  # Gaming Yellow/Gold
                            timestamp=datetime.utcnow()
                        )
                        embed.set_author(
                            name="sheapgamer (เกมถูกบอกด้วย)",
                            icon_url="https://static.xx.fbcdn.net/rsrc.php/yz/r/KFyVIAWzntM.ico",
                            url="https://x.com/sheapgamer"
                        )
                        if image_url:
                            embed.set_image(url=image_url)

                        await channel.send(embed=embed)
                        self.last_seen_guids.append(guid)
                        new_items_posted += 1

                    if new_items_posted > 0:
                        self.save_state()
                        logger.info(f"Posted {new_items_posted} new updates to channel {self.channel_id}")

        except Exception as e:
            logger.error(f"Error checking sheapgamer feed: {e}", exc_info=True)

    @check_x_feed.before_loop
    async def before_check_x_feed(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="x-setup", description="ตั้งค่าช่องสำหรับรับแจ้งเตือนข่าวสารจาก sheapgamer")
    @app_commands.describe(channel="ห้องแชทที่ต้องการรับแจ้งเตือน")
    @app_commands.default_permissions(manage_channels=True)
    async def x_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.channel_id = channel.id
        self.save_state()
        
        embed = discord.Embed(
            description=f"✅ **ตั้งค่าเรียบร้อย!** บอทจะแจ้งเตือนข่าวสาร sheapgamer ที่ช่อง {channel.mention} ทุกครั้งที่มีการอัพเดทใหม่",
            color=0x2ecc71
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="x-status", description="ดูสถานะห้องแจ้งเตือนและการสแกนข่าวสารจาก sheapgamer")
    async def x_status(self, interaction: discord.Interaction):
        if self.channel_id:
            channel = self.bot.get_channel(self.channel_id)
            channel_mention = channel.mention if channel else f"ไม่พบห้อง ID {self.channel_id}"
            status_text = f"🟢 **เปิดใช้งาน**\n**ห้องรับข่าวสาร:** {channel_mention}\n**จำนวนโพสต์ที่เคยแสกนล่าสุด:** {len(self.last_seen_guids)} โพสต์"
        else:
            status_text = "🔴 **ยังไม่ได้เปิดใช้งาน**\nใช้คำสั่ง `/x-setup` เพื่อกำหนดห้องรับข่าวสารได้เลยครับ"

        embed = discord.Embed(
            title="🔍 สถานะการแจ้งเตือน sheapgamer",
            description=status_text,
            color=0x3498db
        )
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(XNotifierCog(bot))
