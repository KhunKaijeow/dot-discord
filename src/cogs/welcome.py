import logging
import re
from typing import Any, Literal
import discord
from discord import app_commands
from discord.ext import commands

from ..services.database import Database

logger = logging.getLogger("discord.javis")


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Retrieve db instance from bot or instantiate it
        self.database = getattr(bot, "database", None) or Database()

    def _format_text(self, text: str, member: discord.Member) -> str:
        """Replace placeholders in template text with actual member and guild values."""
        if not text:
            return ""
        # Placeholders mapping
        replacements = {
            "{member}": member.mention,
            "{member_name}": member.name,
            "{server_name}": member.guild.name,
            "{guild_name}": member.guild.name,
            "{member_count}": str(member.guild.member_count),
        }
        for placeholder, value in replacements.items():
            text = text.replace(placeholder, value)
        return text

    def _parse_color(self, hex_str: str | None, default_color: int) -> int:
        """Parse hex color string (e.g., '#ffb6c1' or 'ffb6c1') to int."""
        if not hex_str:
            return default_color
        hex_str = hex_str.strip().lstrip("#")
        try:
            return int(hex_str, 16)
        except ValueError:
            return default_color

    async def _send_notification(self, guild: discord.Guild, member: discord.Member, config_type: Literal["welcome", "leave"]) -> None:
        """Formats and sends the welcome/goodbye notification to the configured channel."""
        settings = self.database.get_welcome_settings(guild.id)
        if not settings or not settings["channel_id"]:
            return

        channel = guild.get_channel(settings["channel_id"])
        if not channel or not isinstance(channel, discord.TextChannel):
            logger.warning(
                "Welcome channel ID %s for guild %s not found or is not a text channel.",
                settings["channel_id"],
                guild.id
            )
            return

        config = settings[f"{config_type}_config"]
        if not config:
            # Default fallback configs if not customized yet
            if config_type == "welcome":
                config = {
                    "type": "embed",
                    "title": "ยินดีต้อนรับสมาชิกใหม่! 🌸",
                    "description": "ยินดีต้อนรับคุณ {member} เข้าสู่เซิร์ฟเวอร์ {server_name}! 🎉",
                    "color": "ffb6c1",
                    "thumbnail_mode": "User Avatar"
                }
            else:
                config = {
                    "type": "embed",
                    "title": "ลาก่อนนะ... ☁️",
                    "description": "{member_name} ได้ออกจากเซิร์ฟเวอร์ {server_name} ไปแล้ว 👋",
                    "color": "95a5a6",
                    "thumbnail_mode": "User Avatar"
                }

        try:
            if config.get("type") == "text":
                content = self._format_text(config.get("text", ""), member)
                # Allow user mentions in text notifications
                await channel.send(
                    content=content,
                    allowed_mentions=discord.AllowedMentions(users=True)
                )
            else:  # Embed mode
                description = self._format_text(config.get("description", ""), member)
                title = self._format_text(config.get("title", ""), member)
                
                default_color = 0xffb6c1 if config_type == "welcome" else 0x95a5a6
                color = self._parse_color(config.get("color"), default_color)

                embed = discord.Embed(
                    description=description,
                    color=color
                )
                if title:
                    embed.title = title

                # Footer with member count
                member_count_text = f"คุณคือสมาชิกคนที่ {guild.member_count}" if config_type == "welcome" else f"เหลือสมาชิกทั้งหมด {guild.member_count} คน"
                embed.set_footer(text=member_count_text)

                # Thumbnail configuration
                thumbnail_mode = config.get("thumbnail_mode", "None")
                if thumbnail_mode == "User Avatar":
                    embed.set_thumbnail(url=member.display_avatar.url)
                elif thumbnail_mode == "Server Icon" and guild.icon:
                    embed.set_thumbnail(url=guild.icon.url)

                # Big image configuration (banner or GIF)
                image_url = config.get("image_url")
                if image_url:
                    embed.set_image(url=image_url)

                # Mentions inside embed description (does not ping users, but highlights name)
                await channel.send(embed=embed)
        except Exception:
            logger.exception("Failed to send welcome/goodbye notification for guild %s", guild.id)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Triggered when a member joins the guild."""
        await self._send_notification(member.guild, member, "welcome")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Triggered when a member leaves the guild."""
        await self._send_notification(member.guild, member, "leave")

    # Slash commands
    @app_commands.command(
        name="welcome-channel",
        description="ตั้งค่าช่องที่จะส่งการ์ดต้อนรับและบอกลาสมาชิกใหม่ (Welcome & Goodbye)",
    )
    @app_commands.describe(channel="ช่องข้อความที่ต้องการส่งการ์ด")
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not interaction.guild:
            await interaction.response.send_message("คำสั่งนี้ใช้ได้เฉพาะในเซิร์ฟเวอร์ครับ", ephemeral=True)
            return

        # Check permissions
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ คุณต้องมีสิทธิ์ Manage Channels เพื่อตั้งค่าช่องครับ", ephemeral=True)
            return

        self.database.save_welcome_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"✅ ตั้งค่าช่องส่งข้อความต้อนรับและบอกลาสมาชิกใหม่ไปที่ {channel.mention} เรียบร้อยครับ!",
            ephemeral=True
        )

    @app_commands.command(
        name="welcome-set-message",
        description="ตั้งค่าข้อความดิบต้อนรับหรือบอกลาแบบข้อความธรรมดา (ไม่ใส่ Embed)",
    )
    @app_commands.describe(
        event_type="ประเภทกิจกรรม (Welcome = ต้อนรับคนเข้า / Goodbye = บอกลาคนออก)",
        text="ข้อความที่ต้องการพิมพ์ (รองรับ {member}, {member_name}, {server_name}, {member_count})"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_set_message(
        self,
        interaction: discord.Interaction,
        event_type: Literal["Welcome", "Goodbye"],
        text: str
    ) -> None:
        if not interaction.guild:
            return

        config_type = "welcome" if event_type == "Welcome" else "leave"
        config = {
            "type": "text",
            "text": text
        }
        self.database.save_welcome_config(interaction.guild.id, config_type, config)
        
        # Check if channel is configured
        settings = self.database.get_welcome_settings(interaction.guild.id)
        channel_status = ""
        if not settings or not settings["channel_id"]:
            channel_status = "\n⚠️ *หมายเหตุ: บอทยังไม่มีการตั้งค่าช่องส่งการ์ด กรุณาใช้คำสั่ง `/welcome-channel` ด้วยครับ*"

        await interaction.response.send_message(
            f"✅ ตั้งค่าข้อความธรรมดาของกิจกรรม **{event_type}** เรียบร้อยครับ!{channel_status}",
            ephemeral=True
        )

    @app_commands.command(
        name="welcome-set-embed",
        description="ตั้งค่าการ์ด Embed ต้อนรับหรือบอกลาสมาชิกใหม่สไตล์บอท mimu",
    )
    @app_commands.describe(
        event_type="ประเภทกิจกรรม (Welcome = ต้อนรับคนเข้า / Goodbye = บอกลาคนออก)",
        description="รายละเอียดเนื้อหาใน Embed (รองรับ {member}, {member_name}, {server_name}, {member_count})",
        title="หัวข้อของการ์ด Embed (รองรับตัวแปรเดียวกัน)",
        color_hex="รหัสสีของการ์ดแบบ Hex เช่น #ffb6c1 หรือ ffb6c1",
        thumbnail_mode="ประเภทของรูปภาพกล่องเล็กมุมขวาบน",
        image_url="ลิงก์ของรูปแบนเนอร์หรือภาพเคลื่อนไหว GIF ขนาดใหญ่ที่ท้ายการ์ด"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_set_embed(
        self,
        interaction: discord.Interaction,
        event_type: Literal["Welcome", "Goodbye"],
        description: str,
        title: str | None = None,
        color_hex: str | None = None,
        thumbnail_mode: Literal["User Avatar", "Server Icon", "None"] = "None",
        image_url: str | None = None
    ) -> None:
        if not interaction.guild:
            return

        # Validate hex color
        if color_hex:
            clean_hex = color_hex.strip().lstrip("#")
            if not re.match(r"^[0-9a-fA-F]{6}$", clean_hex):
                await interaction.response.send_message(
                    "❌ รหัสสี Hex ไม่ถูกต้อง กรุณากรอกแบบ 6 หลัก เช่น `#ffb6c1` หรือ `ffb6c1` ครับ",
                    ephemeral=True
                )
                return

        config_type = "welcome" if event_type == "Welcome" else "leave"
        config = {
            "type": "embed",
            "description": description,
            "title": title,
            "color": color_hex,
            "thumbnail_mode": thumbnail_mode,
            "image_url": image_url
        }
        self.database.save_welcome_config(interaction.guild.id, config_type, config)
        
        # Check if channel is configured
        settings = self.database.get_welcome_settings(interaction.guild.id)
        channel_status = ""
        if not settings or not settings["channel_id"]:
            channel_status = "\n⚠️ *หมายเหตุ: บอทยังไม่มีการตั้งค่าช่องส่งการ์ด กรุณาใช้คำสั่ง `/welcome-channel` ด้วยครับ*"

        await interaction.response.send_message(
            f"✅ ตั้งค่าการ์ด Embed สำหรับกิจกรรม **{event_type}** เรียบร้อยครับ!{channel_status}",
            ephemeral=True
        )

    @app_commands.command(
        name="welcome-test",
        description="ทดลองจำลองเหตุการณ์ส่งข้อความต้อนรับและบอกลา เพื่อดูหน้าตาของหน้าจอบนห้องแชท",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_test(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return

        settings = self.database.get_welcome_settings(interaction.guild.id)
        if not settings or not settings["channel_id"]:
            await interaction.response.send_message(
                "❌ กรุณาตั้งค่าช่องส่งการ์ดก่อนทดสอบด้วยคำสั่ง `/welcome-channel` ครับ",
                ephemeral=True
            )
            return

        # Inform the user and start the simulation
        await interaction.response.send_message(
            "⏳ กำลังทำการทดสอบจำลองส่งข้อความต้อนรับและบอกลาไปยังช่องการแจ้งเตือน...",
            ephemeral=True
        )
        
        # Simulate join and leave using the command sender's profile
        await self._send_notification(interaction.guild, interaction.user, "welcome")
        await self._send_notification(interaction.guild, interaction.user, "leave")

    @app_commands.command(
        name="welcome-disable",
        description="ปิดใช้งานและล้างค่าการตั้งค่าส่งข้อความต้อนรับ/บอกลาสมาชิกใหม่ทั้งหมดของเซิร์ฟเวอร์",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_disable(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return

        deleted = self.database.delete_welcome_settings(interaction.guild.id)
        if deleted:
            await interaction.response.send_message(
                "✅ ปิดใช้งานและลบข้อมูลต้อนรับ/บอกลาสมาชิกใหม่ของเซิร์ฟเวอร์เรียบร้อยครับ!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ เซิร์ฟเวอร์นี้ไม่มีการตั้งค่าต้อนรับ/บอกลาสมาชิกใหม่อยู่แล้วครับ",
                ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
