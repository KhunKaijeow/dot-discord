"""Per-guild Discord voice player and queue lifecycle."""

from __future__ import annotations

import asyncio
from collections import deque
import logging
import random

import discord

from ..ui import EmbedColor, make_embed
from .models import Track
from .sources import MusicSourceResolver, SourceError, YouTubeAuthenticationError


logger = logging.getLogger("discord.javis.music.player")

FFMPEG_BEFORE_OPTIONS = "-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTIONS = "-vn"


class GuildPlayer:
    """Own one guild's voice connection, queue, and worker task."""

    def __init__(
        self,
        bot,
        guild_id: int,
        sources: MusicSourceResolver,
        *,
        idle_timeout: float = 180,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.sources = sources
        self.idle_timeout = idle_timeout
        self.voice: discord.VoiceClient | None = None
        self.text_channel: discord.abc.Messageable | None = None
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.volume = 0.5
        self._queue_changed = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._closed = False

    def attach(self, voice: discord.VoiceClient, text_channel: discord.abc.Messageable) -> None:
        self.voice = voice
        self.text_channel = text_channel
        self._closed = False

    def enqueue(self, tracks: list[Track]) -> int:
        self.queue.extend(tracks)
        self._queue_changed.set()
        self._ensure_worker()
        return len(tracks)

    def _ensure_worker(self) -> None:
        if not self._worker or self._worker.done():
            self._worker = asyncio.create_task(
                self._player_loop(),
                name=f"music-player-{self.guild_id}",
            )

    async def _player_loop(self) -> None:
        try:
            while not self._closed and self.voice and self.voice.is_connected():
                self._queue_changed.clear()
                if not self.queue:
                    try:
                        await asyncio.wait_for(self._queue_changed.wait(), timeout=self.idle_timeout)
                    except asyncio.TimeoutError:
                        await self._send("💤 ไม่มีเพลงใหม่ในคิว บอทออกจากห้องเสียงแล้ว")
                        await self.disconnect()
                        return
                    continue

                track = self.queue.popleft()
                self.current = track
                try:
                    stream_url = await self.sources.stream_url(track)
                    await self._play(track, stream_url)
                except YouTubeAuthenticationError:
                    self.queue.clear()
                    logger.warning(
                        "Audio provider authentication failed for guild %d (input source: %s)",
                        self.guild_id,
                        track.source,
                    )
                    if track.source == "spotify":
                        message = (
                            "❌ อ่านข้อมูล Spotify สำเร็จ แต่ Spotify ไม่ส่ง audio stream สำหรับ Discord "
                            "และ YouTube ซึ่งเป็นแหล่งเสียงถูกปฏิเสธการเชื่อมต่อ "
                            "กรุณาตั้งค่า `YOUTUBE_COOKIES_BASE64`"
                        )
                    else:
                        message = (
                            "❌ YouTube ปฏิเสธการเชื่อมต่อ กรุณาตั้งค่า "
                            "`YOUTUBE_COOKIES_BASE64`"
                        )
                    await self._send(message)
                    await self.disconnect()
                    return
                except SourceError as exc:
                    logger.warning("Could not resolve stream for guild %d: %s", self.guild_id, exc)
                    await self._send(f"❌ เล่น **{track.display_name}** ไม่สำเร็จ: {exc}")
                except discord.ClientException as exc:
                    logger.exception("Discord audio setup failed for guild %d", self.guild_id)
                    message = (
                        "ไม่พบ FFmpeg ใน runtime กรุณา rebuild deployment"
                        if "ffmpeg" in str(exc).lower()
                        else "Discord ไม่สามารถเริ่ม audio player ได้"
                    )
                    await self._send(f"❌ {message}")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Unexpected playback failure for guild %d", self.guild_id)
                    await self._send("❌ เกิดข้อผิดพลาดระหว่างเล่นเพลง")
                finally:
                    self.current = None
        finally:
            self.current = None

    async def _play(self, track: Track, stream_url: str) -> None:
        voice = self.voice
        if not voice or not voice.is_connected():
            raise SourceError("การเชื่อมต่อห้องเสียงถูกตัด")

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(
                stream_url,
                before_options=FFMPEG_BEFORE_OPTIONS,
                options=FFMPEG_OPTIONS,
            ),
            volume=self.volume,
        )
        finished = asyncio.Event()
        loop = asyncio.get_running_loop()

        def after_playback(error: Exception | None) -> None:
            if error:
                logger.error("Voice playback callback failed for guild %d: %s", self.guild_id, error)
            loop.call_soon_threadsafe(finished.set)

        voice.play(source, after=after_playback)
        await self._announce(track)
        await finished.wait()

    async def _announce(self, track: Track) -> None:
        embed = make_embed(
            self.bot,
            "Music",
            title="🎵 กำลังเล่น",
            description=f"**[{track.display_name}]({track.webpage_url})**\nขอโดย: {track.requester}",
            color=EmbedColor.PRIMARY,
        )
        if track.duration:
            minutes, seconds = divmod(int(track.duration), 60)
            embed.add_field(name="ความยาว", value=f"{minutes}:{seconds:02d}", inline=True)
        embed.add_field(name="ลิงก์ต้นทาง", value=track.source.title(), inline=True)
        embed.add_field(name="แหล่งเสียง", value="YouTube", inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        await self._send(embed=embed)

    async def _send(self, content: str | None = None, *, embed: discord.Embed | None = None) -> None:
        if not self.text_channel:
            return
        try:
            await self.text_channel.send(content, embed=embed)
        except discord.HTTPException:
            logger.warning("Could not send music status to guild %d", self.guild_id)

    def pause(self) -> bool:
        if not self.voice or not self.voice.is_playing():
            return False
        self.voice.pause()
        return True

    def resume(self) -> bool:
        if not self.voice or not self.voice.is_paused():
            return False
        self.voice.resume()
        return True

    def skip(self) -> bool:
        if not self.voice or not (self.voice.is_playing() or self.voice.is_paused()):
            return False
        self.voice.stop()
        return True

    def shuffle(self) -> bool:
        if len(self.queue) < 2:
            return False
        shuffled = list(self.queue)
        random.shuffle(shuffled)
        self.queue = deque(shuffled)
        return True

    async def stop(self) -> None:
        self.queue.clear()
        self._queue_changed.set()
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()
        await self.disconnect()

    async def disconnect(self) -> None:
        self._closed = True
        voice = self.voice
        self.voice = None
        if voice and voice.is_connected():
            try:
                await voice.disconnect(force=True)
            except discord.DiscordException:
                logger.warning("Could not disconnect voice in guild %d", self.guild_id)
        current_task = asyncio.current_task()
        if self._worker and self._worker is not current_task and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        self._worker = None
        self.current = None
