"""Discord music commands with YouTube playback and Spotify link resolving."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import logging
import shlex
import shutil
from typing import Any
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp


logger = logging.getLogger(__name__)

FFMPEG_EXECUTABLE = shutil.which("ffmpeg")
SPOTIFY_OEMBED_URL = "https://open.spotify.com/oembed"
SPOTIFY_HOSTS = {"open.spotify.com", "spotify.link"}
YOUTUBE_HOSTS = {"youtube.com", "music.youtube.com", "youtu.be"}
YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"


class MusicError(Exception):
    """Base error shown to users when a track cannot be prepared."""


class UnsupportedSpotifyUrl(MusicError):
    """Raised for Spotify URLs other than individual tracks."""


@dataclass(slots=True)
class Track:
    title: str
    youtube_url: str
    requester: discord.abc.User
    requested_via: str


def _javascript_runtimes() -> dict[str, dict[str, str]]:
    runtime_commands = (
        ("deno", "deno"),
        ("node", "node"),
        ("quickjs", "qjs"),
    )
    for runtime_name, command in runtime_commands:
        if runtime_path := shutil.which(command):
            return {runtime_name: {"path": runtime_path}}
    return {}


YTDL_OPTIONS = {
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


async def defer_interaction(interaction: discord.Interaction) -> bool:
    """Acknowledge a command and ignore a token that already expired."""
    try:
        await interaction.response.defer(thinking=True)
    except discord.NotFound as error:
        if error.code != 10062:
            raise
        age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
        logger.warning(
            "Ignoring expired interaction %s (age %.2fs)",
            interaction.id,
            age,
        )
        return False
    return True


def _first_entry(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        raise MusicError("ไม่พบข้อมูลเพลงจาก YouTube")
    if "entries" not in data:
        return data

    entry = next((item for item in data["entries"] if item), None)
    if not entry:
        raise MusicError("ไม่พบเพลงที่ตรงกับคำค้นหา")
    return entry


def _extract_youtube_info(query: str, *, flat: bool) -> dict[str, Any]:
    options = dict(YTDL_OPTIONS)
    if flat:
        options["extract_flat"] = "in_playlist"

    with yt_dlp.YoutubeDL(options) as ytdl:
        return _first_entry(ytdl.extract_info(query, download=False))


async def _spotify_search_text(url: str) -> str:
    timeout = aiohttp.ClientTimeout(total=15)
    headers = {"User-Agent": "JavisDiscordBot/1.0"}

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            if urlparse(url).netloc.lower() == "spotify.link":
                async with session.get(url, allow_redirects=True) as response:
                    response.raise_for_status()
                    url = str(response.url)

            parsed = urlparse(url)
            path_parts = [part for part in parsed.path.split("/") if part]
            if parsed.netloc.lower() != "open.spotify.com":
                raise UnsupportedSpotifyUrl("ลิงก์ Spotify ไม่ถูกต้อง")
            if len(path_parts) < 2 or path_parts[-2] != "track":
                raise UnsupportedSpotifyUrl(
                    "ตอนนี้รองรับลิงก์ Spotify แบบเพลงเดี่ยวเท่านั้น"
                )

            clean_url = f"https://open.spotify.com/track/{path_parts[-1]}"
            async with session.get(
                SPOTIFY_OEMBED_URL,
                params={"url": clean_url},
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
    except UnsupportedSpotifyUrl:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
        raise MusicError("อ่านข้อมูลเพลงจาก Spotify ไม่สำเร็จ") from error

    title = str(payload.get("title") or "").strip()
    artist = str(payload.get("author_name") or "").strip()
    if not title:
        raise MusicError("Spotify ไม่ส่งชื่อเพลงกลับมา")

    search_text = " ".join(part for part in (title, artist) if part)
    return f"{search_text} official audio"


async def resolve_track(query: str, requester: discord.abc.User) -> Track:
    """Resolve text, YouTube URL, or Spotify track URL to one YouTube video."""
    query = query.strip()
    if not query:
        raise MusicError("กรุณาใส่ชื่อเพลงหรือลิงก์")

    parsed = urlparse(query)
    host = parsed.hostname.lower().removeprefix("www.") if parsed.hostname else ""
    requested_via = "YouTube"

    if host in SPOTIFY_HOSTS:
        search_text = await _spotify_search_text(query)
        youtube_query = f"ytsearch1:{search_text}"
        requested_via = "Spotify → YouTube"
    elif parsed.scheme in {"http", "https"}:
        if host not in YOUTUBE_HOSTS:
            raise MusicError("รองรับเฉพาะลิงก์ YouTube และ Spotify เท่านั้น")
        youtube_query = query
    else:
        youtube_query = f"ytsearch1:{query}"

    try:
        data = await asyncio.to_thread(
            _extract_youtube_info,
            youtube_query,
            flat=True,
        )
    except MusicError:
        raise
    except Exception as error:
        logger.exception("YouTube track resolution failed for %r", query)
        raise MusicError("ค้นหาเพลงบน YouTube ไม่สำเร็จ") from error

    video_id = data.get("id")
    webpage_url = data.get("webpage_url") or data.get("url")
    if video_id and data.get("extractor_key") in {"Youtube", "YoutubeTab"}:
        webpage_url = YOUTUBE_WATCH_URL.format(video_id=video_id)
    elif video_id and youtube_query.startswith("ytsearch"):
        webpage_url = YOUTUBE_WATCH_URL.format(video_id=video_id)

    if not webpage_url:
        raise MusicError("YouTube ไม่ส่งลิงก์สำหรับเพลงนี้กลับมา")

    return Track(
        title=data.get("title") or "Unknown Song",
        youtube_url=webpage_url,
        requester=requester,
        requested_via=requested_via,
    )


class YouTubeAudioSource(discord.PCMVolumeTransformer):
    def __init__(self, source: discord.AudioSource, data: dict[str, Any]):
        super().__init__(source, volume=0.5)
        self.data = data
        self.title = data.get("title") or "Unknown Song"
        self.webpage_url = data.get("webpage_url")
        self.thumbnail = data.get("thumbnail")

    @classmethod
    async def create(cls, youtube_url: str) -> YouTubeAudioSource:
        if not FFMPEG_EXECUTABLE:
            raise MusicError("เครื่องที่รันบอทยังไม่ได้ติดตั้ง FFmpeg")

        try:
            data = await asyncio.to_thread(
                _extract_youtube_info,
                youtube_url,
                flat=False,
            )
        except MusicError:
            raise
        except Exception as error:
            logger.exception("YouTube audio extraction failed for %s", youtube_url)
            raise MusicError("ดึง audio stream จาก YouTube ไม่สำเร็จ") from error

        stream_url = data.get("url")
        if not stream_url:
            raise MusicError("YouTube ไม่ส่ง audio stream กลับมา")

        headers = data.get("http_headers") or {}
        header_text = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
        before_options = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        if header_text:
            before_options += f" -headers {shlex.quote(header_text)}"
        audio = discord.FFmpegPCMAudio(
            stream_url,
            executable=FFMPEG_EXECUTABLE,
            before_options=before_options,
            options="-vn",
        )
        return cls(audio, data)


class GuildMusicState:
    def __init__(self, bot: commands.Bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.voice_client: discord.VoiceClient | None = None
        self.text_channel: discord.abc.Messageable | None = None
        self.stop_requested = False
        self.advance_lock = asyncio.Lock()

    async def enqueue(
        self,
        track: Track,
        voice_client: discord.VoiceClient,
        text_channel: discord.abc.Messageable,
    ) -> int:
        self.voice_client = voice_client
        self.text_channel = text_channel
        self.stop_requested = False
        self.queue.append(track)
        position = len(self.queue)

        if (
            self.current is None
            and not voice_client.is_playing()
            and not voice_client.is_paused()
        ):
            await self.play_next()
            return 0
        return position

    async def play_next(self) -> None:
        async with self.advance_lock:
            if self.stop_requested:
                return

            while self.queue:
                track = self.queue.popleft()
                self.current = track
                if await self._start_track(track):
                    return
                self.current = None

            await self._disconnect_when_idle()

    async def _start_track(self, track: Track) -> bool:
        channel = self.text_channel
        voice_client = self.voice_client
        if channel is None or voice_client is None or not voice_client.is_connected():
            return False

        loading_message = await channel.send(
            f"🔄 **กำลังเตรียมเพลง:** {track.title}"
        )
        try:
            source = await YouTubeAudioSource.create(track.youtube_url)
            voice_client.play(source, after=self._after_playing)
        except MusicError as error:
            logger.warning(
                "Could not play %s in guild %s: %s",
                track.youtube_url,
                self.guild_id,
                error,
            )
            await loading_message.edit(content=f"😅 {error}")
            return False
        except Exception:
            logger.exception(
                "Unexpected playback error in guild %s",
                self.guild_id,
            )
            await loading_message.edit(
                content="😅 เตรียมเพลงไม่สำเร็จ ลองเลือกเพลงอื่นอีกครั้งนะครับ"
            )
            return False

        duration = source.data.get("duration")
        duration_text = (
            f"{duration // 60:02d}:{duration % 60:02d}"
            if isinstance(duration, int)
            else "ไม่ทราบ"
        )
        embed = discord.Embed(
            description=f"🎵 **[{source.title}]({track.youtube_url})**",
            color=0x9B59B6,
        )
        avatar = self.bot.user.display_avatar.url if self.bot.user else None
        embed.set_author(name="กำลังเล่น • Now Playing", icon_url=avatar)
        if source.thumbnail:
            embed.set_thumbnail(url=source.thumbnail)
        embed.add_field(name="⏱️ ความยาว", value=f"`{duration_text}`")
        embed.add_field(name="👤 ผู้ขอเพลง", value=track.requester.mention)
        embed.add_field(name="🔎 แหล่งคำขอ", value=track.requested_via)
        await loading_message.edit(
            content=None,
            embed=embed,
            view=MusicControlView(self.bot, self.guild_id),
        )
        return True

    def _after_playing(self, error: Exception | None) -> None:
        if error:
            logger.error("Playback error in guild %s: %s", self.guild_id, error)
        future = asyncio.run_coroutine_threadsafe(
            self._continue_after_track(),
            self.bot.loop,
        )
        future.add_done_callback(self._log_callback_error)

    async def _continue_after_track(self) -> None:
        self.current = None
        await self.play_next()

    @staticmethod
    def _log_callback_error(future) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("Could not advance the music queue")

    async def _disconnect_when_idle(self) -> None:
        self.current = None
        voice_client = self.voice_client
        self.voice_client = None
        try:
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()
        finally:
            self.voice_client = None

        if self.text_channel:
            await self.text_channel.send(
                embed=discord.Embed(
                    description=(
                        "📭 **เพลงในคิวหมดแล้ว ผมออกจากห้องเสียงให้แล้วนะครับ**"
                    ),
                    color=0x95A5A6,
                )
            )

    async def stop(self) -> None:
        self.stop_requested = True
        self.queue.clear()
        self.current = None
        voice_client = self.voice_client
        self.voice_client = None
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()


music_states: dict[int, GuildMusicState] = {}


def get_state(bot: commands.Bot, guild_id: int) -> GuildMusicState:
    if guild_id not in music_states:
        music_states[guild_id] = GuildMusicState(bot, guild_id)
    return music_states[guild_id]


class MusicControlView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild_id = guild_id

    @discord.ui.button(label="Pause", emoji="⏸️")
    async def pause(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or not voice.is_playing():
            await interaction.response.send_message(
                "🎵 ตอนนี้ยังไม่มีเพลงให้พักครับ",
                ephemeral=True,
            )
            return
        voice.pause()
        await interaction.response.send_message("⏸️ พักเพลงให้แล้วครับ")

    @discord.ui.button(
        label="Resume",
        emoji="▶️",
        style=discord.ButtonStyle.success,
    )
    async def resume(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or not voice.is_paused():
            await interaction.response.send_message(
                "▶️ เพลงไม่ได้พักอยู่ครับ",
                ephemeral=True,
            )
            return
        voice.resume()
        await interaction.response.send_message("▶️ เล่นเพลงต่อให้แล้วครับ")

    @discord.ui.button(label="Skip", emoji="⏭️")
    async def skip(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or (not voice.is_playing() and not voice.is_paused()):
            await interaction.response.send_message(
                "🎵 ตอนนี้ยังไม่มีเพลงให้ข้ามครับ",
                ephemeral=True,
            )
            return
        voice.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงให้แล้วครับ")

    @discord.ui.button(
        label="Stop",
        emoji="⏹️",
        style=discord.ButtonStyle.danger,
    )
    async def stop(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        state = get_state(self.bot, self.guild_id)
        await state.stop()
        await interaction.response.send_message(
            "👋 หยุดเพลง ล้างคิว และออกจากห้องให้แล้วครับ"
        )


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="play",
        description="เล่นเพลงจากชื่อ ลิงก์ YouTube หรือลิงก์ Spotify",
    )
    @app_commands.describe(query="ชื่อเพลง หรือลิงก์ YouTube/Spotify")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        if not await defer_interaction(interaction):
            return
        if not FFMPEG_EXECUTABLE:
            await interaction.followup.send(
                "🛠️ เครื่องที่รันบอทยังไม่มี FFmpeg",
                ephemeral=True,
            )
            return
        if not interaction.guild or not interaction.user.voice:
            await interaction.followup.send(
                "🎧 เข้าห้องเสียงก่อน แล้วเรียก `/play` อีกครั้งนะครับ",
                ephemeral=True,
            )
            return

        try:
            track = await resolve_track(query, interaction.user)
        except MusicError as error:
            await interaction.followup.send(f"😅 {error}", ephemeral=True)
            return

        voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client
        try:
            if voice_client is None:
                voice_client = await voice_channel.connect()
            elif voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)
        except discord.DiscordException:
            logger.exception("Could not connect to voice channel")
            await interaction.followup.send(
                "🎧 เข้าห้องเสียงไม่สำเร็จ กรุณาตรวจสิทธิ์ Connect/Speak",
                ephemeral=True,
            )
            return

        state = get_state(self.bot, interaction.guild.id)
        position = await state.enqueue(track, voice_client, interaction.channel)
        embed = discord.Embed(
            description=f"🎵 **{track.title}**",
            color=0x2ECC71 if position == 0 else 0x3498DB,
        )
        embed.set_author(
            name="กำลังเริ่มเล่น" if position == 0 else "เพิ่มเข้าคิวแล้ว"
        )
        embed.add_field(name="👤 ผู้ขอเพลง", value=interaction.user.mention)
        if position:
            embed.add_field(name="📋 ลำดับในคิว", value=f"`#{position}`")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="skip", description="ข้ามเพลงปัจจุบัน")
    async def skip(self, interaction: discord.Interaction) -> None:
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or (not voice.is_playing() and not voice.is_paused()):
            await interaction.response.send_message(
                "🎵 ตอนนี้ยังไม่มีเพลงให้ข้ามครับ",
                ephemeral=True,
            )
            return
        voice.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงให้แล้วครับ")

    @app_commands.command(name="pause", description="พักเพลงชั่วคราว")
    async def pause(self, interaction: discord.Interaction) -> None:
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or not voice.is_playing():
            await interaction.response.send_message(
                "🎵 ตอนนี้ยังไม่มีเพลงให้พักครับ",
                ephemeral=True,
            )
            return
        voice.pause()
        await interaction.response.send_message("⏸️ พักเพลงให้แล้วครับ")

    @app_commands.command(name="resume", description="เล่นเพลงที่พักไว้ต่อ")
    async def resume(self, interaction: discord.Interaction) -> None:
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or not voice.is_paused():
            await interaction.response.send_message(
                "▶️ เพลงไม่ได้พักอยู่ครับ",
                ephemeral=True,
            )
            return
        voice.resume()
        await interaction.response.send_message("▶️ เล่นเพลงต่อให้แล้วครับ")

    @app_commands.command(name="queue", description="แสดงคิวเพลงปัจจุบัน")
    async def queue_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        state = get_state(self.bot, interaction.guild.id)
        if not state.current and not state.queue:
            await interaction.response.send_message(
                "📭 คิวเพลงยังว่างอยู่ครับ",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="🎶 คิวเพลง", color=0x3498DB)
        current_text = state.current.title if state.current else "ไม่มี"
        embed.add_field(
            name="กำลังเล่น",
            value=current_text,
            inline=False,
        )
        queue_text = "\n".join(
            f"`{index:02d}` {track.title} — {track.requester.mention}"
            for index, track in enumerate(list(state.queue)[:10], start=1)
        )
        if len(state.queue) > 10:
            queue_text += f"\nและอีก {len(state.queue) - 10} เพลง"
        embed.add_field(
            name="เพลงถัดไป",
            value=queue_text or "ไม่มี",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="stop",
        description="หยุดเพลง ล้างคิว และออกจากห้องเสียง",
    )
    async def stop(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not interaction.guild.voice_client:
            await interaction.response.send_message(
                "🎧 ตอนนี้บอทไม่ได้อยู่ในห้องเสียงครับ",
                ephemeral=True,
            )
            return
        await get_state(self.bot, interaction.guild.id).stop()
        await interaction.response.send_message(
            "👋 หยุดเพลง ล้างคิว และออกจากห้องให้แล้วครับ"
        )


def load_opus() -> None:
    if discord.opus.is_loaded():
        return
    candidates = (
        "libopus.so.0",
        "libopus.so",
        "libopus.dylib",
        "/opt/homebrew/lib/libopus.dylib",
        "/usr/local/lib/libopus.dylib",
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
    )
    for candidate in candidates:
        try:
            discord.opus.load_opus(candidate)
            logger.info("Loaded Opus from %s", candidate)
            return
        except OSError:
            continue
    logger.warning("Opus library was not found; voice playback may fail")


async def setup(bot: commands.Bot) -> None:
    if not FFMPEG_EXECUTABLE:
        logger.error("FFmpeg was not found; /play will be unavailable")
    if not YTDL_OPTIONS["js_runtimes"]:
        logger.warning(
            "No supported JavaScript runtime found; install Node.js 22+ "
            "or Deno 2.3+ for reliable YouTube extraction"
        )
    load_opus()
    await bot.add_cog(MusicCog(bot))
