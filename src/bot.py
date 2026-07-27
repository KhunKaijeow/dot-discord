import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from src.gemini import GeminiService

class GeminiBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        # intents.message_content = True  # Commented out to avoid PrivilegedIntentsRequired error. Enable if using prefix commands.
        super().__init__(command_prefix="!", intents=intents)
        self.gemini_service = GeminiService()

    async def setup_hook(self):
        from src.music import setup as music_setup
        from src.valorant import setup as valorant_setup
        from src.stock import setup as stock_setup
        from src.weather import setup as weather_setup
        from src.crypto import setup as crypto_setup
        from src.lyrics import setup as lyrics_setup
        from src.draw import setup as draw_setup
        from src.news import setup as news_setup
        from src.reminder import setup as reminder_setup
        from src.translator import setup as translator_setup
        await music_setup(self)
        await valorant_setup(self)
        await stock_setup(self)
        await weather_setup(self)
        await crypto_setup(self)
        await lyrics_setup(self)
        await draw_setup(self)
        await news_setup(self)
        await reminder_setup(self)
        await translator_setup(self)

bot = GeminiBot()

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    print(f"Logged in as {bot.user.name} ({bot.user.id})")

@bot.tree.command(name="ask", description="ถามคำถามหรือคุยต่อเนื่องกับ Gemini AI")
@app_commands.describe(prompt="คำถามของคุณ")
async def ask(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer(thinking=True)
    try:
        # Retrieve or create chat session for this specific channel
        chat = bot.gemini_service.get_or_create_chat(interaction.channel_id)
        # Send message asynchronously using a threadpool to prevent blocking the gateway
        response = await asyncio.to_thread(chat.send_message, prompt)
        answer = response.text
    except Exception as e:
        answer = f"เกิดข้อผิดพลาดในการเรียกใช้งาน Gemini AI: {e}"

    embed = discord.Embed(
        color=0x1a73e8  # Premium Google Blue
    )
    avatar_url = bot.user.display_avatar.url if bot.user else None
    embed.set_author(name="Javis AI • ถามตอบอัจฉริยะ", icon_url=avatar_url)
    embed.add_field(name="💬 คำถามของคุณ", value=f">>> {prompt}", inline=False)
    
    # Truncate answer if too long
    if len(answer) > 2000:
        answer = answer[:1980] + "\n...(คำตอบยาวเกินไป ถูกจำกัดการแสดงผล)..."
    
    embed.add_field(name="🤖 คำตอบจากระบบ", value=answer, inline=False)
    embed.set_footer(text="Powered by Gemini 3.5 Flash", icon_url=avatar_url)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="reset-chat", description="ล้างประวัติการสนทนาของช่องนี้")
async def reset_chat(interaction: discord.Interaction):
    bot.gemini_service.reset_chat(interaction.channel_id)
    embed = discord.Embed(
        description="🧹 **ล้างประวัติการสนทนาในช่องแชทนี้สำเร็จเรียบร้อย!** เริ่มแชทใหม่ได้ทันทีครับ",
        color=0x2ecc71  # Mint Green
    )
    avatar_url = bot.user.display_avatar.url if bot.user else None
    embed.set_footer(text="Javis AI Chat History Reset", icon_url=avatar_url)
    await interaction.response.send_message(embed=embed)
