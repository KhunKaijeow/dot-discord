import logging
import re
from typing import Any, Literal
import discord
from discord import app_commands
from discord.ext import commands

from ..services.database import Database

logger = logging.getLogger("discord.javis")


class BasicInfoModal(discord.ui.Modal):
    def __init__(self, cog: "WelcomeCog", guild_id: int, event_type: Literal["welcome", "leave"], current_config: dict[str, Any]):
        super().__init__(title=f"Editing: {event_type.capitalize()} Card")
        self.cog = cog
        self.guild_id = guild_id
        self.event_type = event_type
        self.current_config = current_config

        self.card_title = discord.ui.TextInput(
            label="Title",
            default=current_config.get("title", ""),
            placeholder="e.g. Welcome to {server_name}!",
            max_length=256,
            required=False
        )
        self.description = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            default=current_config.get("description", ""),
            placeholder="e.g. ยินดีต้อนรับคุณ {member} เข้าสู่เซิร์ฟเวอร์นะครับ! 💖",
            max_length=2000,
            required=True
        )
        self.color_hex = discord.ui.TextInput(
            label="Hex Color",
            default=current_config.get("color", ""),
            placeholder="e.g. #ffb6c1",
            max_length=7,
            required=False
        )

        self.add_item(self.card_title)
        self.add_item(self.description)
        self.add_item(self.color_hex)

    async def on_submit(self, interaction: discord.Interaction):
        color_val = self.color_hex.value.strip()
        if color_val:
            clean_hex = color_val.lstrip("#")
            if not re.match(r"^[0-9a-fA-F]{6}$", clean_hex):
                await interaction.response.send_message(
                    "❌ รหัสสี Hex ไม่ถูกต้อง กรุณากรอกแบบ 6 หลัก เช่น `#ffb6c1`",
                    ephemeral=True
                )
                return

        self.current_config["type"] = "embed"
        self.current_config["title"] = self.card_title.value.strip()
        self.current_config["description"] = self.description.value.strip()
        self.current_config["color"] = color_val

        self.cog.database.save_welcome_config(self.guild_id, self.event_type, self.current_config)
        await interaction.response.send_message(
            f"✅ อัปเดตข้อมูลพื้นฐานการ์ด **{self.event_type.capitalize()}** สำเร็จแล้วครับ!",
            ephemeral=True
        )


class ImagesModal(discord.ui.Modal):
    def __init__(self, cog: "WelcomeCog", guild_id: int, event_type: Literal["welcome", "leave"], current_config: dict[str, Any]):
        super().__init__(title=f"Editing Images: {event_type.capitalize()} Card")
        self.cog = cog
        self.guild_id = guild_id
        self.event_type = event_type
        self.current_config = current_config

        self.image_url = discord.ui.TextInput(
            label="Banner Image / GIF URL",
            default=current_config.get("image_url", ""),
            placeholder="e.g. https://media.giphy.com/...",
            required=False
        )
        self.thumbnail_mode = discord.ui.TextInput(
            label="Thumbnail Mode (User Avatar / Server Icon / None)",
            default=current_config.get("thumbnail_mode", "None"),
            placeholder="User Avatar, Server Icon, or None",
            max_length=20,
            required=False
        )

        self.add_item(self.image_url)
        self.add_item(self.thumbnail_mode)

    async def on_submit(self, interaction: discord.Interaction):
        mode = self.thumbnail_mode.value.strip().title()
        if mode not in ["User Avatar", "Server Icon", "None"]:
            mode = "None"

        self.current_config["type"] = "embed"
        self.current_config["image_url"] = self.image_url.value.strip()
        self.current_config["thumbnail_mode"] = mode

        self.cog.database.save_welcome_config(self.guild_id, self.event_type, self.current_config)
        await interaction.response.send_message(
            f"✅ อัปเดตภาพการ์ด **{self.event_type.capitalize()}** สำเร็จแล้วครับ!",
            ephemeral=True
        )


