"""Valorant service status slash commands."""

import discord
from discord.ext import commands
from discord import app_commands
from ..config import VALORANT_API_KEY
from ..ui import EmbedColor, make_embed, set_embed_author

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
            embed = make_embed(
                self.bot,
                "VALORANT",
                title="⚠️ ต้องตั้งค่า API Key",
                description="ก่อนเช็กสถานะเกม ใส่คีย์ฟรีจาก HenrikDev ให้ผมก่อนนะ",
                color=EmbedColor.WARNING,
            )

            embed.add_field(
                name="วิธีตั้งค่า",
                value="1. เปิด [HenrikDev Dashboard](https://api.henrikdev.xyz/dashboard/) และล็อกอิน\n"
                      "2. สร้าง **Basic API Key** แล้วคัดลอกคีย์ `HDEV-...`\n"
                      "3. ใส่ใน `.env` ที่ `VALORANT_API_KEY`\n"
                      "4. รีสตาร์ทบอทแล้วลองอีกครั้ง",
                inline=False
            )
            await interaction.followup.send(embed=embed)
            return

        # Query HenrikDev API
        url = f"https://api.henrikdev.xyz/valorant/v1/status/{region}"
        headers = {"Authorization": VALORANT_API_KEY}

        try:
            async with self.bot.external_http.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    api_data = data.get("data", {})
                    maintenances = api_data.get("maintenances", [])
                    incidents = api_data.get("incidents", [])

                    # Build beautiful status embed
                    is_healthy = not maintenances and not incidents
                    embed = discord.Embed(
                        title="🎮 สถานะ VALORANT",
                        description=f"ภูมิภาค `{region.upper()}` • {'ระบบปกติ' if is_healthy else 'พบประกาศที่ควรตรวจสอบ'}",
                        color=0x2ecc71 if is_healthy else 0xff4655
                    )
                    set_embed_author(embed, self.bot, "VALORANT")

                    # Handle Maintenance
                    if maintenances:
                        m_text = ""
                        for m in maintenances:
                            title = m.get("titles", [{}])[0].get("content", "การซ่อมบำรุงเซิร์ฟเวอร์")
                            updates = m.get("updates", [])
                            update_text = updates[0].get("translations", [{}])[0].get("content", "กำลังดำเนินการ") if updates else ""
                            m_text += f"**{title}**\n> {update_text}\n\n"
                        embed.add_field(name="🛠️ การปิดปรับปรุง", value=m_text[:1024], inline=False)
                    else:
                        embed.add_field(name="🛠️ การปิดปรับปรุง", value="ไม่พบประกาศ", inline=True)

                    # Handle Incidents
                    if incidents:
                        i_text = ""
                        for inc in incidents:
                            title = inc.get("titles", [{}])[0].get("content", "พบข้อผิดพลาดของเซิร์ฟเวอร์")
                            updates = inc.get("updates", [])
                            update_text = updates[0].get("translations", [{}])[0].get("content", "กำลังแก้ไขปัญหา") if updates else ""
                            i_text += f"**{title}**\n> {update_text}\n\n"
                        embed.add_field(name="🚨 เหตุขัดข้อง", value=i_text[:1024], inline=False)
                    else:
                        embed.add_field(name="🚨 เหตุขัดข้อง", value="ไม่พบรายงาน", inline=True)

                    await interaction.followup.send(embed=embed)
                elif response.status == 401:
                    embed = make_embed(
                        self.bot,
                        "VALORANT",
                        title="❌ API Key ใช้งานไม่ได้",
                        description="คีย์ใน `.env` อาจหมดอายุ ลองสร้างใหม่ที่ [HenrikDev Dashboard](https://api.henrikdev.xyz/dashboard/) นะ",
                        color=EmbedColor.ERROR,
                    )
                    await interaction.followup.send(embed=embed)
                else:
                    embed = make_embed(
                        self.bot,
                        "VALORANT",
                        title="❌ โหลดสถานะเกมไม่สำเร็จ",
                        description=f"บริการตอบกลับด้วยรหัส `{response.status}` รอสักครู่แล้วลองใหม่อีกทีนะ",
                        color=EmbedColor.ERROR,
                    )
                    await interaction.followup.send(embed=embed)

        except Exception:
            embed = make_embed(
                self.bot,
                "VALORANT",
                title="❌ โหลดสถานะเกมไม่สำเร็จ",
                description="บริการเงียบไปนิดนึง รอสักครู่แล้วลองใหม่อีกทีนะ",
                color=EmbedColor.ERROR,
            )
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ValorantCog(bot))
