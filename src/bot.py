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
    "src.cogs.music",
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
    "src.cogs.ai_tools",
)


class JavisBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(
            command_prefix="!",
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.http = HttpClient()
        self.ai_service = TyphoonService(http_client=self.http)
        self.database = Database()
        self.started_at = datetime.now(timezone.utc)

    async def setup_hook(self) -> None:
        await self.http.start()
        for extension in COG_EXTENSIONS:
            await self.load_extension(extension)
        try:
            synced = await self.tree.sync()
            logger.info("Synced %d command(s)", len(synced))
        except Exception:
            logger.exception("Failed to sync application commands")

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            await self.http.close()


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
        description=(
            f"**💬 คุณถามว่า**\n> {display_prompt}\n\n"
            f"**✨ คำตอบจากผม**\n{answer}"
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
        title="🧹 เริ่มบทสนทนาใหม่แล้ว",
        description="เคลียร์เรื่องเก่าให้เรียบร้อย เริ่มคุยเรื่องใหม่กันได้เลย!",
        color=EmbedColor.SUCCESS,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"ใจเย็นนิดนึงนะ รออีก `{error.retry_after:.1f}` วินาทีแล้วลองใหม่ได้เลย"
    elif isinstance(error, app_commands.MissingPermissions):
        message = "คำสั่งนี้ต้องใช้สิทธิ์ผู้ดูแลเพิ่มอีกนิดนะ"
    else:
        message = "อุ๊ปส์ คำสั่งสะดุดนิดหน่อย ลองใหม่อีกทีนะ"
        root_error = getattr(error, "original", error)
        logger.error(
            "Application command failed: %s",
            type(root_error).__name__,
            exc_info=(type(root_error), root_error, root_error.__traceback__),
        )
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)
