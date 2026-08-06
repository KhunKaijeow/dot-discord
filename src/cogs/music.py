"""Discord music commands with YouTube playback and Spotify link resolving."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import shlex
import shutil
from typing import Any
from urllib.parse import urlparse, parse_qs

from ..config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from ..services.music_queue import MusicQueue, QueueFullError
from ..ui import EmbedColor, make_embed, set_embed_author

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp


logger = logging.getLogger(__name__)

MAX_QUEUE_SIZE = 200
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


async def _resolve_youtube_playlist(url: str, requester: discord.abc.User) -> list[Track]:
    options = dict(YTDL_OPTIONS)
    options["extract_flat"] = "in_playlist"
    
    try:
        data = await asyncio.to_thread(
            lambda: yt_dlp.YoutubeDL(options).extract_info(url, download=False)
        )
    except Exception as e:
        logger.exception("YouTube playlist extraction failed")
        raise MusicError("อ่าน YouTube Playlist ไม่สำเร็จ ลองใหม่อีกทีนะ") from e

    entries = data.get("entries") or []
    tracks = []
    for entry in entries:
        if not entry:
            continue
        video_id = entry.get("id")
        title = entry.get("title") or "Unknown Song"
        if video_id:
            youtube_url = YOUTUBE_WATCH_URL.format(video_id=video_id)
            tracks.append(Track(
                title=title,
                youtube_url=youtube_url,
                requester=requester,
                requested_via="YouTube Playlist"
            ))
            
    if not tracks:
        raise MusicError("YouTube Playlist นี้ยังไม่มีเพลงที่เปิดได้นะ")
        
    return tracks


async def _resolve_spotify_playlist(playlist_id: str, requester: discord.abc.User) -> list[Track]:
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        raise MusicError(
            "บอทไม่ได้ตั้งค่าตัวแปร `SPOTIFY_CLIENT_ID` และ `SPOTIFY_CLIENT_SECRET` ในไฟล์ `.env` "
            "เลยยังโหลด Spotify Playlist ไม่ได้นะ"
        )
        
    token_url = "https://accounts.spotify.com/api/token"
    auth_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    auth_data = {
        "grant_type": "client_credentials",
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET
    }
    
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # 1. Exchange client credentials for an access token
            async with session.post(token_url, data=auth_data, headers=auth_headers) as token_resp:
                if token_resp.status != 200:
                    raise MusicError("การขอสิทธิ์เข้าถึง Spotify API (Token) ล้มเหลว")
                token_data = await token_resp.json()
                access_token = token_data.get("access_token")
                
            # 2. Get playlist tracks (up to 100 tracks)
            tracks_url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
            playlist_headers = {"Authorization": f"Bearer {access_token}"}
            params = {
                "fields": "items(track(name,artists(name)))",
                "limit": 100
            }
            async with session.get(tracks_url, headers=playlist_headers, params=params) as tracks_resp:
                if tracks_resp.status != 200:
                    raise MusicError("อ่าน Spotify Playlist ไม่สำเร็จ ลองใหม่อีกทีนะ")
                tracks_data = await tracks_resp.json()
    except MusicError:
        raise
    except Exception as e:
        logger.exception("Failed to connect to Spotify API")
        raise MusicError("เกิดข้อผิดพลาดในการเชื่อมต่อเพื่อดึงข้อมูล Spotify Playlist") from e
        
    items = tracks_data.get("items") or []
    tracks = []
    
    for item in items:
        track_info = item.get("track")
        if not track_info:
            continue
        track_name = track_info.get("name")
        artists = track_info.get("artists") or []
        artist_names = ", ".join(artist.get("name") for artist in artists if artist.get("name"))
        
        if track_name:
            search_query = f"{track_name} {artist_names}".strip()
            # Enqueue the query as a deferred search
            tracks.append(Track(
                title=f"{track_name} - {artist_names}" if artist_names else track_name,
                youtube_url=f"ytsearch1:{search_query} official audio",
                requester=requester,
                requested_via="Spotify Playlist"
            ))
            
    if not tracks:
        raise MusicError("Spotify Playlist นี้ยังไม่มีเพลงที่เปิดได้นะ")
        
    return tracks


async def resolve_tracks(query: str, requester: discord.abc.User) -> list[Track]:
    """Resolve text, YouTube URL (video/playlist), or Spotify URL (track/playlist) to a list of Tracks."""
    query = query.strip()
    if not query:
        raise MusicError("ส่งชื่อเพลงหรือลิงก์มาให้ผมหน่อยนะ")

    parsed = urlparse(query)
    host = parsed.hostname.lower().removeprefix("www.") if parsed.hostname else ""
    requested_via = "YouTube"

    # 1. Spotify Hosts
    if host in SPOTIFY_HOSTS:
        # Spotify link handling (redirects if spotify.link)
        clean_url = query
        if host == "spotify.link":
            timeout = aiohttp.ClientTimeout(total=10)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(query, allow_redirects=True) as response:
                        response.raise_for_status()
                        clean_url = str(response.url)
            except Exception as e:
                raise MusicError("เปิดลิงก์ย่อ Spotify ไม่สำเร็จ ลองใช้ลิงก์เต็มแทนนะ") from e
                
            parsed = urlparse(clean_url)
            host = parsed.hostname.lower().removeprefix("www.") if parsed.hostname else ""

        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[-2] == "playlist":
            playlist_id = path_parts[-1]
            return await _resolve_spotify_playlist(playlist_id, requester)
        elif len(path_parts) >= 2 and path_parts[-2] == "track":
            search_text = await _spotify_search_text(clean_url)
            youtube_query = f"ytsearch1:{search_text}"
            requested_via = "Spotify → YouTube"
        else:
            raise MusicError("รองรับเฉพาะลิงก์เพลงเดี่ยวและเพลย์ลิสต์ของ Spotify เท่านั้น")

    # 2. YouTube Hosts
    elif parsed.scheme in {"http", "https"}:
        if host not in YOUTUBE_HOSTS:
            raise MusicError("รองรับเฉพาะลิงก์ YouTube และ Spotify เท่านั้น")
            
        # Check if YouTube URL is a playlist (contains 'list=' parameter)
        query_params = parse_qs(parsed.query)
        if "list" in query_params:
            return await _resolve_youtube_playlist(query, requester)
            
        youtube_query = query
    else:
        youtube_query = f"ytsearch1:{query}"

    # Single track resolution (as before)
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

    return [Track(
        title=data.get("title") or "Unknown Song",
        youtube_url=webpage_url,
        requester=requester,
        requested_via=requested_via,
    )]


class YouTubeAudioSource(discord.PCMVolumeTransformer):
    def __init__(self, source: discord.AudioSource, data: dict[str, Any], volume: float = 0.5):
        super().__init__(source, volume=volume)
        self.data = data
        self.title = data.get("title") or "Unknown Song"
        self.webpage_url = data.get("webpage_url")
        self.thumbnail = data.get("thumbnail")

    @classmethod
    async def create(cls, youtube_url: str, volume: float = 0.5) -> YouTubeAudioSource:
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
        return cls(audio, data, volume)


class GuildMusicState:
    def __init__(self, bot: commands.Bot, guild_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.queue = MusicQueue[Track](max_size=MAX_QUEUE_SIZE)
        self.current: Track | None = None
        self.voice_client: discord.VoiceClient | None = None
        self.text_channel: discord.abc.Messageable | None = None
        self.stop_requested = False
        self.skip_requested = False
        self.loop_mode = "off"
        self.volume = 0.5
        self.advance_lock = asyncio.Lock()

    async def enqueue(
        self,
        track: Track,
        voice_client: discord.VoiceClient,
        text_channel: discord.abc.Messageable,
    ) -> int:
        return await self.enqueue_many([track], voice_client, text_channel)

    async def enqueue_many(
        self,
        tracks: list[Track],
        voice_client: discord.VoiceClient,
        text_channel: discord.abc.Messageable,
    ) -> int:
        if not tracks:
            raise ValueError("tracks must not be empty")
        self.ensure_capacity(len(tracks))
        self.voice_client = voice_client
        self.text_channel = text_channel
        self.stop_requested = False
        position = self.queue.extend(tracks)

        if (
            self.current is None
            and not voice_client.is_playing()
            and not voice_client.is_paused()
        ):
            await self.play_next()
            return 0
        return position

    def ensure_capacity(self, requested: int) -> None:
        available = self.queue.available - (1 if self.current else 0)
        if requested > available:
            raise QueueFullError(MAX_QUEUE_SIZE, requested, max(0, available))

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
            source = await YouTubeAudioSource.create(track.youtube_url, self.volume)
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
                content="😅 เตรียมเพลงไม่สำเร็จ ลองเลือกเพลงอื่นอีกทีนะ"
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
            color=EmbedColor.MUSIC,
        )
        set_embed_author(embed, self.bot, "Music • กำลังเล่น")
        if source.thumbnail:
            embed.set_thumbnail(url=source.thumbnail)
        embed.add_field(name="⏱️ ความยาวเพลง", value=f"`{duration_text}`", inline=True)
        embed.add_field(name="🔎 แหล่งคำขอ", value=f"`{track.requested_via}`", inline=True)
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
        finished = self.current
        if finished and not self.skip_requested:
            if self.loop_mode == "track":
                self.queue.appendleft(finished)
            elif self.loop_mode == "queue":
                self.queue.append(finished)
        self.skip_requested = False
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
            embed = make_embed(
                self.bot,
                "Music",
                title="👋 คิวหมดแล้วนะ",
                description="เพลงจบครบทุกเพลงแล้ว ผมออกจากห้องเสียงให้เรียบร้อย ไว้เปิดเพลงด้วยกันใหม่!",
                color=EmbedColor.INFO,
            )
            await self.text_channel.send(embed=embed)

    async def stop(self) -> None:
        self.stop_requested = True
        self.skip_requested = True
        self.queue.clear()
        self.current = None
        voice_client = self.voice_client
        self.voice_client = None
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()

    def skip(self) -> None:
        self.skip_requested = True
        if self.voice_client:
            self.voice_client.stop()


music_states: dict[int, GuildMusicState] = {}


def get_state(bot: commands.Bot, guild_id: int) -> GuildMusicState:
    if guild_id not in music_states:
        music_states[guild_id] = GuildMusicState(bot, guild_id)
    return music_states[guild_id]


def user_can_control_voice(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not interaction.guild.voice_client:
        return True
    user_voice = getattr(interaction.user, "voice", None)
    return bool(user_voice and user_voice.channel == interaction.guild.voice_client.channel)


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
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or not voice.is_playing():
            await interaction.response.send_message(
                "🎵 ตอนนี้ยังไม่มีเพลงให้พักนะ",
                ephemeral=True,
            )
            return
        voice.pause()
        await interaction.response.send_message("⏸️ พักเพลงให้แล้วนะ")

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
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or not voice.is_paused():
            await interaction.response.send_message(
                "▶️ เพลงนี้ไม่ได้พักอยู่นะ",
                ephemeral=True,
            )
            return
        voice.resume()
        await interaction.response.send_message("▶️ เล่นต่อให้แล้ว ไปฟังกันเลย")

    @discord.ui.button(label="Skip", emoji="⏭️")
    async def skip(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or (not voice.is_playing() and not voice.is_paused()):
            await interaction.response.send_message(
                "🎵 ตอนนี้ยังไม่มีเพลงให้ข้ามนะ",
                ephemeral=True,
            )
            return
        get_state(self.bot, self.guild_id).skip()
        await interaction.response.send_message("⏭️ ข้ามเพลงให้แล้วนะ")

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
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        state = get_state(self.bot, self.guild_id)
        await state.stop()
        await interaction.response.send_message(
            "👋 หยุดเพลง ล้างคิว และออกจากห้องให้แล้วนะ"
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
                "🎧 เข้าห้องเสียงก่อน แล้วเรียก `/play` ใหม่อีกทีนะ",
                ephemeral=True,
            )
            return

        try:
            tracks = await resolve_tracks(query, interaction.user)
        except MusicError as error:
            await interaction.followup.send(f"😅 {error}", ephemeral=True)
            return

        state = get_state(self.bot, interaction.guild.id)
        try:
            state.ensure_capacity(len(tracks))
        except QueueFullError as error:
            await interaction.followup.send(
                f"คิวรับเพิ่มได้อีก `{error.available}` เพลง แต่รายการนี้มี `{error.requested}` เพลงนะ",
                ephemeral=True,
            )
            return

        voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.channel != voice_channel and (
            voice_client.is_playing() or voice_client.is_paused()
        ):
            await interaction.followup.send("บอทกำลังใช้งานในห้องเสียงอื่นอยู่", ephemeral=True)
            return
        try:
            if voice_client is None:
                voice_client = await voice_channel.connect()
            elif voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)
        except discord.DiscordException:
            logger.exception("Could not connect to voice channel")
            await interaction.followup.send(
                "🎧 เข้าห้องเสียงไม่สำเร็จ ลองเช็กสิทธิ์ Connect/Speak ให้หน่อยนะ",
                ephemeral=True,
            )
            return

        try:
            first_position = await state.enqueue_many(
                tracks,
                voice_client,
                interaction.channel,
            )
        except QueueFullError as error:
            await interaction.followup.send(
                f"คิวรับเพิ่มได้อีก `{error.available}` เพลง แต่รายการนี้มี `{error.requested}` เพลงนะ",
                ephemeral=True,
            )
            return
        is_playing_now = first_position == 0
            
        if len(tracks) > 1:
            embed = make_embed(
                self.bot,
                "Music",
                title="🎶 เพลย์ลิสต์พร้อมแล้ว",
                description=f"ใส่เพลงเข้าคิวให้ครบ `{len(tracks)}` เพลงแล้ว ไปฟังกันเลย!",
                color=EmbedColor.SUCCESS if is_playing_now else EmbedColor.INFO,
            )
            await interaction.followup.send(embed=embed)
        else:
            track = tracks[0]
            embed = discord.Embed(
                description=f"🎵 **[{track.title}]({track.youtube_url})**",
                color=EmbedColor.SUCCESS if is_playing_now else EmbedColor.INFO,
            )
            set_embed_author(
                embed,
                self.bot,
                "Music • กำลังเล่น" if is_playing_now else "Music • เข้าคิวแล้ว",
            )
            embed.add_field(name="🔎 แหล่งคำขอ", value=f"`{track.requested_via}`", inline=True)
            if not is_playing_now:
                embed.add_field(name="📋 ลำดับคิว", value=f"`#{first_position}`", inline=True)
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="skip", description="ข้ามเพลงปัจจุบัน")
    async def skip(self, interaction: discord.Interaction) -> None:
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or (not voice.is_playing() and not voice.is_paused()):
            await interaction.response.send_message(
                "🎵 ตอนนี้ยังไม่มีเพลงให้ข้ามนะ",
                ephemeral=True,
            )
            return
        get_state(self.bot, interaction.guild.id).skip()
        await interaction.response.send_message("⏭️ ข้ามเพลงให้แล้วนะ")

    @app_commands.command(name="pause", description="พักเพลงชั่วคราว")
    async def pause(self, interaction: discord.Interaction) -> None:
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or not voice.is_playing():
            await interaction.response.send_message(
                "🎵 ตอนนี้ยังไม่มีเพลงให้พักนะ",
                ephemeral=True,
            )
            return
        voice.pause()
        await interaction.response.send_message("⏸️ พักเพลงให้แล้วนะ")

    @app_commands.command(name="resume", description="เล่นเพลงที่พักไว้ต่อ")
    async def resume(self, interaction: discord.Interaction) -> None:
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        voice = interaction.guild.voice_client if interaction.guild else None
        if not voice or not voice.is_paused():
            await interaction.response.send_message(
                "▶️ เพลงนี้ไม่ได้พักอยู่นะ",
                ephemeral=True,
            )
            return
        voice.resume()
        await interaction.response.send_message("▶️ เล่นต่อให้แล้ว ไปฟังกันเลย")

    @app_commands.command(name="queue", description="แสดงคิวเพลงปัจจุบัน")
    async def queue_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        state = get_state(self.bot, interaction.guild.id)
        if not state.current and not state.queue:
            await interaction.response.send_message(
                "📭 คิวเพลงยังว่างอยู่ ลองเพิ่มเพลงที่ชอบเข้ามาได้เลย",
                ephemeral=True,
            )
            return

        embed = make_embed(
            self.bot,
            "Music",
            title="🎶 คิวเพลงของเรา",
            description=f"มีเพลงรออยู่ `{len(state.queue)}` เพลง",
            color=EmbedColor.MUSIC,
        )
        if state.current:
            embed.add_field(
                name="▶️ ตอนนี้กำลังเล่น",
                value=f"▶️ **[{state.current.title}]({state.current.youtube_url})**",
                inline=False,
            )
        else:
            embed.add_field(
                name="▶️ ตอนนี้กำลังเล่น",
                value="*ยังไม่มีเพลงที่กำลังเล่น*",
                inline=False,
            )
        
        queue_items = []
        for index, track in enumerate(list(state.queue)[:10], start=1):
            queue_items.append(f"`{index:02d}` [{track.title}]({track.youtube_url})")
        queue_text = "\n".join(queue_items)
        if len(state.queue) > 10:
            queue_text += f"\n*และอีก {len(state.queue) - 10} เพลงในคิว*"
            
        embed.add_field(
            name="📋 เพลงถัดไป",
            value=queue_text or "*ยังไม่มีเพลงรออยู่*",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="now-playing", description="ดูเพลงที่กำลังเล่นและสถานะการเล่น")
    async def now_playing(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        state = get_state(self.bot, interaction.guild.id)
        if not state.current:
            await interaction.response.send_message("🎵 ตอนนี้ยังไม่มีเพลงเล่นอยู่", ephemeral=True)
            return
        loop_map = {"off": "❌ ปิด", "track": "🔂 เพลงปัจจุบัน", "queue": "🔁 ทั้งคิว"}
        loop_text = loop_map.get(state.loop_mode, state.loop_mode)
        
        embed = make_embed(
            self.bot,
            "Music",
            title="🎵 เพลงที่กำลังเล่น",
            description=f"🎵 **[{state.current.title}]({state.current.youtube_url})**",
            color=EmbedColor.MUSIC,
        )
        embed.add_field(name="🔊 ระดับเสียง", value=f"`{int(state.volume * 100)}%`", inline=True)
        embed.add_field(name="🔁 โหมดเล่นซ้ำ", value=f"`{loop_text}`", inline=True)
        embed.add_field(name="🔎 แหล่งคำขอ", value=f"`{state.current.requested_via}`", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="ปรับระดับเสียง 0–100%")
    async def volume(self, interaction: discord.Interaction, percent: app_commands.Range[int, 0, 100]) -> None:
        if not interaction.guild:
            return
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        state = get_state(self.bot, interaction.guild.id)
        state.volume = percent / 100
        voice = interaction.guild.voice_client
        if voice and isinstance(voice.source, discord.PCMVolumeTransformer):
            voice.source.volume = state.volume
        await interaction.response.send_message(f"🔊 ตั้งระดับเสียงเป็น `{percent}%` แล้ว")

    @app_commands.command(name="loop", description="ตั้งโหมดเล่นซ้ำ")
    @app_commands.choices(mode=[
        app_commands.Choice(name="ปิด", value="off"),
        app_commands.Choice(name="เพลงปัจจุบัน", value="track"),
        app_commands.Choice(name="ทั้งคิว", value="queue"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: str) -> None:
        if not interaction.guild:
            return
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        get_state(self.bot, interaction.guild.id).loop_mode = mode
        await interaction.response.send_message(f"🔁 ตั้ง Loop เป็น `{mode}` แล้ว")

    @app_commands.command(name="shuffle", description="สุ่มลำดับเพลงในคิว")
    async def shuffle(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        state = get_state(self.bot, interaction.guild.id)
        state.queue.shuffle()
        await interaction.response.send_message(f"🔀 สุ่มคิว `{len(state.queue)}` เพลงแล้ว")

    @app_commands.command(name="remove", description="นำเพลงออกจากคิวตามลำดับ")
    async def remove(
        self,
        interaction: discord.Interaction,
        position: app_commands.Range[int, 1, MAX_QUEUE_SIZE],
    ) -> None:
        if not interaction.guild:
            return
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        state = get_state(self.bot, interaction.guild.id)
        if position > len(state.queue):
            await interaction.response.send_message("ไม่พบลำดับเพลงนี้", ephemeral=True)
            return
        removed = state.queue.remove(position)
        await interaction.response.send_message(f"🗑️ นำ **{removed.title}** ออกจากคิวแล้ว")

    @app_commands.command(name="clear-queue", description="ล้างเพลงที่รอทั้งหมดโดยไม่หยุดเพลงปัจจุบัน")
    async def clear_queue(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            return
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        state = get_state(self.bot, interaction.guild.id)
        count = state.queue.clear()
        await interaction.response.send_message(f"🧹 ล้างคิว `{count}` เพลงแล้ว")

    @app_commands.command(
        name="stop",
        description="หยุดเพลง ล้างคิว และออกจากห้องเสียง",
    )
    async def stop(self, interaction: discord.Interaction) -> None:
        if not user_can_control_voice(interaction):
            await interaction.response.send_message("ต้องอยู่ห้องเสียงเดียวกับบอท", ephemeral=True)
            return
        if not interaction.guild or not interaction.guild.voice_client:
            await interaction.response.send_message(
                "🎧 ตอนนี้ผมยังไม่ได้อยู่ในห้องเสียงนะ",
                ephemeral=True,
            )
            return
        await get_state(self.bot, interaction.guild.id).stop()
        await interaction.response.send_message(
            "👋 หยุดเพลง ล้างคิว และออกจากห้องให้แล้วนะ"
        )

    @app_commands.command(name="playlist-save", description="บันทึกเพลงในคิวปัจจุบันเป็นเพลย์ลิสต์ส่วนตัว")
    @app_commands.describe(name="ชื่อเพลย์ลิสต์ (ความยาวไม่เกิน 50 ตัวอักษร)")
    async def playlist_save(self, interaction: discord.Interaction, name: str) -> None:
        if not interaction.guild:
            return
        
        name = name.strip()
        if not 1 <= len(name) <= 50:
            await interaction.response.send_message("ชื่อเพลย์ลิสต์ใช้ได้ 1–50 ตัวอักษรนะ", ephemeral=True)
            return

        state = get_state(self.bot, interaction.guild.id)
        
        tracks_to_save = []
        if state.current:
            tracks_to_save.append(state.current)
        tracks_to_save.extend(list(state.queue))
        
        if not tracks_to_save:
            await interaction.response.send_message("ยังไม่มีเพลงให้เก็บ เปิดเพลงหรือเพิ่มคิวก่อนนะ", ephemeral=True)
            return
            
        if len(tracks_to_save) > 100:
            await interaction.response.send_message("หนึ่งเพลย์ลิสต์เก็บได้ 100 เพลง ตอนนี้คิวยาวเกินไปนิดนึงนะ", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        try:
            user_id = interaction.user.id
            playlist_count = await asyncio.to_thread(self.bot.database.count_user_playlists, user_id)
            
            existing_playlists = await asyncio.to_thread(self.bot.database.list_playlists, user_id)
            is_overwrite = any(p["name"].lower() == name.lower() for p in existing_playlists)
            
            if playlist_count >= 10 and not is_overwrite:
                await interaction.followup.send("เก็บครบ 10 เพลย์ลิสต์แล้ว ลบอันเก่าสักรายการก่อนนะ")
                return

            track_tuples = [(t.title, t.youtube_url, t.requested_via) for t in tracks_to_save]
            
            await asyncio.to_thread(self.bot.database.save_playlist, user_id, name, track_tuples)
            
            action_text = "เขียนทับ" if is_overwrite else "บันทึก"
            embed = make_embed(
                self.bot,
                "Music • Playlist",
                title="💾 เก็บเพลย์ลิสต์ไว้ให้แล้ว",
                description=(
                    f"**ชื่อ** `{name}`\n"
                    f"**จำนวน** `{len(track_tuples)}` เพลง • {action_text}เรียบร้อย"
                ),
                color=EmbedColor.SUCCESS,
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.exception("Error saving playlist")
            await interaction.followup.send("😅 เก็บเพลย์ลิสต์ไม่สำเร็จ ลองใหม่อีกทีนะ")

    @app_commands.command(name="playlist-load", description="โหลดเพลงจากเพลย์ลิสต์ส่วนตัวเข้าสู่คิว")
    @app_commands.describe(name="ชื่อเพลย์ลิสต์ที่บันทึกไว้")
    async def playlist_load(self, interaction: discord.Interaction, name: str) -> None:
        if not interaction.guild:
            return
        
        if not interaction.user.voice:
            await interaction.response.send_message(
                "🎧 เข้าห้องเสียงก่อน แล้วเรียก `/playlist-load` ใหม่อีกทีนะ",
                ephemeral=True,
            )
            return

        name = name.strip()
        await interaction.response.defer(thinking=True)

        try:
            user_id = interaction.user.id
            db_tracks = await asyncio.to_thread(self.bot.database.load_playlist, user_id, name)
            
            if not db_tracks:
                await interaction.followup.send(f"หาเพลย์ลิสต์ `{name}` ไม่เจอ ลองเช็กชื่ออีกทีนะ")
                return

            state = get_state(self.bot, interaction.guild.id)
            try:
                state.ensure_capacity(len(db_tracks))
            except QueueFullError as error:
                await interaction.followup.send(
                    f"คิวรับเพิ่มได้อีก `{error.available}` เพลง แต่เพลย์ลิสต์นี้มี `{error.requested}` เพลงนะ"
                )
                return

            voice_channel = interaction.user.voice.channel
            voice_client = interaction.guild.voice_client
            
            if voice_client and voice_client.channel != voice_channel and (
                voice_client.is_playing() or voice_client.is_paused()
            ):
                await interaction.followup.send("ตอนนี้ผมเปิดเพลงอยู่อีกห้องนึงนะ")
                return

            try:
                if voice_client is None:
                    voice_client = await voice_channel.connect()
                elif voice_client.channel != voice_channel:
                    await voice_client.move_to(voice_channel)
            except discord.DiscordException:
                logger.exception("Could not connect to voice channel")
                await interaction.followup.send("🎧 เข้าห้องเสียงไม่สำเร็จ ลองเช็กสิทธิ์ Connect/Speak ให้หน่อยนะ")
                return

            tracks = []
            for row in db_tracks:
                tracks.append(
                    Track(
                        title=row["title"],
                        youtube_url=row["youtube_url"],
                        requester=interaction.user,
                        requested_via=row["requested_via"],
                    )
                )
            try:
                await state.enqueue_many(tracks, voice_client, interaction.channel)
            except QueueFullError as error:
                await interaction.followup.send(
                    f"คิวรับเพิ่มได้อีก `{error.available}` เพลง แต่เพลย์ลิสต์นี้มี `{error.requested}` เพลงนะ"
                )
                return

            embed = make_embed(
                self.bot,
                "Music • Playlist",
                title="🎶 โหลดเพลย์ลิสต์ให้แล้ว",
                description=f"เพลงจาก `{name}` เข้าแถวรอครบ `{len(tracks)}` เพลงแล้ว ไปฟังกันเลย!",
                color=EmbedColor.MUSIC,
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception("Error loading playlist")
            await interaction.followup.send("😅 โหลดเพลย์ลิสต์สะดุดนิดหน่อย ลองใหม่อีกทีนะ")

    @app_commands.command(name="playlist-list", description="แสดงรายชื่อเพลย์ลิสต์ส่วนตัวทั้งหมดของคุณ")
    async def playlist_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            user_id = interaction.user.id
            playlists = await asyncio.to_thread(self.bot.database.list_playlists, user_id)
            
            if not playlists:
                embed = make_embed(
                    self.bot,
                    "Music • Playlist",
                    title="📭 ชั้นวางเพลงยังว่างอยู่",
                    description="เปิดเพลงที่ชอบแล้วใช้ `/playlist-save` เก็บไว้ฟังรอบหน้าได้เลย",
                    color=EmbedColor.INFO,
                )
                await interaction.followup.send(embed=embed)
                return

            embed = make_embed(
                self.bot,
                "Music • Playlist",
                title="💾 เพลย์ลิสต์ที่เก็บไว้",
                description=f"มีทั้งหมด `{len(playlists)}/10` เพลย์ลิสต์",
                color=EmbedColor.MUSIC,
            )
            
            desc_items = []
            for i, p in enumerate(playlists, start=1):
                try:
                    dt = datetime.fromisoformat(p["created_at"])
                    date_str = dt.strftime("%d/%m/%Y")
                except Exception:
                    date_str = p["created_at"]
                
                desc_items.append(
                    f"`{i:02d}` **{p['name']}** — `{p['track_count']}` เพลง (สร้างเมื่อ: {date_str})"
                )
            
            embed.add_field(
                name="🎧 เลือกฟังได้เลย",
                value="\n".join(desc_items),
                inline=False,
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.exception("Error listing playlists")
            await interaction.followup.send("😅 เปิดรายการเพลย์ลิสต์ไม่สำเร็จ ลองใหม่อีกทีนะ")

    @app_commands.command(name="playlist-delete", description="ลบเพลย์ลิสต์ส่วนตัวของคุณ")
    @app_commands.describe(name="ชื่อเพลย์ลิสต์ที่ต้องการลบ")
    async def playlist_delete(self, interaction: discord.Interaction, name: str) -> None:
        name = name.strip()
        await interaction.response.defer(thinking=True)
        try:
            user_id = interaction.user.id
            deleted = await asyncio.to_thread(self.bot.database.delete_playlist, user_id, name)
            
            if deleted:
                embed = make_embed(
                    self.bot,
                    "Music • Playlist",
                    title="🗑️ เอาเพลย์ลิสต์ออกแล้ว",
                    description=f"ลบ `{name}` ออกจากชั้นวางให้เรียบร้อยแล้วนะ",
                    color=EmbedColor.SUCCESS,
                )
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(f"หาเพลย์ลิสต์ `{name}` ไม่เจอ ลองเช็กชื่ออีกทีนะ")
                
        except Exception as e:
            logger.exception("Error deleting playlist")
            await interaction.followup.send("😅 ลบเพลย์ลิสต์ไม่สำเร็จ ลองใหม่อีกทีนะ")


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
