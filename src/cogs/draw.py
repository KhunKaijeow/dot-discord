"""AI image generation slash commands using Together AI's FLUX.1 model."""

import discord
from discord.ext import commands
from discord import app_commands
import io
import aiohttp
import logging
from src.config import TOGETHER_API_KEY

logger = logging.getLogger(__name__)

async def generate_flux_image(prompt: str, api_key: str) -> tuple[discord.Embed, discord.File]:
    url = "https://api.together.xyz/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "black-forest-labs/FLUX.1-schnell-Free",
        "prompt": prompt,
        "steps": 4,
        "n": 1,
        "height": 1024,
        "width": 1024
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            if response.status != 200:
                resp_text = await response.text()
                raise ValueError(f"Together AI API returned error: HTTP {response.status} - {resp_text}")
            
            data = await response.json()
            image_data_list = data.get("data", [])
            if not image_data_list:
                raise ValueError(f"No image data returned: {data}")
            
            image_url = image_data_list[0].get("url")
            if not image_url:
                raise ValueError(f"No image URL in response data: {data}")
            
            # Download the image to a bytes buffer
            async with session.get(image_url) as img_response:
                if img_response.status != 200:
                    raise ValueError(f"Failed to download generated image from {image_url}")
                img_bytes = await img_response.read()
                
    img_buf = io.BytesIO(img_bytes)
    file = discord.File(img_buf, filename="flux_draw.png")
    
    embed = discord.Embed(
        title=f"🎨 ภาพ AI: {prompt}",
        color=discord.Color.random()
    )
    embed.set_image(url="attachment://flux_draw.png")
    return embed, file

class DrawControlView(discord.ui.View):
    def __init__(self, prompt: str, api_key: str):
        # View timeout is 5 minutes (300s) to free resources, but can be interacted with multiple times
        super().__init__(timeout=300)
        self.prompt = prompt
        self.api_key = api_key

    @discord.ui.button(label="สร้างใหม่ (Regenerate)", style=discord.ButtonStyle.primary, emoji="🔄")
    async def regenerate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        try:
            embed, file = await generate_flux_image(self.prompt, self.api_key)
            embed.description = f"**วาดให้:** {interaction.user.mention}\n*ลองสร้างเวอร์ชันใหม่ให้แล้ว ✨*"
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=self, attachments=[file])
        except Exception as e:
            logger.exception("Error regenerating image")
            await interaction.followup.send(f"❌ ขออภัย ไม่สามารถเจนรูปภาพใหม่ได้ในขณะนี้: {e}", ephemeral=True)

class DrawCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="draw", description="สร้างรูปภาพด้วย AI จากคำอธิบาย (Prompt)")
    @app_commands.describe(prompt="รายละเอียดภาพที่ต้องการวาด (ภาษาอังกฤษจะประมวลผลได้ดีที่สุด)")
    @app_commands.checks.cooldown(3, 60.0, key=lambda interaction: interaction.user.id)
    async def draw(self, interaction: discord.Interaction, prompt: str):
        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 500:
            await interaction.response.send_message("Prompt ต้องมีความยาว 1–500 ตัวอักษร", ephemeral=True)
            return
            
        await interaction.response.defer(thinking=True)

        try:
            embed, file = await generate_flux_image(prompt, TOGETHER_API_KEY)
            embed.description = f"**วาดให้:** {interaction.user.mention}\n*เนรมิตภาพเสร็จแล้วด้วย FLUX.1 🎨*"
            
            view = DrawControlView(prompt, TOGETHER_API_KEY)
            await interaction.followup.send(embed=embed, file=file, view=view)
        except Exception as e:
            logger.exception("Error generating image")
            await interaction.followup.send(f"❌ ขออภัย เกิดข้อผิดพลาดในการวาดภาพ: {e}")

async def setup(bot):
    await bot.add_cog(DrawCog(bot))
