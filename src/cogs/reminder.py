"""Reminder slash commands."""

import discord
from discord.ext import commands
from discord import app_commands
import re
import asyncio

class ReminderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="remind", description="ตั้งเวลาแจ้งเตือนเหตุการณ์พร้อมข้อความ")
    @app_commands.describe(
        duration="ระยะเวลา เช่น 30s (30 วินาที), 10m (10 นาที), 2h (2 ชั่วโมง)",
        message="ข้อความความเตือนความจำ"
    )
    async def remind(self, interaction: discord.Interaction, duration: str, message: str):
        duration_clean = duration.strip().lower()
        
        # Parse time string using regex (e.g., 30s, 10m, 2h)
        pattern = re.compile(r"^(\d+)([smh])$")
        match = pattern.match(duration_clean)
        
        if not match:
            embed = discord.Embed(
                title="❌ รูปแบบเวลาไม่ถูกต้อง",
                description="กรุณาระบุเวลาตามรูปแบบที่กำหนด ตัวอย่างดังนี้ครับ:\n"
                            "• `30s` = 30 วินาที\n"
                            "• `10m` = 10 นาที\n"
                            "• `1h` = 1 ชั่วโมง\n"
                            "*(ลงท้ายด้วยตัวอักษร s, m หรือ h เท่านั้น)*",
                color=0xe74c3c
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        value, unit = match.groups()
        value = int(value)
        
        # Calculate time in seconds
        seconds = 0
        unit_display = ""
        if unit == "s":
            seconds = value
            unit_display = f"{value} วินาที"
        elif unit == "m":
            seconds = value * 60
            unit_display = f"{value} นาที"
        elif unit == "h":
            seconds = value * 3600
            unit_display = f"{value} ชั่วโมง"

        # Enforce maximum reminder time of 24 hours (86400 seconds)
        max_seconds = 86400
        if seconds > max_seconds:
            embed = discord.Embed(
                title="⚠️ เวลาแจ้งเตือนนานเกินไป",
                description="ระบบอนุญาตให้ตั้งเวลาแจ้งเตือนได้สูงสุดไม่เกิน **24 ชั่วโมง (24h)** เท่านั้นครับ",
                color=0xe74c3c
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if seconds <= 0:
            embed = discord.Embed(
                title="❌ เวลาแจ้งเตือนไม่ถูกต้อง",
                description="เวลาแจ้งเตือนต้องมากกว่า 0 วินาทีครับ",
                color=0xe74c3c
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Confirm reminder registration
        embed = discord.Embed(
            description=f"⏰ บอทจะส่งข้อความแจ้งเตือนคุณในอีก **{unit_display}** ข้างหน้าครับ\n\n"
                        f"📝 **บันทึกช่วยจำ:** >>> {message}",
            color=0x3498db  # Material Blue
        )
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        embed.set_author(name="ตั้งเวลาเตือนความจำ • Reminder Set", icon_url=avatar_url)
        embed.set_footer(text="Javis Reminder Service", icon_url=avatar_url)
        await interaction.response.send_message(embed=embed)

        # Wait non-blockingly
        await asyncio.sleep(seconds)

        # Trigger notification
        try:
            # We ping the user who set the reminder
            reminder_embed = discord.Embed(
                description=f"📢 **แจ้งเตือนเหตุการณ์ครบกำหนด:**\n\n>>> {message}",
                color=0xe67e22  # Orange Alert
            )
            reminder_embed.set_author(name="ระบบแจ้งเตือนความจำ • Alert Notification", icon_url=avatar_url)
            reminder_embed.set_footer(text=f"เตือนความจำตั้งขึ้นจากเมื่อ {unit_display} ที่แล้ว", icon_url=avatar_url)
            await interaction.channel.send(content=interaction.user.mention, embed=reminder_embed)
        except Exception as e:
            print(f"Error sending reminder: {e}")

async def setup(bot):
    await bot.add_cog(ReminderCog(bot))
