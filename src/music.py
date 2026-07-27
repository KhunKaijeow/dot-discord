import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import shlex
import urllib.request
import re
from bs4 import BeautifulSoup
import yt_dlp

# yt-dlp configuration
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.webpage_url = data.get('webpage_url')
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        
        if 'entries' in data:
            # Take first item from search results
            data = data['entries'][0]

        # Extract HTTP headers from yt-dlp to bypass YouTube 403 Forbidden blocks
        http_headers = data.get('http_headers', {})
        headers_str = "".join(f"{k}: {v}\r\n" for k, v in http_headers.items())
        
        before_opts = (
            '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 '
            f'-headers {shlex.quote(headers_str)}'
        )

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, before_options=before_opts, options='-vn'), data=data)


def resolve_spotify_track(url: str) -> str:
    """Uses Spotify's public oEmbed API to resolve track titles."""
    try:
        import urllib.parse
        import requests
        
        clean_url = url.split('?')[0]
        encoded_url = urllib.parse.quote(clean_url, safe='')
        oembed_url = f"https://open.spotify.com/oembed?url={encoded_url}"
        
        headers = {
            'User-Agent': 'Spotify-Discord-Bot/1.0'
        }
        
        response = requests.get(oembed_url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            title = data.get('title')
            artist = data.get('author_name')
            if title and artist:
                return f"{title} {artist}"
            elif title:
                return title
        else:
            print(f"[Spotify Resolver] API returned status code {response.status_code}")
    except Exception as e:
        print(f"[Spotify Resolver] Error: {e}")
    return "Spotify Song"


async def resolve_track_info(query: str, loop) -> tuple:
    """Resolves any URL (Spotify, YouTube) or search query into a (title, youtube_url) tuple."""
    if "open.spotify.com/track/" in query:
        try:
            # Strip query params
            clean_url = query.split('?')[0]
            resolved = await loop.run_in_executor(None, resolve_spotify_track, clean_url)
            if resolved:
                # Turn it into a YouTube search
                return resolved, f"ytsearch:{resolved}"
        except Exception as e:
            print(f"Spotify resolve error: {e}")
        return "Spotify Song", query

    is_url = query.startswith("http://") or query.startswith("https://")
    try:
        search_query = query if is_url else f"ytsearch:{query}"
        data = await loop.run_in_executor(
            None, 
            lambda: yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}).extract_info(search_query, download=False)
        )
        if 'entries' in data:
            if not data['entries']:
                return "Unknown Song", query
            first_entry = data['entries'][0]
            title = first_entry.get('title', 'Unknown Song')
            video_id = first_entry.get('id')
            if video_id:
                return title, f"https://www.youtube.com/watch?v={video_id}"
            return title, query
        else:
            title = data.get('title', 'Unknown Song')
            return title, query
    except Exception as e:
        print(f"YouTube resolve error: {e}")
        return "Unknown Song", query


class MusicControlView(discord.ui.View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.blurple, emoji="⏸️", custom_id="music_pause")
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            await interaction.response.send_message("❌ ไม่มีเพลงที่กำลังเล่นอยู่ครับ", ephemeral=True)
            return

        voice_client.pause()
        embed = discord.Embed(description="⏸️ **หยุดเพลงชั่วคราวแล้วครับ**", color=0xe67e22)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.green, emoji="▶️", custom_id="music_resume")
    async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_paused():
            await interaction.response.send_message("❌ เพลงไม่ได้หยุดชั่วคราวอยู่ครับ", ephemeral=True)
            return

        voice_client.resume()
        embed = discord.Embed(description="▶️ **เล่นเพลงต่อเรียบร้อยครับ**", color=0x2ecc71)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️", custom_id="music_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client or (not voice_client.is_playing() and not voice_client.is_paused()):
            await interaction.response.send_message("❌ ไม่มีเพลงที่กำลังเล่นอยู่ครับ", ephemeral=True)
            return

        voice_client.stop()
        embed = discord.Embed(description="⏭️ **ข้ามเพลงเรียบร้อยครับ**", color=0xf1c40f)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", custom_id="music_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client:
            await interaction.response.send_message("❌ บอทไม่ได้อยู่ในช่องพูดคุยครับ", ephemeral=True)
            return

        state = get_state(self.bot, self.guild_id)
        state.queue.clear()
        state.current = None

        await voice_client.disconnect()
        embed = discord.Embed(description="⏹️ **ล้างคิวเพลงและออกจากห้องพูดคุยเรียบร้อยครับ**", color=0xe74c3c)
        await interaction.response.send_message(embed=embed)


