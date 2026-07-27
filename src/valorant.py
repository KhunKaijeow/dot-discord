import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from src.config import VALORANT_API_KEY

class ValorantCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="valorant-status", description="ตรวจสอบสถานะเซิร์ฟเวอร์เกม Valorant")
    @app_commands.describe(region="ภูมิภาคของเซิร์ฟเวอร์ เช่น ap (Asia-Pacific), na (North America), eu (Europe), kr (Korea)")
    @app_commands.choices(region=[
        app_commands.Choice(name="Asia-Pacific (ap)", value="ap"),
        app_commands.Choice(name="North America (na)", value="na"),
        app_commands.Choice(name="Europe (eu)", value="eu"),
        app_commands.Choice(name="Korea (kr)", value="kr"),
        app_commands.Choice(name="Latin America (latam)", value="latam"),
        app_commands.Choice(name="Brazil (br)", value="br")
    ])
    async def valorant_status(self, interaction: discord.Interaction, region: str = "ap"):
        await interaction.response.defer(thinking=True)

        if not VALORANT_API_KEY or VALORANT_API_KEY == "your_valorant_api_key_here":
            # Show helpful configuration guide embed
            # Show helpful configuration guide embed
            embed = discord.Embed(
                description="ℹ️ **ฟีเจอร์นี้เชื่อมต่อผ่าน Unofficial Valorant API (HenrikDev) ซึ่งต้องใช้ API Key ฟรีเพื่อสืบค้นสถานะเซิร์ฟเวอร์ครับ**",
                color=0xff4655  # Valorant Riot Red
            )
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            embed.set_author(name="Valorant API Setup Required", icon_url=avatar_url)
            
            embed.add_field(
                name="📋 ขั้นตอนการตั้งค่าเปิดใช้งาน:",
                value="1️⃣ เข้าไปที่หน้าเว็บ [HenrikDev Dashboard](https://api.henrikdev.xyz/dashboard/)\n"
                      "2️⃣ ล็อกอินด้วยบัญชี Discord เพื่อเคลม **Basic API Key** ฟรี\n"
                      "3️⃣ คัดลอกค่าคีย์บอร์ดที่ได้ (จะขึ้นต้นด้วย `HDEV-...`)\n"
                      "4️⃣ นำไปใส่ในไฟล์ `.env` ช่องตัวแปร `VALORANT_API_KEY`\n"
                      "5️⃣ สั่งรีสตาร์ทบอทเพื่อเริ่มใช้งานคำสั่งได้ทันทีครับ",
                inline=False
            )
            embed.set_footer(text="Javis Security & Integration", icon_url=avatar_url)
            await interaction.followup.send(embed=embed)
            return

        # Query HenrikDev API
        url = f"https://api.henrikdev.xyz/valorant/v1/status/{region}"
        headers = {"Authorization": VALORANT_API_KEY}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                    
                    if response.status == 200:
                        data = await response.json()
                        api_data = data.get("data", {})
                        maintenances = api_data.get("maintenances", [])
                        incidents = api_data.get("incidents", [])

                        # Build beautiful status embed
                        is_healthy = not maintenances and not incidents
                        embed = discord.Embed(
                            description=f"🎮 **เซิร์ฟเวอร์ภูมิภาค:** `{region.upper()}`",
                            color=0x2ecc71 if is_healthy else 0xff4655
                        )
                        embed.set_author(name="สถานะเซิร์ฟเวอร์ VALORANT Status", icon_url=avatar_url)

                        # Handle Maintenance
                        if maintenances:
                            m_text = ""
                            for m in maintenances:
                                title = m.get("titles", [{}])[0].get("content", "การซ่อมบำรุงเซิร์ฟเวอร์")
                                updates = m.get("updates", [])
                                update_text = updates[0].get("translations", [{}])[0].get("content", "กำลังดำเนินการ") if updates else ""
                                m_text += f"⚙️ **{title}**\n> *{update_text}*\n\n"
                            embed.add_field(name="🛠️ กำลังปิดปรับปรุง (Maintenance)", value=m_text[:1024], inline=False)
                        else:
                            embed.add_field(name="🛠️ กำลังปิดปรับปรุง (Maintenance)", value="✅ เซิร์ฟเวอร์เปิดทำงานปกติ ไม่มีกำหนดการปิดปรับปรุงขณะนี้", inline=False)

                        # Handle Incidents
                        if incidents:
                            i_text = ""
                            for inc in incidents:
                                title = inc.get("titles", [{}])[0].get("content", "พบข้อผิดพลาดของเซิร์ฟเวอร์")
                                updates = inc.get("updates", [])
                                update_text = updates[0].get("translations", [{}])[0].get("content", "กำลังแก้ไขปัญหา") if updates else ""
                                i_text += f"🚨 **{title}**\n> *{update_text}*\n\n"
                            embed.add_field(name="🚨 ปัญหาระบบเซิร์ฟเวอร์ (Incidents)", value=i_text[:1024], inline=False)
                        else:
                            embed.add_field(name="🚨 ปัญหาระบบเซิร์ฟเวอร์ (Incidents)", value="✅ ระบบทำงานปกติ ไม่พบบัญชีรายงานเหตุขัดข้องใดๆ", inline=False)

                        embed.set_footer(text="Data powered by HenrikDev API", icon_url=avatar_url)
                        await interaction.followup.send(embed=embed)
                    elif response.status == 401:
                        embed = discord.Embed(
                            title="❌ เข้าใช้งานไม่สำเร็จ (401 Unauthorized)",
                            description="รหัสคีย์ `VALORANT_API_KEY` ในไฟล์ `.env` ไม่ถูกต้องหรือหมดอายุการใช้งานแล้วครับ กรุณาสร้างคีย์ใหม่ที่ [HenrikDev Dashboard](https://api.henrikdev.xyz/dashboard/)",
                            color=0xff4655
                        )
                        embed.set_footer(text="Javis API Authentication Service", icon_url=avatar_url)
                        await interaction.followup.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title="❌ ดึงข้อมูลล้มเหลว",
                            description=f"เกิดข้อผิดพลาดในการติดต่อฐานข้อมูล API (HTTP Code: {response.status})",
                            color=0xff4655
                        )
                        embed.set_footer(text="Javis API Connection Service", icon_url=avatar_url)
                        await interaction.followup.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="❌ เกิดข้อผิดพลาดทางเทคนิค",
                description=f"ไม่สามารถทำรายการตรวจสอบข้อมูลได้ในขณะนี้: {e}",
                color=0xff4655
            )
            embed.set_footer(text="Javis Connection Service", icon_url=avatar_url)
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ValorantCog(bot))
