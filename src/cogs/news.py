"""News lookup and summarization slash commands."""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import urllib.parse
import xml.etree.ElementTree as ET
import asyncio

class NewsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="news", description="ดึงหัวข้อข่าวเด่นล่าสุดแล้วใช้ Gemini AI สรุปข่าวให้อ่านง่าย")
    @app_commands.describe(keyword="หัวข้อข่าวที่สนใจ เช่น คริปโต, เทคโนโลยี (ปล่อยว่างหากต้องการข่าวเด่นทั่วไป)")
    async def news(self, interaction: discord.Interaction, keyword: str = None):
        await interaction.response.defer(thinking=True)

        # Build Google News RSS Feed URL (Thai localized)
        if keyword and keyword.strip() != "":
            keyword_clean = keyword.strip()
            encoded_kw = urllib.parse.quote(keyword_clean)
            url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=th&gl=TH&ceid=TH:th"
            title_display = f"สรุปข่าวเด่นล่าสุด: {keyword_clean}"
        else:
            url = "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th"
            title_display = "สรุปข่าวเด่นทั่วไปประจำวัน"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise Exception(f"RSS API returned status {response.status}")
                    
                    xml_content = await response.text()
                    
                    # Parse XML using standard library ElementTree
                    root = ET.fromstring(xml_content)
                    items = root.findall('.//item')[:5]
                    
                    if not items:
                        embed = discord.Embed(
                            title="🔎 ยังไม่เจอข่าวที่ตรงกัน",
                            description="ตอนนี้ยังไม่เจอข่าวเด่นในหัวข้อนี้ ลองเปลี่ยนคำค้นอีกนิดแล้วให้ผมหาใหม่นะครับ",
                            color=0xe74c3c
                        )
                        await interaction.followup.send(embed=embed)
                        return

                    # Format list of news for Gemini AI
                    news_list = []
                    for idx, item in enumerate(items, 1):
                        title_el = item.find("title")
                        link_el = item.find("link")
                        title = title_el.text if title_el is not None else "Untitled"
                        link = link_el.text if link_el is not None else ""
                        news_list.append({"index": idx, "title": title, "link": link})

                    # Prompt Gemini to synthesize summaries
                    prompt = (
                        "คุณคือ Javis ผู้ช่วยอัจฉริยะที่จะมารายงานสรุปข่าวเด่นให้กระชับและน่าอ่านที่สุดบน Discord "
                        "โปรดสรุปข้อมูลข่าวเด่นด้านล่างนี้เป็นภาษาไทยให้อ่านง่าย รักษารายละเอียดลิงก์ข่าวแต่ละเรื่อง "
                        "แบ่งประเด็นย่อสรุปข่าวละประมาณ 1-2 บรรทัด (ห้ามยาวเกินไป) โดยเขียนลิงก์แบบ Markdown เช่น [อ่านข่าวเพิ่มเติม](ลิงก์) "
                        "นี่คือหัวข้อข่าวทั้งหมด:\n\n"
                    )
                    
                    for item in news_list:
                        prompt += f"{item['index']}. หัวข้อข่าว: {item['title']} - ลิงก์ข่าว: {item['link']}\n"

                    # Fetch response asynchronously using a threadpool to prevent blocking the gateway loop
                    summary = await asyncio.to_thread(
                        self.bot.gemini_service.generate_complex_response, 
                        prompt
                    )

                    # Truncate summary if too long
                    if len(summary) > 4000:
                        summary = summary[:3900] + "..."

                    # Build beautiful embed
                    embed = discord.Embed(
                            description=f"📰 **ข่าวที่คุณอยากรู้:** `{keyword_clean if (keyword and keyword.strip() != '') else 'ข่าวเด่นทั่วไปประจําวัน'}`\n\n{summary}",
                        color=0x1f73b7  # Google News Blue
                    )
                    avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                    embed.set_author(name="สรุปข่าวมาให้แล้ว • Daily News", icon_url=avatar_url)
                    embed.set_footer(text="สรุปให้อ่านง่ายโดย Javis AI • Gemini", icon_url=avatar_url)

                    await interaction.followup.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="😅 ขออภัย สรุปข่าวไม่สำเร็จ",
                description="ตอนนี้ผมดึงหรือสรุปข่าวให้ไม่ได้ ลองใหม่อีกครั้งในอีกสักครู่นะครับ",
                color=0xe74c3c
            )
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            embed.set_footer(text="Javis News • เดี๋ยวลองใหม่กันนะ", icon_url=avatar_url)
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(NewsCog(bot))
