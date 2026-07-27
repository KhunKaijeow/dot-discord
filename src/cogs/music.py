"""Music playback slash commands and per-guild queue state."""

import asyncio
import logging
import shlex
import shutil
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp


logger = logging.getLogger(__name__)


async def defer_interaction(interaction: discord.Interaction) -> bool:
    """Acknowledge an interaction and quietly reject an expired token."""
    try:
        await interaction.response.defer(thinking=True)
    except discord.NotFound as error:
        if error.code != 10062:
            raise

        age_seconds = (
            discord.utils.utcnow() - interaction.created_at
        ).total_seconds()
        logger.warning(
            "Ignoring expired interaction %s (age %.2fs); "
            "Discord no longer accepts its response token",
            interaction.id,
            age_seconds,
        )
        return False
    return True


def _javascript_runtimes() -> dict[str, dict[str, str]]:
    """Enable a supported runtime so yt-dlp can solve YouTube JS challenges."""
    runtime_commands = (
        ("deno", "deno"),
        ("node", "node"),
        ("quickjs", "qjs"),
    )
    for runtime_name, command in runtime_commands:
        if runtime_path := shutil.which(command):
            return {runtime_name: {"path": runtime_path}}
    return {}


# yt-dlp configuration
ytdl_format_options = {
    "format": "bestaudio[protocol^=http]/bestaudio/best",
    "noplaylist": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
    "socket_timeout": 20,
    "retries": 3,
    "extractor_retries": 3,
    "fragment_retries": 3,
    "js_runtimes": _javascript_runtimes(),
}


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
        loop = loop or asyncio.get_running_loop()

        def extract() -> tuple[dict[str, Any], str]:
            # YoutubeDL instances are not shared because multiple guilds may
            # resolve songs concurrently.
            with yt_dlp.YoutubeDL(ytdl_format_options) as ytdl:
                extracted = ytdl.extract_info(url, download=not stream)
                if not extracted:
                    raise ValueError("yt-dlp returned no media information")

                if "entries" in extracted:
                    extracted = next(
                        (entry for entry in extracted["entries"] if entry),
                        None,
                    )
                    if not extracted:
                        raise ValueError("No YouTube search results found")

                filename = (
                    extracted["url"]
                    if stream
                    else ytdl.prepare_filename(extracted)
                )
                return extracted, filename

        data, filename = await loop.run_in_executor(None, extract)

        # Extract HTTP headers from yt-dlp to bypass YouTube 403 Forbidden blocks
        http_headers = data.get("http_headers", {})
        headers_str = "".join(f"{k}: {v}\r\n" for k, v in http_headers.items())
        before_opts = (
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            f"-headers {shlex.quote(headers_str)}"
        )

        audio = discord.FFmpegPCMAudio(
            filename,
            before_options=before_opts,
            options="-vn",
        )
        return cls(audio, data=data)


def resolve_spotify_track(url: str) -> str:
    """Uses Spotify's public oEmbed API and embed page scraping fallback to resolve track titles."""
    try:
        import urllib.parse
        import requests
        import re
        import json
        
        # Follow redirects for spotify.link URLs
        if "spotify.link" in url:
            response = requests.head(url, allow_redirects=True, timeout=5)
            url = response.url

        clean_url = url.split('?')[0]
        track_id = clean_url.split('/track/')[-1]
        encoded_url = urllib.parse.quote(clean_url, safe='')
        
        # 1. Try Spotify's oEmbed API
        try:
            oembed_url = f"https://open.spotify.com/oembed?url={encoded_url}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(oembed_url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                title = data.get('title')
                artist = data.get('author_name')
                if title and artist:
                    return f"{title} {artist}"
                elif title:
                    return title
            else:
                logger.warning(
                    "[Spotify Resolver] oEmbed API status %d for %s",
                    response.status_code,
                    clean_url
                )
        except Exception as oembed_err:
            logger.debug("[Spotify Resolver] oEmbed API error: %s", oembed_err)

        # 2. Try Embed Page Scraping Fallback
        try:
            embed_url = f"https://open.spotify.com/embed/track/{track_id}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(embed_url, headers=headers, timeout=5)
            if response.status_code == 200:
                match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', response.text)
                if match:
                    data = json.loads(match.group(1))
                    entity = data.get('props', {}).get('pageProps', {}).get('state', {}).get('data', {}).get('entity', {})
                    title = entity.get('title') or entity.get('name')
                    artists = entity.get('artists', [])
                    artist_names = ", ".join([a['name'] for a in artists if 'name' in a])
                    if title and artist_names:
                        return f"{title} {artist_names}"
                    elif title:
                        return title
        except Exception as scrape_err:
            logger.debug("[Spotify Resolver] Scraping fallback error: %s", scrape_err)
            
    except Exception as e:
        logger.exception("[Spotify Resolver] General error: %s", e)
    return "Spotify Song"


