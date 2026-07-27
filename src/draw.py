import discord
from discord.ext import commands
from discord import app_commands
import urllib.parse
import random

class DrawControlView(discord.ui.View):
    def __init__(self, prompt: str):
        # View timeout is 5 minutes (300s) to free resources, but can be interacted with multiple times
        super().__init__(timeout=300)
        self.prompt = prompt

    @discord.ui.button(label="สร้างใหม่ (Regenerate)", style=discord.ButtonStyle.primary, emoji="🔄")
    async def regenerate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(thinking=True)
        
        # Create a new random seed to generate a different variant of the image
        new_seed = random.randint(1, 9999999)
        encoded_prompt = urllib.parse.quote(self.prompt)
        new_image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={new_seed}"

        # Re-build embed
        embed = discord.Embed(
            title=f"🎨 ภาพ AI: {self.prompt}",
            description=f"**ผู้ขอสร้าง:** {interaction.user.mention}\n*(ภาพแบบสุ่ม Seed: `{new_seed}`)*",
            color=discord.Color.random()
        )
        embed.set_image(url=new_image_url)
        embed.set_footer(text="Powered by Pollinations.ai")

        # Edit original message with new image
        await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=self)

class DrawCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="draw", description="สร้างรูปภาพด้วย AI จากคำอธิบาย (Prompt)")
    @app_commands.describe(prompt="รายละเอียดภาพที่ต้องการวาด (ภาษาอังกฤษจะประมวลผลได้ดีที่สุด)")
    async def draw(self, interaction: discord.Interaction, prompt: str):
        # We don't defer because generating the URL is instant. The client (Discord) will load the image!
        # But sending an instant response is even better as it renders immediately while loading.
        
        encoded_prompt = urllib.parse.quote(prompt.strip())
        seed = random.randint(1, 9999999)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={seed}"

        embed = discord.Embed(
            title=f"🎨 ภาพ AI: {prompt}",
            description=f"**ผู้ขอสร้าง:** {interaction.user.mention}\n*(กำลังประมวลผลภาพ...)*",
            color=discord.Color.random()
        )
        embed.set_image(url=image_url)
        embed.set_footer(text="Powered by Pollinations.ai")

        view = DrawControlView(prompt)
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(DrawCog(bot))
