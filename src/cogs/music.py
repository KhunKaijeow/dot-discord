"""Music playback slash commands supporting Spotify and YouTube."""

import asyncio
import logging
import random
import re
from typing import Dict, List, Optional, Any

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

from ..services.spotify import SpotifyService
from ..ui import EmbedColor, make_embed

logger = logging.getLogger("discord.javis.music")

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "ios", "mweb", "tv_embedded"],
        }
    },
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class Track:
    """Represents an audio track queued for playback."""

    def __init__(
        self,
        title: str,
        artist: str,
        duration: float,
        url: str,
        thumbnail: Optional[str] = None,
        requester: str = "",
        spotify_id: Optional[str] = None,
    ) -> None:
        self.title = title
        self.artist = artist
        self.duration = duration  # in seconds
        self.url = url  # original link (YouTube or Spotify)
        self.thumbnail = thumbnail
        self.requester = requester
        self.spotify_id = spotify_id
        self.stream_url: Optional[str] = None
        self.resolved = False

    def get_search_query(self) -> str:
        """Get the search term or URL for yt-dlp to resolve the stream."""
        if self.spotify_id:
            return f"{self.title} {self.artist}"
        return self.url or self.title


class GuildMusicState:
    """Manages the music queue and playback loop for a single Guild (Server)."""

    def __init__(self, bot: commands.Bot, guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue: List[Track] = []
        self.current: Optional[Track] = None
        self.voice_client: Optional[discord.VoiceClient] = None
        self.volume: float = 0.5
        self.loop_mode: str = "off"  # "off", "track", "queue"
        self.play_next_event = asyncio.Event()
        self.player_task: Optional[asyncio.Task] = None
        self.text_channel: Optional[discord.TextChannel] = None
        self.idle_timeout_seconds = 180.0

    def start_player(self, text_channel: discord.TextChannel) -> None:
        """Start the audio player background task if not running."""
        self.text_channel = text_channel
        if not self.player_task or self.player_task.done():
            self.player_task = asyncio.create_task(self.player_loop())

    async def player_loop(self) -> None:
        """Background task that runs continuously to play queued songs."""
        while True:
            self.play_next_event.clear()

            if not self.voice_client or not self.voice_client.is_connected():
                logger.info("Voice client disconnected. Stopping player loop for guild %d.", self.guild_id)
                break

            # Handle loops and queue pops
            if self.loop_mode == "track" and self.current:
                # Play the current track again
                track = self.current
            else:
                if not self.queue:
                    # Inactivity timeout wait
                    try:
                        await asyncio.wait_for(self.wait_for_track(), timeout=self.idle_timeout_seconds)
                    except asyncio.TimeoutError:
                        if self.text_channel:
                            embed = make_embed(
                                self.bot,
                                "Music",
                                title="💤 ปิดเพลงเนื่องจากไม่มีการเล่นนานเกินไป",
                                description="ไม่มีเพลงใหม่ในคิว ผมขอตัวออกจากห้องก่อนนะ 👋",
                                color=EmbedColor.INFO,
                            )
                            await self.text_channel.send(embed=embed)
                        await self.stop()
                        break

                if not self.queue:
                    continue

                track = self.queue.pop(0)
                if self.loop_mode == "queue" and self.current:
                    self.queue.append(self.current)
                self.current = track

            # Lazy resolve track stream URL if not resolved yet
            if not track.resolved:
                try:
                    await self.resolve_track(track)
                except Exception:
                    logger.exception("Failed to resolve track stream url for: %s", track.title)
                    if self.text_channel:
                        await self.text_channel.send(f"❌ ไม่สามารถเล่นเพลง **{track.title}** ได้เนื่องจากพบปัญหาในการดึงข้อมูลเพลง")
                    self.current = None
                    continue

            # Play the stream using ffmpeg
            try:
                # Create the audio source and wrap in Volume Transformer
                ffmpeg_source = discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTIONS)
                source = discord.PCMVolumeTransformer(ffmpeg_source, volume=self.volume)

                def after_playing(error: Optional[Exception]) -> None:
                    if error:
                        logger.error("Error occurred in audio player after callback: %s", error)
                    self.bot.loop.call_soon_threadsafe(self.play_next_event.set)

                self.voice_client.play(source, after=after_playing)

                # Announce the song to the chat
                if self.text_channel and self.loop_mode != "track":
                    embed = make_embed(
                        self.bot,
                        "Music",
                        title="🎵 กำลังเล่น",
                        description=f"**[{track.title}]({track.url})**\nขอโดย: {track.requester}",
                        color=EmbedColor.PRIMARY,
                    )
                    if track.artist:
                        embed.add_field(name="ศิลปิน", value=track.artist, inline=True)
                    if track.duration:
                        m, s = divmod(int(track.duration), 60)
                        embed.add_field(name="ความยาว", value=f"{m}:{s:02d}", inline=True)
                    if track.thumbnail:
                        embed.set_thumbnail(url=track.thumbnail)
                    await self.text_channel.send(embed=embed)

                # Wait for the song to finish or skip command to trigger
                await self.play_next_event.wait()
            except Exception:
                logger.exception("Error during playback setup for guild %d", self.guild_id)
                if self.text_channel:
                    await self.text_channel.send("❌ เกิดข้อผิดพลาดในการเริ่มเล่นเพลง รอสักครู่แล้วลองอีกทีนะ")
                await asyncio.sleep(2)

        self.current = None

    async def wait_for_track(self) -> None:
        """Wait until a track is appended to the queue or voice client disconnects."""
        while not self.queue:
            if not self.voice_client or not self.voice_client.is_connected():
                break
            await asyncio.sleep(0.5)

    async def resolve_track(self, track: Track) -> None:
        """Fetch the stream URL using yt-dlp in a separate executor thread."""
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, self._extract_info, track.get_search_query())
        if not info:
            raise ValueError("Could not extract stream information using yt-dlp")

        track.stream_url = info.get("url")
        if not track.title or track.title == track.url:
            track.title = info.get("title", "Unknown Title")
        if not track.url:
            track.url = info.get("webpage_url")
        if not track.duration:
            track.duration = info.get("duration", 0)
        if not track.thumbnail:
            track.thumbnail = info.get("thumbnail")
        track.resolved = True

    def _extract_info(self, query: str) -> Optional[Dict[str, Any]]:
        """Run yt-dlp to extract info synchronously."""
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
            is_url = query.startswith("http://") or query.startswith("https://")
            search_query = query if is_url else f"ytsearch1:{query}"
            try:
                info = ydl.extract_info(search_query, download=False)
                if not info:
                    return None
                if "entries" in info:
                    entries = info["entries"]
                    if not entries:
                        return None
                    return entries[0]
                return info
            except Exception:
                logger.exception("yt-dlp extraction failed for query: %s", query)
                return None

    async def stop(self) -> None:
        """Stop playback, empty queue, and disconnect."""
        self.queue.clear()
        self.current = None
        self.loop_mode = "off"
        if self.voice_client:
            try:
                await self.voice_client.disconnect()
            except Exception:
                logger.exception("Failed to disconnect voice client")
            self.voice_client = None
        if self.player_task and not self.player_task.done():
            self.player_task.cancel()