async def resolve_track_info(query: str, loop) -> tuple:
    """Resolves any URL (Spotify, YouTube) or search query into a (title, youtube_url) tuple."""
    if "open.spotify.com/track/" in query or "spotify.link" in query:
        try:
            resolved = await loop.run_in_executor(None, resolve_spotify_track, query)
            if resolved and resolved != "Spotify Song":
                # Turn it into a YouTube search
                return resolved, f"ytsearch:{resolved}"
        except Exception as e:
            logger.exception("Spotify resolve error: %s", e)
        return "Spotify Song", query

    is_url = query.startswith("http://") or query.startswith("https://")
    try:
        search_query = query if is_url else f"ytsearch1:{query}"

        def extract_flat() -> dict[str, Any]:
            options = {
                **ytdl_format_options,
                "extract_flat": "in_playlist",
            }
            with yt_dlp.YoutubeDL(options) as ytdl:
                return ytdl.extract_info(search_query, download=False)

        data = await loop.run_in_executor(
            None,
            extract_flat,
        )
        if not data:
            return "Unknown Song", query
        if "entries" in data:
            entries = [entry for entry in data["entries"] if entry]
            if not entries:
                return "Unknown Song", query
            first_entry = entries[0]
            title = first_entry.get("title", "Unknown Song")
            video_id = first_entry.get("id")
            if video_id:
                return title, f"https://www.youtube.com/watch?v={video_id}"
            return title, query
        else:
            title = data.get("title", "Unknown Song")
            return title, query
    except Exception as e:
        logger.exception("YouTube resolve failed: %s", e)
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
            await interaction.response.send_message("🎵 ตอนนี้ยังไม่มีเพลงให้พักนะครับ", ephemeral=True)
            return

        voice_client.pause()
        embed = discord.Embed(description="⏸️ **พักเพลงให้แล้วนะครับ**", color=0xe67e22)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.green, emoji="▶️", custom_id="music_resume")
    async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_paused():
            await interaction.response.send_message("▶️ เพลงไม่ได้พักอยู่นะ ตอนนี้กำลังเล่นตามปกติครับ", ephemeral=True)
            return

        voice_client.resume()
        embed = discord.Embed(description="▶️ **เปิดเพลงต่อให้แล้วนะ ฟังกันต่อเลย!**", color=0x2ecc71)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️", custom_id="music_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client or (not voice_client.is_playing() and not voice_client.is_paused()):
            await interaction.response.send_message("🎵 ตอนนี้ยังไม่มีเพลงให้ข้ามนะครับ", ephemeral=True)
            return

        voice_client.stop()
        embed = discord.Embed(description="⏭️ **ข้ามให้แล้ว ไปเพลงถัดไปกันเลย!**", color=0xf1c40f)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", custom_id="music_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if not voice_client:
            await interaction.response.send_message("🎧 ตอนนี้ผมยังไม่ได้อยู่ในห้องเสียงนะครับ", ephemeral=True)
            return

        state = get_state(self.bot, self.guild_id)
        state.voice_client = voice_client
        await state.stop_and_disconnect()
        embed = discord.Embed(description="👋 **หยุดเพลง ล้างคิว และออกจากห้องให้แล้วนะครับ**", color=0xe74c3c)
        await interaction.response.send_message(embed=embed)


