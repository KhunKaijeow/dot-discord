"""Song lyrics slash commands."""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import urllib.parse
from .music import get_state
from ..ui import EmbedColor, make_embed, set_embed_author

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
                    query = state.current.title
                else:
                    embed = make_embed(
                        self.bot,
                        "Lyrics",
                        title="🎵 ตอนนี้ยังไม่มีเพลงเล่นอยู่",
                        description="ส่งชื่อเพลงมาได้เลย เช่น `/lyrics query:Shape of You` เดี๋ยวผมหาให้",
                        color=EmbedColor.INFO,
                    )
                    await interaction.followup.send(embed=embed)
                    return
            except Exception:
                embed = make_embed(
                    self.bot,
                    "Lyrics",
                    title="🎵 บอกชื่อเพลงผมหน่อย",
                    description="ลองใส่ชื่อเพลง เช่น `/lyrics query:hello` แล้วผมจะไปหาเนื้อร้องให้",
                    color=EmbedColor.INFO,
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
                            embed = make_embed(
                                self.bot,
                                "Lyrics",
                                title="🔎 ยังไม่เจอเนื้อเพลงนี้",
                                description=f"ผมหา **{query_clean}** ไม่เจอ ลองเติมชื่อศิลปินแล้วค้นอีกทีนะ",
                                color=EmbedColor.WARNING,
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
                            embed = make_embed(
                                self.bot,
                                "Lyrics",
                                title="🎼 เพลงนี้อาจไม่มีเนื้อร้อง",
                                description=f"ยังไม่มีเนื้อร้องของ **{query_clean}** หรืออาจเป็นเพลงบรรเลงก็ได้นะ",
                                color=EmbedColor.WARNING,
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
                            title=f"🎼 {title}",
                            description=f"👤 **ศิลปิน:** `{artist}` | 💿 **อัลบั้ม:** `{album}`\n\n>>> {lyrics_text}",
                            color=EmbedColor.MUSIC,
                        )
                        set_embed_author(embed, self.bot, "Lyrics")
                        await interaction.followup.send(embed=embed)
                    else:
                        embed = make_embed(
                            self.bot,
                            "Lyrics",
                            title="😅 เนื้อเพลงยังมาไม่ถึง",
                            description=f"แหล่งข้อมูลตอบกลับด้วยรหัส `{response.status}` รอสักครู่แล้วลองใหม่อีกทีนะ",
                            color=EmbedColor.ERROR,
                        )
                        await interaction.followup.send(embed=embed)

        except Exception:
            embed = make_embed(
                self.bot,
                "Lyrics",
                title="😅 เนื้อเพลงยังมาไม่ถึง",
                description="แหล่งข้อมูลเงียบไปนิดนึง รอสักครู่แล้วลองใหม่อีกทีนะ",
                color=EmbedColor.ERROR,
            )
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(LyricsCog(bot))
