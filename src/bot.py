"""Discord bot composition and core AI chat commands."""

import asyncio
from datetime import datetime, timezone
import logging

import discord
from discord import app_commands
from discord.ext import commands

from .services.gemini import GeminiService
from .services.database import Database


logger = logging.getLogger("discord.javis")


COG_EXTENSIONS = (
    "src.cogs.music",
    "src.cogs.valorant",
    "src.cogs.stock",
    "src.cogs.weather",
    "src.cogs.crypto",
    "src.cogs.lyrics",
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
    "src.cogs.ai_tools",
)


class GeminiBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(
            command_prefix="!",
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.gemini_service = GeminiService()
        self.database = Database()
        self.started_at = datetime.now(timezone.utc)

    async def setup_hook(self):
        for extension in COG_EXTENSIONS:
            await self.load_extension(extension)


bot = GeminiBot()

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    print(f"Logged in as {bot.user.name} ({bot.user.id})")

@bot.tree.command(name="ask", description="ถามคำถามหรือคุยต่อเนื่องกับ Typhoon AI")
@app_commands.describe(prompt="คำถามของคุณ")
@app_commands.checks.cooldown(5, 60.0, key=lambda interaction: interaction.user.id)
async def ask(interaction: discord.Interaction, prompt: str):
    prompt = prompt.strip()
    if not 1 <= len(prompt) <= 4000:
        await interaction.response.send_message("คำถามต้องมีความยาว 1–4,000 ตัวอักษร", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    try:
        # Retrieve or create chat session for this specific channel
        chat = bot.gemini_service.get_or_create_chat(interaction.channel_id)
        # Send message asynchronously using a threadpool to prevent blocking the gateway
        response = await asyncio.to_thread(chat.send_message, prompt)
        answer = response.text
    except Exception as e:
        print(f"Typhoon request failed: {e}")
        answer = "ขอโทษนะ ตอนนี้ผมคุยกับ Typhoon ไม่สำเร็จ ลองถามใหม่อีกครั้งในอีกสักครู่นะครับ 🙏"

    embed = discord.Embed(
        color=0x1a73e8  # Premium Google Blue
    )
    avatar_url = bot.user.display_avatar.url if bot.user else None
    embed.set_author(name="Javis AI • มาคุยกันเถอะ", icon_url=avatar_url)
    embed.add_field(name="💬 คำถามของคุณ", value=f">>> {prompt}", inline=False)
    
    # Truncate answer if too long
    if len(answer) > 2000:
        answer = answer[:1980] + "\n...(คำตอบยาวเกินไป ถูกจำกัดการแสดงผล)..."
    
    embed.add_field(name="🤖 คำตอบของผม", value=answer, inline=False)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="reset-chat", description="ล้างประวัติการสนทนาของช่องนี้")
async def reset_chat(interaction: discord.Interaction):
    bot.gemini_service.reset_chat(interaction.channel_id)
    embed = discord.Embed(
        description="🧹 **ล้างประวัติแชทให้แล้วนะ!** เริ่มคุยเรื่องใหม่กันได้เลยครับ",
        color=0x2ecc71  # Mint Green
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"ใช้งานถี่เกินไป กรุณารอ `{error.retry_after:.1f}` วินาที"
    elif isinstance(error, app_commands.MissingPermissions):
        message = "คุณไม่มีสิทธิ์เพียงพอสำหรับคำสั่งนี้"
    else:
        message = "คำสั่งทำงานไม่สำเร็จ กรุณาลองใหม่ภายหลัง"
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