class WelcomeEditorView(discord.ui.View):
    def __init__(self, cog: "WelcomeCog", guild_id: int, event_type: Literal["welcome", "leave"]):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.event_type = event_type

    def _get_config(self) -> dict[str, Any]:
        settings = self.cog.database.get_welcome_settings(self.guild_id)
        config = None
        if settings:
            config = settings[f"{self.event_type}_config"]
        if not config:
            config = {}
        return config

    @discord.ui.button(
        label="edit basic information (color / title / description)",
        style=discord.ButtonStyle.secondary,
        custom_id="edit_basic_info"
    )
    async def edit_basic_info(self, interaction: discord.Interaction, _: discord.ui.Button):
        config = self._get_config()
        modal = BasicInfoModal(self.cog, self.guild_id, self.event_type, config)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="edit images",
        style=discord.ButtonStyle.secondary,
        custom_id="edit_images"
    )
    async def edit_images(self, interaction: discord.Interaction, _: discord.ui.Button):
        config = self._get_config()
        modal = ImagesModal(self.cog, self.guild_id, self.event_type, config)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="test",
        style=discord.ButtonStyle.success,
        custom_id="test_notification"
    )
    async def test_notification(self, interaction: discord.Interaction, _: discord.ui.Button):
        settings = self.cog.database.get_welcome_settings(self.guild_id)
        if not settings or not settings["channel_id"]:
            await interaction.response.send_message(
                "❌ กรุณาตั้งค่าช่องส่งการ์ดด้วยคำสั่ง `/welcome-channel` ก่อนทำการทดสอบครับ",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"⏳ กำลังจำลองการส่งการ์ด **{self.event_type.capitalize()}** ไปยังช่องการแจ้งเตือน...",
            ephemeral=True
        )
        if isinstance(interaction.user, discord.Member):
            await self.cog._send_notification(interaction.guild, interaction.user, self.event_type)


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.database = getattr(bot, "database", None) or Database()

    def _format_text(self, text: str, member: discord.Member) -> str:
        """Replace placeholders in template text with actual member and guild values."""
        if not text:
            return ""
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
        """Parse hex color string to int."""
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
            # Default fallback configs
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

                member_count_text = f"คุณคือสมาชิกคนที่ {guild.member_count}" if config_type == "welcome" else f"เหลือสมาชิกทั้งหมด {guild.member_count} คน"
                embed.set_footer(text=member_count_text)

                thumbnail_mode = config.get("thumbnail_mode", "None")
                if thumbnail_mode == "User Avatar":
                    embed.set_thumbnail(url=member.display_avatar.url)
                elif thumbnail_mode == "Server Icon" and guild.icon:
                    embed.set_thumbnail(url=guild.icon.url)

                image_url = config.get("image_url")
                if image_url:
                    embed.set_image(url=image_url)

                await channel.send(embed=embed)
        except Exception:
            logger.exception("Failed to send welcome/goodbye notification for guild %s", guild.id)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._send_notification(member.guild, member, "welcome")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
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
        description="ตั้งค่าข้อความดิบต้อนรับหรือบอกลาแบบข้อความธรรมดา (ไม่ใช้ Embed)",
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
        description="เปิดใช้งานเครื่องมือออกแบบการ์ด Embed ต้อนรับ/บอกลาแบบโต้ตอบ (Interactive Embed Builder)",
    )
    @app_commands.describe(
        event_type="เลือกประเภทกิจกรรมที่ต้องการออกแบบการ์ด Embed"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_set_embed(
        self,
        interaction: discord.Interaction,
        event_type: Literal["Welcome", "Goodbye"]
    ) -> None:
        if not interaction.guild:
            return

        config_type = "welcome" if event_type == "Welcome" else "leave"
        view = WelcomeEditorView(self, interaction.guild.id, config_type)

        embed = discord.Embed(
            title=f"⭐ successfully created an embed called: {config_type}",
            description=(
                "please select from the buttons below for what you'd like to edit!\n"
                "alternatively, you can edit these individually in slash commands with `/embed edit`."
            ),
            color=0x2ecc71
        )

        await interaction.response.send_message(
            embed=embed,
            view=view,
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

        await interaction.response.send_message(
            "⏳ กำลังทำการทดสอบจำลองส่งข้อความต้อนรับและบอกลาไปยังช่องการแจ้งเตือน...",
            ephemeral=True
        )
        
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