class MusicCog(commands.Cog):
    """Cog grouping slash commands for Discord Music feature."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.spotify = SpotifyService(bot.external_http)
        self.states: Dict[int, GuildMusicState] = {}

    def get_guild_state(self, guild_id: int) -> GuildMusicState:
        """Get or initialize the music state manager for a guild."""
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState(self.bot, guild_id)
        return self.states[guild_id]

    def _extract_youtube_playlist(self, url: str) -> List[Dict[str, Any]]:
        """Extract flat entries from a YouTube playlist URL."""
        opts = {
            "extract_flat": True,
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "mweb", "tv_embedded"],
                }
            },
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return []
                entries = info.get("entries", [])
                valid_entries = []
                for entry in entries:
                    if entry and entry.get("title") and entry.get("url"):
                        video_url = entry.get("url")
                        if not video_url.startswith("http"):
                            video_url = f"https://www.youtube.com/watch?v={video_url}"
                        thumbnails = entry.get("thumbnails", [])
                        thumbnail = thumbnails[0].get("url") if thumbnails else None
                        valid_entries.append({
                            "title": entry.get("title"),
                            "url": video_url,
                            "duration": entry.get("duration", 0),
                            "thumbnail": thumbnail,
                        })
                return valid_entries
            except Exception:
                logger.exception("Failed to extract YouTube playlist")
                return []

    @app_commands.command(name="play", description="เล่นเพลงจาก YouTube/Spotify (รองรับ ลิงก์เดี่ยว, ลิงก์ Playlist, หรือพิมพ์ค้นหา)")
    @app_commands.describe(query="ลิงก์เพลงหรือคำค้นหา เช่น Taylor Swift Blank Space")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        """Resolve query or link and play it in the voice channel."""
        # Defer immediately since resolving playlists/fetching can take time
        await interaction.response.defer(thinking=True)

        if not interaction.user.voice or not interaction.user.voice.channel:
            embed = make_embed(
                self.bot,
                "Music",
                title="❌ ล้มเหลว",
                description="คุณต้องเข้าห้องเสียงก่อนใช้งานคำสั่งนี้ครับ",
                color=EmbedColor.ERROR,
            )
            await interaction.followup.send(embed=embed)
            return

        voice_channel = interaction.user.voice.channel
        guild_id = interaction.guild_id
        if not guild_id:
            return

        state = self.get_guild_state(guild_id)

        # Check channel occupancy
        if state.voice_client and state.voice_client.channel != voice_channel:
            embed = make_embed(
                self.bot,
                "Music",
                title="❌ ล้มเหลว",
                description="บอทกำลังทำงานในห้องเสียงอื่นอยู่ครับ ไม่สามารถดึงตัวไปได้",
                color=EmbedColor.ERROR,
            )
            await interaction.followup.send(embed=embed)
            return

        # Connect to voice with stale cleanup and timeout parameters
        if not state.voice_client or not state.voice_client.is_connected():
            try:
                if state.voice_client:
                    try:
                        await state.voice_client.disconnect(force=True)
                    except Exception:
                        pass
                    state.voice_client = None

                state.voice_client = await voice_channel.connect(timeout=30.0, reconnect=True, self_deaf=True)
            except Exception as e:
                logger.exception("Failed to connect to voice channel")
                error_msg = str(e)
                if "PyNaCl" in error_msg or "davey" in error_msg:
                    error_msg = "เซิร์ฟเวอร์ยังไม่ได้ติดตั้งไลบรารี PyNaCl/davey (โปรด Rebuild หรือ Redeploy บอทหลังอัปเดต requirements.txt)"
                elif "Did not connect" in error_msg:
                    error_msg = "การเชื่อมต่อห้องเสียงหมดเวลา (Timeout) ลองเรียกคำสั่งใหม่อีกครั้งนะ"
                embed = make_embed(
                    self.bot,
                    "Music",
                    title="❌ เชื่อมต่อล้มเหลว",
                    description=f"ไม่สามารถเชื่อมต่อห้องเสียงได้: {error_msg}",
                    color=EmbedColor.ERROR,
                )
                await interaction.followup.send(embed=embed)
                return

        query_str = query.strip()
        is_url = query_str.startswith("http://") or query_str.startswith("https://")
        added_tracks: List[Track] = []

        try:
            # 1. Check if it's a Spotify link
            spotify_tracks = await self.spotify.parse_url(query_str)
            if spotify_tracks is not None:
                for t in spotify_tracks:
                    added_tracks.append(
                        Track(
                            title=t["title"],
                            artist=t["artist"],
                            duration=t["duration"],
                            url=t["url"],
                            thumbnail=t["thumbnail"],
                            requester=interaction.user.display_name,
                            spotify_id=t["spotify_id"],
                        )
                    )
            # 2. Check if it's a YouTube Playlist link
            elif is_url and ("list=" in query_str or "/playlist?" in query_str):
                loop = asyncio.get_event_loop()
                yt_playlist = await loop.run_in_executor(None, self._extract_youtube_playlist, query_str)
                for t in yt_playlist:
                    added_tracks.append(
                        Track(
                            title=t["title"],
                            artist="",
                            duration=t["duration"],
                            url=t["url"],
                            thumbnail=t["thumbnail"],
                            requester=interaction.user.display_name,
                        )
                    )
            # 3. Simple Search Query or Single YouTube URL
            else:
                # Build an unresolved track. If queue is empty, we resolve it now to show correct title
                track = Track(
                    title=query_str,
                    artist="",
                    duration=0.0,
                    url=query_str if is_url else "",
                    requester=interaction.user.display_name,
                )
                if not state.current and not state.queue:
                    await state.resolve_track(track)
                added_tracks.append(track)

        except Exception as e:
            logger.exception("Error while queuing track(s)")
            embed = make_embed(
                self.bot,
                "Music",
                title="❌ เกิดข้อผิดพลาด",
                description=f"ไม่สามารถโหลดข้อมูลเพลงได้: {e}",
                color=EmbedColor.ERROR,
            )
            await interaction.followup.send(embed=embed)
            return

        if not added_tracks:
            embed = make_embed(
                self.bot,
                "Music",
                title="❌ ค้นหาล้มเหลว",
                description="ไม่พบเพลงที่คุณต้องการเล่น ลองพิมพ์หาใหม่อีกรอบนะ",
                color=EmbedColor.ERROR,
            )
            await interaction.followup.send(embed=embed)
            return

        # Queue songs
        state.queue.extend(added_tracks)
        state.start_player(interaction.channel)  # type: ignore

        # Send response confirmation
        if len(added_tracks) == 1:
            track = added_tracks[0]
            embed = make_embed(
                self.bot,
                "Music",
                title="✅ เพิ่มเข้าคิวแล้ว",
                description=f"**[{track.title}]({track.url or 'https://youtube.com'})**",
                color=EmbedColor.SUCCESS,
            )
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
            await interaction.followup.send(embed=embed)
        else:
            embed = make_embed(
                self.bot,
                "Music",
                title="✅ เพิ่มเข้าคิวสำเร็จ",
                description=f"เพิ่มเพลงทั้งหมด **{len(added_tracks)}** เพลงเข้าคิวเรียบร้อยครับ",
                color=EmbedColor.SUCCESS,
            )
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="pause", description="พักการเล่นเพลงชั่วคราว")
    async def pause(self, interaction: discord.Interaction) -> None:
        """Pause the voice client playback."""
        state = self.get_guild_state(interaction.guild_id or 0)
        if not state.voice_client or not state.voice_client.is_playing():
            await interaction.response.send_message("❌ บอทไม่ได้กำลังเล่นเพลงอยู่ครับ", ephemeral=True)
            return

        state.voice_client.pause()
        await interaction.response.send_message("⏸️ พักการเล่นเพลงชั่วคราวแล้วครับ")

    @app_commands.command(name="resume", description="เล่นเพลงต่อหลังจากที่พักไว้")
    async def resume(self, interaction: discord.Interaction) -> None:
        """Resume paused voice client playback."""
        state = self.get_guild_state(interaction.guild_id or 0)
        if not state.voice_client or not state.voice_client.is_paused():
            await interaction.response.send_message("❌ เพลงไม่ได้ถูกหยุดพักไว้ครับ", ephemeral=True)
            return

        state.voice_client.resume()
        await interaction.response.send_message("▶️ เล่นเพลงต่อเรียบร้อยครับ")

    @app_commands.command(name="skip", description="ข้ามเพลงที่กำลังเล่นอยู่ไปเพลงถัดไป")
    async def skip(self, interaction: discord.Interaction) -> None:
        """Skip the current playing track."""
        state = self.get_guild_state(interaction.guild_id or 0)
        if not state.voice_client or not state.voice_client.is_playing():
            await interaction.response.send_message("❌ บอทไม่ได้กำลังเล่นเพลงอยู่ครับ", ephemeral=True)
            return

        state.voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงปัจจุบันเรียบร้อยครับ")

    @app_commands.command(name="stop", description="หยุดการเล่นเพลง เคลียร์คิวทั้งหมด และออกจากห้องเสียง")
    async def stop(self, interaction: discord.Interaction) -> None:
        """Stop music, clear queue, disconnect."""
        state = self.get_guild_state(interaction.guild_id or 0)
        if not state.voice_client:
            await interaction.response.send_message("❌ บอทไม่ได้อยู่ในห้องเสียงครับ", ephemeral=True)
            return

        await state.stop()
        await interaction.response.send_message("👋 หยุดเล่น เคลียร์คิว และออกจากห้องเสียงเรียบร้อยครับ")

    @app_commands.command(name="nowplaying", description="แสดงรายละเอียดของเพลงที่กำลังเล่นอยู่")
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        """Show details of the current playing track."""
        state = self.get_guild_state(interaction.guild_id or 0)
        track = state.current
        if not track:
            await interaction.response.send_message("❌ ตอนนี้ไม่ได้เล่นเพลงอะไรอยู่ครับ", ephemeral=True)
            return

        embed = make_embed(
            self.bot,
            "Music",
            title="✨ เพลงที่กำลังเล่นอยู่ขณะนี้",
            description=f"**[{track.title}]({track.url})**\nขอโดย: {track.requester}",
            color=EmbedColor.INFO,
        )
        if track.artist:
            embed.add_field(name="ศิลปิน", value=track.artist, inline=True)
        if track.duration:
            m, s = divmod(int(track.duration), 60)
            embed.add_field(name="ความยาว", value=f"{m}:{s:02d}", inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        
        # Calculate current playtime progress if possible
        # discord.VoiceClient doesn't directly expose progress time, but this provides a clean info layout
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="queue", description="แสดงรายการเพลงทั้งหมดในคิวขณะนี้")
    async def queue_list(self, interaction: discord.Interaction) -> None:
        """Display the current tracks queued in the Guild."""
        state = self.get_guild_state(interaction.guild_id or 0)
        if not state.current and not state.queue:
            await interaction.response.send_message("📭 ตอนนี้ไม่มีเพลงอยู่ในคิวครับ", ephemeral=True)
            return

        description = ""
        if state.current:
            description += f"**เพลงปัจจุบันที่กำลังเล่น:**\n> 🎵 {state.current.title} (ขอโดย: {state.current.requester})\n\n"

        if state.queue:
            description += "**เพลงถัดไปในคิว:**\n"
            # Display first 10 tracks
            for idx, track in enumerate(state.queue[:10], start=1):
                description += f"{idx}. {track.title} (ขอโดย: {track.requester})\n"
            
            if len(state.queue) > 10:
                description += f"\n*และยังมีเพลงอื่นอีก {len(state.queue) - 10} เพลง*"
        else:
            description += "*ไม่มีเพลงถัดไปในคิว*"

        embed = make_embed(
            self.bot,
            "Music",
            title="📋 รายการเพลงในคิว",
            description=description,
            color=EmbedColor.INFO,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shuffle", description="สลับตำแหน่งคิวเพลงทั้งหมดแบบสุ่ม")
    async def shuffle(self, interaction: discord.Interaction) -> None:
        """Shuffle the current guild queue."""
        state = self.get_guild_state(interaction.guild_id or 0)
        if len(state.queue) < 2:
            await interaction.response.send_message("❌ มีเพลงในคิวไม่เพียงพอสำหรับการสลับตำแหน่งครับ (ต้องมีอย่างน้อย 2 เพลง)", ephemeral=True)
            return

        random.shuffle(state.queue)
        await interaction.response.send_message("🔀 สลับตำแหน่งคิวเพลงทั้งหมดเรียบร้อยแล้วครับ")


async def setup(bot: commands.Bot) -> None:
    """Setup hook to register the MusicCog."""
    await bot.add_cog(MusicCog(bot))
