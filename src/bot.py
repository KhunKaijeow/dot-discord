"""Discord bot composition and core AI chat commands."""

import asyncio
from datetime import datetime, timezone
import logging

import discord
from discord import app_commands
from discord.ext import commands

from .services.database import Database
from .services.http_client import HttpClient
from .services.typhoon import TyphoonService
from .ui import EmbedColor, make_embed


logger = logging.getLogger("discord.javis")


COG_EXTENSIONS = (
    "src.cogs.help",
    "src.cogs.valorant",
    "src.cogs.stock",
    "src.cogs.weather",
    "src.cogs.crypto",
    "src.cogs.draw",
    "src.cogs.news",
    "src.cogs.reminder",
    "src.cogs.translator",
    "src.cogs.horoscope",
    "src.cogs.x_notifier",
    "src.cogs.gold",
    "src.cogs.deals_notifier",
    "src.cogs.dashboard",
    "src.cogs.price_alerts",
    "src.cogs.morning_digest",
    "src.cogs.admin",
    "src.cogs.health",
    "src.cogs.privacy",
    "src.cogs.setup_check",
    "src.cogs.ai_tools",
    "src.cogs.music",
)


def app_command_error_message(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> str | None:
    """Map known command failures to actionable, non-sensitive messages."""
    if isinstance(error, app_commands.CommandOnCooldown):
        return f"ใจเย็นนิดนึงนะ รออีก `{error.retry_after:.1f}` วินาทีแล้วลองใหม่ได้เลย"
    if isinstance(error, app_commands.MissingPermissions):
        missing = ", ".join(error.missing_permissions)
        return f"คำสั่งนี้ต้องใช้สิทธิ์เพิ่ม: {missing}"
    if isinstance(error, app_commands.BotMissingPermissions):
        missing = ", ".join(error.missing_permissions)
        return f"บอทยังขาดสิทธิ์: {missing}"

    root_error = getattr(error, "original", error)
    if isinstance(root_error, discord.Forbidden):
        permissions = interaction.app_permissions
        missing = []
        if not permissions.view_channel:
            missing.append("View Channel")
        if not permissions.send_messages:
            missing.append("Send Messages")
        if not permissions.embed_links:
            missing.append("Embed Links")
        if not permissions.attach_files:
            missing.append("Attach Files")
        if missing:
            return f"บอทถูกปฏิเสธสิทธิ์ในห้องนี้: {', '.join(missing)}"
        return "Discord ปฏิเสธการทำงานของบอท ลองตรวจ Role และ Channel Overrides"
    if isinstance(root_error, discord.NotFound) and root_error.code in {10062, 10015}:
        return "คำสั่งหมดเวลาก่อนตอบกลับ ลองเรียกคำสั่งใหม่อีกครั้งนะ"
    if isinstance(root_error, TimeoutError):
        return "บริการภายนอกตอบช้าเกินไป รอสักครู่แล้วลองใหม่นะ"
    return None


class JavisBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix="!",
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.external_http = HttpClient()
        self.ai_service = TyphoonService(http_client=self.external_http)
        self.database = Database()
        self.started_at = datetime.now(timezone.utc)
        self.command_sync_succeeded: bool | None = None
        self.command_sync_count = 0

    async def setup_hook(self) -> None:
        await self.external_http.start()
        for extension in COG_EXTENSIONS:
            await self.load_extension(extension)
        try:
            synced = await self.tree.sync()
            self.command_sync_succeeded = True
            self.command_sync_count = len(synced)
            logger.info("Synced %d command(s)", len(synced))
        except Exception:
            self.command_sync_succeeded = False
            logger.exception("Failed to sync application commands")

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            await self.external_http.close()


bot = JavisBot()


@bot.event
async def on_ready() -> None:
    logger.info("Logged in as %s (%s)", bot.user.name, bot.user.id)


@bot.tree.command(name="ask", description="ถามคำถามหรือคุยต่อเนื่องกับ Typhoon AI")
@app_commands.describe(prompt="คำถามของคุณ")
@app_commands.checks.cooldown(5, 60.0, key=lambda interaction: interaction.user.id)
async def ask(interaction: discord.Interaction, prompt: str) -> None:
    prompt = prompt.strip()
    if not 1 <= len(prompt) <= 4000:
        await interaction.response.send_message("คำถามต้องมีความยาว 1–4,000 ตัวอักษร", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    try:
        # Retrieve or create chat session for this specific channel
        chat = bot.ai_service.get_or_create_chat(interaction.channel_id)
        # Send message asynchronously using a threadpool to prevent blocking the gateway
        response = await asyncio.to_thread(chat.send_message, prompt)
        answer = response.text
    except Exception:
        logger.exception("Typhoon request failed")
        answer = "อุ๊ปส์ ตอนนี้ผมต่อกับ Typhoon ไม่ติด ลองถามใหม่อีกทีในอีกสักครู่นะ 🙏"

    display_prompt = prompt
    if len(display_prompt) > 700:
        display_prompt = display_prompt[:697].rstrip() + "..."
    if len(answer) > 3000:
        answer = answer[:2960].rstrip() + "\n\n*คำตอบยาวมาก เลยย่อส่วนท้ายไว้นิดนึงนะ*"
    embed = make_embed(
        bot,
        "AI Chat",
        title="✨ คำตอบจาก Javis",
        description=(
            f"**คำถาม**\n> {display_prompt}\n\n"
            f"**คำตอบ**\n{answer}"
        ),
        color=EmbedColor.PRIMARY,
    )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="reset-chat", description="ล้างประวัติการสนทนาของช่องนี้")
async def reset_chat(interaction: discord.Interaction) -> None:
    bot.ai_service.reset_chat(interaction.channel_id)
    embed = make_embed(
        bot,
        "AI Chat",
        title="✅ เริ่มบทสนทนาใหม่แล้ว",
        description="ล้างประวัติของห้องนี้เรียบร้อย พร้อมคุยเรื่องใหม่ได้เลย",
        color=EmbedColor.SUCCESS,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    message = app_command_error_message(interaction, error)
    if message is None:
        message = "อุ๊ปส์ คำสั่งสะดุดนิดหน่อย ลองใหม่อีกทีนะ"
        root_error = getattr(error, "original", error)
        logger.error(
            "Application command failed: %s",
            type(root_error).__name__,
            exc_info=(type(root_error), root_error, root_error.__traceback__),
        )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        logger.exception("Could not deliver application command error message")