class GuildPlayState:
    def __init__(self, bot, guild_id):
        self.bot = bot
        self.guild_id = guild_id
        self.queue = []
        self.current = None
        self.voice_client = None
        self.stop_requested = False
        self.start_lock = asyncio.Lock()

    async def play_next_async(self, interaction):
        if self.stop_requested:
            return

        if not self.queue:
            self.current = None
            voice_client = self.voice_client
            try:
                if voice_client and voice_client.is_connected():
                    await voice_client.disconnect()
            finally:
                self.voice_client = None
            embed = discord.Embed(
                description=(
                    "📭 **เพลงในคิวหมดแล้ว ผมออกจากห้องเสียงให้แล้วนะครับ**"
                ),
                color=0xE74C3C,
            )
            await interaction.channel.send(embed=embed)
            return
        
        song = self.queue.pop(0)
        title = song['title']
        query = song['query']
        user = song['user']
        self.current = title

        loading_msg = await interaction.channel.send(f"🔄 **รอสักครู่นะ กำลังเตรียมเพลง:** {title}")
        
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
            embed.set_author(name="เปิดให้แล้ว • Now Playing", icon_url=avatar_url)
            if source.thumbnail:
                embed.set_thumbnail(url=source.thumbnail)
            
            embed.add_field(name="⏱️ ความยาว", value=f"`{duration_str}`", inline=True)
            embed.add_field(name="👤 ผู้ขอเพลง", value=user.mention, inline=True)
            

            def after_playing(error):
                if error:
                    logger.error("Playback error in guild %s: %s", self.guild_id, error)
                future = asyncio.run_coroutine_threadsafe(
                    self.play_next_async(interaction),
                    self.bot.loop,
                )
                future.add_done_callback(self._log_playback_callback_error)
            
            self.voice_client.play(source, after=after_playing)
            view = MusicControlView(self.bot, self.guild_id)
            await loading_msg.edit(content=None, embed=embed, view=view)
        except Exception as e:
            logger.exception(
                "Unable to play %r in guild %s: %s",
                query,
                self.guild_id,
                e,
            )
            import traceback
            tb = traceback.format_exc()
            if len(tb) > 1000:
                tb = tb[:1000] + "\n..."
            try:
                await interaction.channel.send(f"❌ **เกิดข้อผิดพลาดในการโหลดเพลง:**\n```py\n{tb}\n```")
            except Exception:
                pass
            await loading_msg.edit(content=f"😅 เล่นเพลง **{title}** ไม่สำเร็จ ลองเลือกเพลงอื่นหรือสั่งใหม่อีกครั้งนะครับ")
            await self.play_next_async(interaction)

    @staticmethod
    def _log_playback_callback_error(future):
        try:
            future.result()
        except Exception:
            logger.exception("Could not advance the music queue")

    async def stop_and_disconnect(self):
        self.stop_requested = True
        self.queue.clear()
        self.current = None
        voice_client = self.voice_client
        self.voice_client = None
        try:
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()
        finally:
            self.voice_client = None


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
        if not await defer_interaction(interaction):
            return

        # Check voice state
        if not interaction.user.voice:
            await interaction.followup.send("🎧 เข้าห้องเสียงก่อนนะครับ แล้วเรียกผมไปเปิดเพลงให้ได้เลย!")
            return

        channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        if voice_client is None:
            voice_client = await channel.connect()
        elif voice_client.channel != channel:
            await voice_client.move_to(channel)

        state = get_state(self.bot, interaction.guild.id)
        state.voice_client = voice_client
        state.stop_requested = False

        # Resolve track metadata
        title, resolved_query = await resolve_track_info(query, self.bot.loop)

        # Add to queue with requester info
        state.queue.append({
            'title': title, 
            'query': resolved_query,
            'user': interaction.user
        })

        async with state.start_lock:
            if not voice_client.is_playing() and not voice_client.is_paused():
                # If not currently playing, start playing
                embed = discord.Embed(
                    description=f"🎉 **เพิ่มให้แล้ว เพลงกำลังเริ่มเล่นนะ!**\n\n🎵 **{title}**",
                    color=0x2ecc71  # Mint Green
                )
                embed.add_field(name="👤 ผู้ขอเพลง", value=interaction.user.mention, inline=True)
                await interaction.followup.send(embed=embed)
                await state.play_next_async(interaction)
            else:
                # If already playing, just notify queue addition
                embed = discord.Embed(
                    description=f"📥 **เพิ่มเพลงนี้เข้าคิวให้แล้วนะ**\n\n🎵 **{title}**",
                    color=0x3498db  # Material Blue
                )
                embed.add_field(name="👤 ผู้ขอเพลง", value=interaction.user.mention, inline=True)
                embed.add_field(name="📋 ลำดับในคิว", value=f"`#{len(state.queue)}`", inline=True)
                await interaction.followup.send(embed=embed)

    @app_commands.command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่")
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            embed = discord.Embed(description="🎵 **ตอนนี้ยังไม่มีเพลงให้ข้ามนะครับ**", color=0xe74c3c)
            await interaction.response.send_message(embed=embed)
            return

        voice_client.stop()
        embed = discord.Embed(description="⏭️ **ข้ามให้แล้ว ไปเพลงถัดไปกันเลย!**", color=0xf1c40f)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pause", description="หยุดเพลงชั่วคราว")
    async def pause(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            embed = discord.Embed(description="🎵 **ตอนนี้ยังไม่มีเพลงให้พักนะครับ**", color=0xe74c3c)
            await interaction.response.send_message(embed=embed)
            return

        voice_client.pause()
        embed = discord.Embed(description="⏸️ **พักเพลงให้แล้วนะครับ**", color=0xe67e22)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="resume", description="เล่นเพลงที่หยุดชั่วคราวต่อ")
    async def resume(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_paused():
            embed = discord.Embed(description="▶️ **เพลงไม่ได้พักอยู่นะ ตอนนี้กำลังเล่นตามปกติครับ**", color=0xe74c3c)
            await interaction.response.send_message(embed=embed)
            return

        voice_client.resume()
        embed = discord.Embed(description="▶️ **เปิดเพลงต่อให้แล้วนะ ฟังกันต่อเลย!**", color=0x2ecc71)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="queue", description="แสดงรายการคิวเพลงปัจจุบัน")
    async def queue(self, interaction: discord.Interaction):
        state = get_state(self.bot, interaction.guild.id)
        if not state.current and not state.queue:
            embed = discord.Embed(description="📭 **คิวยังว่างอยู่ ขอเพลงแรกมาได้เลยครับ!**", color=0x95a5a6)
            await interaction.response.send_message(embed=embed)
            return

        embed = discord.Embed(
            color=0x3498db  # Material Blue
        )
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        embed.set_author(name="มาดูคิวเพลงกัน • Queue", icon_url=avatar_url)
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
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stop", description="หยุดเพลง ล้างคิว และออกจากห้องพูดคุย")
    async def stop(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client:
            embed = discord.Embed(description="🎧 **ตอนนี้ผมยังไม่ได้อยู่ในห้องเสียงนะครับ**", color=0xe74c3c)
            await interaction.response.send_message(embed=embed)
            return

        # Clear queue
        state = get_state(self.bot, interaction.guild.id)
        state.voice_client = voice_client
        await state.stop_and_disconnect()
        embed = discord.Embed(description="👋 **หยุดเพลง ล้างคิว และออกจากห้องให้แล้วนะครับ**", color=0xe74c3c)
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
    if not ytdl_format_options["js_runtimes"]:
        logger.warning(
            "No supported JavaScript runtime found; install Deno 2.3+ "
            "or Node.js 22+ for reliable YouTube playback"
        )
    load_opus_lib()
    await bot.add_cog(MusicCog(bot))
