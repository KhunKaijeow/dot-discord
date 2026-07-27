"""Translation slash commands."""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import urllib.parse

class TranslatorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="translate", description="แปลข้อความต่างๆ เป็นภาษาปลายทางด้วย Google Translate (ไม่ใช้ Gemini)")
    @app_commands.describe(
        text="ข้อความที่ต้องการแปล",
        to_language="ภาษาปลายทาง เช่น English, Japanese, Korean (ค่าเริ่มต้น: English)"
    )
    @app_commands.choices(to_language=[
        app_commands.Choice(name="English (อังกฤษ)", value="en"),
        app_commands.Choice(name="Thai (ไทย)", value="th"),
        app_commands.Choice(name="Japanese (ญี่ปุ่น)", value="ja"),
        app_commands.Choice(name="Korean (เกาหลี)", value="ko"),
        app_commands.Choice(name="Chinese (จีน)", value="zh-CN"),
        app_commands.Choice(name="French (ฝรั่งเศส)", value="fr"),
        app_commands.Choice(name="German (เยอรมัน)", value="de"),
        app_commands.Choice(name="Spanish (สเปน)", value="es"),
        app_commands.Choice(name="Russian (รัสเซีย)", value="ru"),
    ])
    async def translate(self, interaction: discord.Interaction, text: str, to_language: str = "en"):
        await interaction.response.defer(thinking=True)

        encoded_text = urllib.parse.quote(text.strip())
        
        # Free public keyless Google Translate API endpoint
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={to_language}&dt=t&q={encoded_text}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        
                        # Extract translation segments
                        translation_segments = data[0]
                        translated_text = "".join(segment[0] for segment in translation_segments if segment[0])
                        
                        # Extract detected source language
                        detected_lang = data[2] if len(data) > 2 else "auto"

                        # Build beautiful Embed card
                        embed = discord.Embed(
                            description=f"🌐 **ทิศทางการแปล:** `{detected_lang.upper()}` ➡️ `{to_language.upper()}`",
                            color=0x1abc9c  # Teal color
                        )
                        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                        embed.set_author(name="แปลภาษาอัจฉริยะ • AI Translation", icon_url=avatar_url)
                        
                        embed.add_field(name="📥 ข้อความต้นฉบับ", value=f"```\n{text}\n```", inline=False)
                        embed.add_field(name="📤 ผลลัพธ์การแปล", value=f"```\n{translated_text}\n```", inline=False)
                        
                        embed.set_footer(text="Translated via Google Translate (Keyless)", icon_url=avatar_url)

                        await interaction.followup.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title="❌ แปลภาษาล้มเหลว",
                            description=f"เกิดข้อผิดพลาดในการดึงข้อมูลแปลจากระบบ (HTTP Code: {response.status})",
                            color=0xe74c3c
                        )
                        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                        embed.set_footer(text="Javis Translation Service", icon_url=avatar_url)
                        await interaction.followup.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="❌ เกิดข้อผิดพลาด",
                description=f"ไม่สามารถทำการแปลภาษาได้ในขณะนี้: {e}",
                color=0xe74c3c
            )
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            embed.set_footer(text="Javis Translation Service", icon_url=avatar_url)
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(TranslatorCog(bot))