class GuildPlayState:
    def __init__(self, bot, guild_id):
        self.bot = bot
        self.guild_id = guild_id
        self.queue = []
        self.current = None
        self.voice_client = None

    async def play_next_async(self, interaction):
        if not self.queue:
            self.current = None
            embed = discord.Embed(description="⏹️ **คิวเพลงหมดแล้วครับ**", color=0xe74c3c)
            await interaction.channel.send(embed=embed)
            return
        
        song = self.queue.pop(0)
        title = song['title']
        query = song['query']
        user = song['user']
        self.current = title

        loading_msg = await interaction.channel.send(f"🔄 **กำลังโหลดเพลง:** {title}")
        
        try:
            source = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)
            
            # Format duration
            duration_sec = source.data.get('duration')
            if duration_sec:
                mins, secs = divmod(duration_sec, 60)
                duration_str = f"{mins:02d}:{secs:02d}"
            else:
                duration_str = "ไม่ทราบ"

            # Create rich embed
            embed = discord.Embed(
                description=f"🎵 **[{source.title}]({source.webpage_url or query})**",
                color=0x9b59b6  # Vibrant Purple
            )
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            embed.set_author(name="กำลังเล่นเพลง • Now Playing", icon_url=avatar_url)
            if source.thumbnail:
                embed.set_thumbnail(url=source.thumbnail)
            
            embed.add_field(name="⏱️ ความยาว", value=f"`{duration_str}`", inline=True)
            embed.add_field(name="👤 ผู้ขอเพลง", value=user.mention, inline=True)
            
            embed.set_footer(text="Javis Music System", icon_url=avatar_url)

            def after_playing(error):
                if error:
                    print(f"Playback error: {error}")
                asyncio.run_coroutine_threadsafe(self.play_next_async(interaction), self.bot.loop)
            
            self.voice_client.play(source, after=after_playing)
            view = MusicControlView(self.bot, self.guild_id)
            await loading_msg.edit(content=None, embed=embed, view=view)
        except Exception as e:
            await loading_msg.edit(content=f"❌ เกิดข้อผิดพลาดในการเล่นเพลง **{title}**: {e}")
            await self.play_next_async(interaction)


# Global dictionary storing guild playback states
music_states = {}

def get_state(bot, guild_id) -> GuildPlayState:
    if guild_id not in music_states:
        music_states[guild_id] = GuildPlayState(bot, guild_id)
    return music_states[guild_id]


