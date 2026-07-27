"""Song lyrics slash commands."""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import urllib.parse
from .music import get_state

class LyricsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="lyrics", description="ค้นหาเนื้อเพลงตามคำค้นหา หรือเพลงที่กำลังเล่นปัจจุบัน")
    @app_commands.describe(query="ชื่อเพลง หรือชื่อนักร้อง (ปล่อยว่างหากต้องการหาเพลงที่กำลังเล่นอยู่)")
    async def lyrics(self, interaction: discord.Interaction, query: str = None):
        await interaction.response.defer(thinking=True)

        # If no query is provided, check if a song is playing in the guild's voice channel
        if not query or query.strip() == "":
            try:
                state = get_state(self.bot, interaction.guild.id)
                if state and state.current:
                    query = state.current
                else:
                    embed = discord.Embed(
                        title="🎵 ตอนนี้ยังไม่มีเพลงเล่นอยู่",
                        description="พิมพ์ชื่อเพลงที่อยากหาเนื้อร้องมาได้เลย เช่น `/lyrics query:Shape of You`",
                        color=0xe74c3c
                    )
                    await interaction.followup.send(embed=embed)
                    return
            except Exception:
                embed = discord.Embed(
                    title="🎵 บอกชื่อเพลงผมหน่อย",
                    description="ลองใส่ชื่อเพลงที่อยากหาเนื้อร้อง เช่น `/lyrics query:hello` นะครับ",
                    color=0xe74c3c
                )
                await interaction.followup.send(embed=embed)
                return

        query_clean = query.strip()
        encoded_query = urllib.parse.quote(query_clean)
        
        # Querying LRCLIB public API (No key required, highly reliable)
        url = f"https://lrclib.net/api/search?q={encoded_query}"
        headers = {"User-Agent": "JavisDiscordBot/1.0 (https://github.com/kjss/bot-discord)"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        results = await response.json(content_type=None)
                        
                        if not results:
                            embed = discord.Embed(
                                title="🔎 ยังไม่เจอเนื้อเพลงนี้",
                                description=f"ผมหาเนื้อเพลง **{query_clean}** ไม่เจอ ลองใส่ชื่อศิลปินเพิ่มหรือเช็กชื่อเพลงอีกครั้งนะครับ",
                                color=0xe74c3c
                            )
                            await interaction.followup.send(embed=embed)
                            return
                        
                        # Find the first search result that contains plain text lyrics
                        best_match = None
                        for track in results:
                            if track.get("plainLyrics"):
                                best_match = track
                                break
                        
                        if not best_match:
                            embed = discord.Embed(
                                title="🎼 เพลงนี้อาจไม่มีเนื้อร้อง",
                                description=f"ผมหาเนื้อร้องของ **{query_clean}** ไม่เจอ เพลงนี้อาจเป็นเพลงบรรเลงหรือตอนนี้ยังไม่มีข้อมูลครับ",
                                color=0xe74c3c
                            )
                            await interaction.followup.send(embed=embed)
                            return

                        title = best_match.get("trackName", "Unknown Title")
                        artist = best_match.get("artistName", "Unknown Artist")
                        album = best_match.get("albumName", "Unknown Album")
                        lyrics_text = best_match.get("plainLyrics", "")

                        # Format and split/truncate if too long
                        max_len = 3800
                        if len(lyrics_text) > max_len:
                            lyrics_text = lyrics_text[:max_len] + "\n\n...(เนื้อเพลงมีความยาวเกินกว่าจะแสดงได้ทั้งหมด)..."

                        # Build beautiful Embed card
                        embed = discord.Embed(
                            description=f"👤 **ศิลปิน:** `{artist}` | 💿 **อัลบั้ม:** `{album}`\n\n>>> {lyrics_text}",
                            color=0x9b59b6  # Purple theme for music
                        )
                        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                        embed.set_author(name=f"เจอเนื้อเพลงแล้ว • {title}", icon_url=avatar_url)
                        embed.set_footer(text="เนื้อเพลงจาก LRCLIB", icon_url=avatar_url)
                        await interaction.followup.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title="😅 โหลดเนื้อเพลงไม่สำเร็จ",
                            description=f"แหล่งข้อมูลตอบกลับไม่สำเร็จ (รหัส {response.status}) ลองใหม่อีกครั้งในอีกสักครู่นะครับ",
                            color=0xe74c3c
                        )
                        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                        embed.set_footer(text="Javis Lyrics • เดี๋ยวลองใหม่กันนะ", icon_url=avatar_url)
                        await interaction.followup.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="😅 โหลดเนื้อเพลงไม่สำเร็จ",
                description="ตอนนี้ผมติดต่อแหล่งข้อมูลเนื้อเพลงไม่ได้ ลองใหม่อีกครั้งในอีกสักครู่นะครับ",
                color=0xe74c3c
            )
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            embed.set_footer(text="Javis Lyrics • เดี๋ยวลองใหม่กันนะ", icon_url=avatar_url)
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(LyricsCog(bot))
