"""AI image generation slash commands using Together AI's FLUX.1 model."""

import io
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ..config import TOGETHER_API_KEY


logger = logging.getLogger(__name__)

TOGETHER_IMAGE_URL = "https://api.together.xyz/v1/images/generations"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=90)


class ImageGenerationError(RuntimeError):
    """Raised when Together AI cannot produce a downloadable image."""


async def generate_flux_image(
    prompt: str,
    api_key: str | None,
) -> tuple[discord.Embed, discord.File]:
    if not api_key:
        raise ImageGenerationError("TOGETHER_API_KEY is not configured")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "black-forest-labs/FLUX.1-schnell-Free",
        "prompt": prompt,
        "steps": 4,
        "n": 1,
        "height": 1024,
        "width": 1024,
    }

    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
        async with session.post(TOGETHER_IMAGE_URL, json=payload, headers=headers) as response:
            if response.status != 200:
                raise ImageGenerationError(f"Together AI returned HTTP {response.status}")

            data = await response.json()
            image_data_list = data.get("data", [])
            if not image_data_list:
                raise ImageGenerationError("Together AI returned no image data")

            image_url = image_data_list[0].get("url")
            if not image_url:
                raise ImageGenerationError("Together AI returned no image URL")

            async with session.get(image_url) as img_response:
                if img_response.status != 200:
                    raise ImageGenerationError("Could not download the generated image")
                img_bytes = await img_response.read()

    img_buf = io.BytesIO(img_bytes)
    file = discord.File(img_buf, filename="flux_draw.png")

    embed = discord.Embed(
        title=f"🎨 ภาพ AI: {prompt}",
        color=discord.Color.random(),
    )
    embed.set_image(url="attachment://flux_draw.png")
    return embed, file


class DrawControlView(discord.ui.View):
    def __init__(self, prompt: str, api_key: str | None):
        super().__init__(timeout=300)
        self.prompt = prompt
        self.api_key = api_key

    @discord.ui.button(label="สร้างใหม่ (Regenerate)", style=discord.ButtonStyle.primary, emoji="🔄")
    async def regenerate_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            embed, file = await generate_flux_image(self.prompt, self.api_key)
            embed.description = f"**วาดให้:** {interaction.user.mention}\n*ลองสร้างเวอร์ชันใหม่ให้แล้ว ✨*"
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                embed=embed,
                view=self,
                attachments=[file],
            )
        except Exception:
            logger.exception("Error regenerating image")
            await interaction.followup.send(
                "❌ ขออภัย ไม่สามารถสร้างรูปภาพใหม่ได้ในขณะนี้",
                ephemeral=True,
            )


class DrawCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="draw", description="สร้างรูปภาพด้วย AI จากคำอธิบาย (Prompt)")
    @app_commands.describe(prompt="รายละเอียดภาพที่ต้องการวาด (ภาษาอังกฤษจะประมวลผลได้ดีที่สุด)")
    @app_commands.checks.cooldown(3, 60.0, key=lambda interaction: interaction.user.id)
    async def draw(self, interaction: discord.Interaction, prompt: str) -> None:
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
        except Exception:
            logger.exception("Error generating image")
            await interaction.followup.send("❌ ขออภัย ไม่สามารถสร้างรูปภาพได้ในขณะนี้")


async def setup(bot):
    await bot.add_cog(DrawCog(bot))