# Music Cog holding slash commands
class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="play", description="เล่นเพลงจากชื่อ, ลิงก์ YouTube หรือ Spotify")
    @app_commands.describe(query="ชื่อเพลง ลิงก์ YouTube หรือลิงก์ Spotify")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True)

        # Check voice state
        if not interaction.user.voice:
            await interaction.followup.send("❌ คุณต้องเชื่อมต่อกับช่องพูดคุย (Voice Channel) ก่อนครับ")
            return

        channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        if voice_client is None:
            voice_client = await channel.connect()
        elif voice_client.channel != channel:
            await voice_client.move_to(channel)

        state = get_state(self.bot, interaction.guild.id)
        state.voice_client = voice_client

        # Resolve track metadata
        title, resolved_query = await resolve_track_info(query, self.bot.loop)

        # Add to queue with requester info
        state.queue.append({
            'title': title, 
            'query': resolved_query,
            'user': interaction.user
        })

        if not voice_client.is_playing() and not voice_client.is_paused():
            # If not currently playing, start playing
            embed = discord.Embed(
                description=f"✅ **เพิ่มเข้าคิวและเริ่มเล่นสำเร็จ**\n\n🎵 **{title}**",
                color=0x2ecc71  # Mint Green
            )
            embed.add_field(name="👤 ผู้ขอเพลง", value=interaction.user.mention, inline=True)
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            embed.set_footer(text="Javis Music System", icon_url=avatar_url)
            await interaction.followup.send(embed=embed)
            await state.play_next_async(interaction)
        else:
            # If already playing, just notify queue addition
            embed = discord.Embed(
                description=f"📥 **เพิ่มเข้าคิวเพลงเรียบร้อยแล้ว**\n\n🎵 **{title}**",
                color=0x3498db  # Material Blue
            )
            embed.add_field(name="👤 ผู้ขอเพลง", value=interaction.user.mention, inline=True)
            embed.add_field(name="📋 ลำดับในคิว", value=f"`#{len(state.queue)}`", inline=True)
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            embed.set_footer(text="Javis Music System", icon_url=avatar_url)
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่")
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            embed = discord.Embed(description="❌ **ไม่มีเพลงที่กำลังเล่นอยู่ครับ**", color=0xe74c3c)
            await interaction.response.send_message(embed=embed)
            return

        voice_client.stop()
        embed = discord.Embed(description="⏭️ **ข้ามเพลงเรียบร้อยครับ**", color=0xf1c40f)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pause", description="หยุดเพลงชั่วคราว")
    async def pause(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            embed = discord.Embed(description="❌ **ไม่มีเพลงที่กำลังเล่นอยู่ครับ**", color=0xe74c3c)
            await interaction.response.send_message(embed=embed)
            return

        voice_client.pause()
        embed = discord.Embed(description="⏸️ **หยุดเพลงชั่วคราวแล้วครับ**", color=0xe67e22)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="resume", description="เล่นเพลงที่หยุดชั่วคราวต่อ")
    async def resume(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_paused():
            embed = discord.Embed(description="❌ **เพลงไม่ได้หยุดชั่วคราวอยู่ครับ**", color=0xe74c3c)
            await interaction.response.send_message(embed=embed)
            return

        voice_client.resume()
        embed = discord.Embed(description="▶️ **เล่นเพลงต่อเรียบร้อยครับ**", color=0x2ecc71)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="queue", description="แสดงรายการคิวเพลงปัจจุบัน")
    async def queue(self, interaction: discord.Interaction):
        state = get_state(self.bot, interaction.guild.id)
        if not state.current and not state.queue:
            embed = discord.Embed(description="📭 **ไม่มีเพลงในคิวปัจจุบันครับ**", color=0x95a5a6)
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(
            color=0x3498db  # Material Blue
        )
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        embed.set_author(name="รายการคิวเพลง • Queue List", icon_url=avatar_url)
        embed.add_field(name="🎶 เพลงที่กำลังเล่น", value=f"📡 **{state.current}**" if state.current else "ไม่มี", inline=False)
        
        if not state.queue:
            queue_list = "*ไม่มีเพลงในคิวถัดไป*"
        else:
            queue_list = ""
            for idx, song in enumerate(state.queue[:10], start=1):
                queue_list += f"`{idx:02d}` **{song['title']}** | ขอโดย: {song['user'].mention}\n"
            if len(state.queue) > 10:
                queue_list += f"\n*และยังมีอีก {len(state.queue) - 10} เพลงในคิวคอยอยู่...*"

        embed.add_field(name="📋 คิวเพลงถัดไป (10 อันดับแรก)", value=queue_list, inline=False)
        embed.set_footer(text="Javis Music System", icon_url=avatar_url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stop", description="หยุดเพลง ล้างคิว และออกจากห้องพูดคุย")
    async def stop(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client:
            embed = discord.Embed(description="❌ **บอทไม่ได้อยู่ในช่องพูดคุยครับ**", color=0xe74c3c)
            await interaction.response.send_message(embed=embed)
            return

        # Clear queue
        state = get_state(self.bot, interaction.guild.id)
        state.queue.clear()
        state.current = None

        await voice_client.disconnect()
        embed = discord.Embed(description="⏹️ **ล้างคิวเพลงและออกจากห้องพูดคุยเรียบร้อยครับ**", color=0xe74c3c)
        await interaction.response.send_message(embed=embed)


def load_opus_lib():
    """Manually search and load libopus (essential for voice on macOS/Apple Silicon)."""
    if not discord.opus.is_loaded():
        paths = [
            'libopus.so.0',
            'libopus.so',
            'libopus.dylib',
            '/opt/homebrew/lib/libopus.dylib',
            '/usr/local/lib/libopus.dylib',
            '/usr/lib/x86_64-linux-gnu/libopus.so.0',
        ]
        for path in paths:
            try:
                discord.opus.load_opus(path)
                print(f"[Opus] Successfully loaded libopus from: {path}")
                return
            except Exception:
                continue
        print("[Opus WARNING] Could not find or load libopus. Voice playback might fail.")

# Setup function to register cog
async def setup(bot):
    load_opus_lib()
    await bot.add_cog(MusicCog(bot))
