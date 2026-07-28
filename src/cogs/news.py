"""News lookup and display slash commands without AI dependency."""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import urllib.parse
import xml.etree.ElementTree as ET

class NewsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="news", description="ดึงหัวข้อข่าวเด่นล่าสุด (แสดงหัวข้อข่าวและลิงก์โดยตรง ไม่ใช้ AI)")
    @app_commands.describe(keyword="หัวข้อข่าวที่สนใจ เช่น คริปโต, เทคโนโลยี (ปล่อยว่างหากต้องการข่าวเด่นทั่วไป)")
    async def news(self, interaction: discord.Interaction, keyword: str = None):
        await interaction.response.defer(thinking=True)

        # Build Google News RSS Feed URL (Thai localized)
        if keyword and keyword.strip() != "":
            keyword_clean = keyword.strip()
            encoded_kw = urllib.parse.quote(keyword_clean)
            url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=th&gl=TH&ceid=TH:th"
            title_display = f"🔎 สรุปข่าวเด่นล่าสุดเกี่ยวกับ: {keyword_clean}"
        else:
            url = "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th"
            title_display = "📰 ข่าวเด่นประเด็นร้อนวันนี้"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise Exception(f"RSS API returned status {response.status}")
                    
                    xml_content = await response.text()
                    
                    # Parse XML using standard library ElementTree
                    root = ET.fromstring(xml_content)
                    items = root.findall('.//item')[:7]  # Fetch top 7 news items
                    
                    if not items:
                        embed = discord.Embed(
                            title="🔎 ไม่พบข่าวที่ค้นหา",
                            description="ไม่พบข่าวที่ตรงกับคำค้นหาของคุณในขณะนี้ ลองเปลี่ยนคีย์เวิร์ดใหม่นะครับ",
                            color=0xe74c3c
                        )
                        await interaction.followup.send(embed=embed)
                        return

                    # Build news description text
                    news_lines = []
                    for idx, item in enumerate(items, 1):
                        title_el = item.find("title")
                        link_el = item.find("link")
                        pub_date_el = item.find("pubDate")
                        
                        title = title_el.text if title_el is not None else "หัวข้อข่าวไม่มีชื่อ"
                        link = link_el.text if link_el is not None else ""
                        pub_date = pub_date_el.text if pub_date_el is not None else ""

                        # Parse date to show a shorter relative time or friendly string
                        # e.g., "Tue, 28 Jul 2026 13:07:15 GMT" -> "28 Jul 13:07"
                        short_date = ""
                        if pub_date:
                            try:
                                # Standard RSS format: %a, %d %b %Y %H:%M:%S %Z
                                dt = urllib.parse.parse_qsl(pub_date) # Fallback or parse string manually
                                parts = pub_date.split(" ")
                                if len(parts) >= 5:
                                    # Take day, month, time
                                    short_date = f" ({parts[1]} {parts[2]} {parts[4][:5]})"
                            except Exception:
                                pass

                        if link:
                            news_lines.append(f"{idx}. [{title}]({link}){short_date}")
                        else:
                            news_lines.append(f"{idx}. {title}{short_date}")

                    description_text = "\n\n".join(news_lines)

                    # Build beautiful embed
                    embed = discord.Embed(
                        title=title_display,
                        description=description_text,
                        color=0x1f73b7  # Google News Blue
                    )
                    avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                    embed.set_author(name="Google News • ข่าวสารล่าสุด", icon_url=avatar_url)
                    embed.set_footer(text="คลิกที่หัวข้อข่าวเพื่อเปิดอ่านข่าวตัวเต็มในเบราว์เซอร์ได้ทันที")

                    await interaction.followup.send(embed=embed)

        except Exception as e:
            print(f"Error fetching news: {e}")
            embed = discord.Embed(
                title="😅 ขออภัย ดึงข่าวไม่สำเร็จ",
                description="ตอนนี้บอทไม่สามารถดึงข้อมูลข่าวสารได้ ลองใหม่อีกครั้งในอีกสักครู่นะครับ",
                color=0xe74c3c
            )
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(NewsCog(bot))
