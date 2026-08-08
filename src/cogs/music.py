"""Slash commands for Spotify and YouTube music playback."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import config
from ..music import GuildPlayer, MusicSourceResolver, SourceError
from ..ui import EmbedColor, make_embed


logger = logging.getLogger("discord.javis.music")
MAX_GUILD_QUEUE_SIZE = 100


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sources = MusicSourceResolver(
            bot.external_http,
            spotify_client_id=config.SPOTIFY_CLIENT_ID,
            spotify_client_secret=config.SPOTIFY_CLIENT_SECRET,
            youtube_cookies_file=config.YOUTUBE_COOKIES_FILE,
            youtube_cookies_base64=config.YOUTUBE_COOKIES_BASE64,
        )
        self.players: dict[int, GuildPlayer] = {}

    def _embed(
        self,
        title: str,
        description: str,
        color: EmbedColor = EmbedColor.INFO,
    ) -> discord.Embed:
        return make_embed(
            self.bot,
            "Music",
            title=title,
            description=description,
            color=color,
        )

    def cog_unload(self) -> None:
        self.sources.close()
        for player in self.players.values():
            asyncio.create_task(player.disconnect())

    def _player(self, guild_id: int) -> GuildPlayer:
        player = self.players.get(guild_id)
        if player is None:
            player = GuildPlayer(self.bot, guild_id, self.sources)
            self.players[guild_id] = player
        return player

    @staticmethod
    def _user_voice_channel(interaction: discord.Interaction):
        voice_state = getattr(interaction.user, "voice", None)
        return voice_state.channel if voice_state else None

    async def _require_same_voice(
        self,
        interaction: discord.Interaction,
        player: GuildPlayer,
    ) -> bool:
        user_channel = self._user_voice_channel(interaction)
        bot_channel = player.voice.channel if player.voice else None
        if user_channel and bot_channel and user_channel.id == bot_channel.id:
            return True
        await interaction.response.send_message(
            embed=self._embed(
                "🎧 ต้องอยู่ห้องเดียวกัน",
                "เข้าห้องเสียงเดียวกับบอทก่อนใช้คำสั่งควบคุมเพลง",
                EmbedColor.WARNING,
            ),
            ephemeral=True,
        )
        return False

    async def _connect(
        self,
        interaction: discord.Interaction,
        player: GuildPlayer,
        channel,
    ) -> discord.VoiceClient:
        existing_voice = player.voice or interaction.guild.voice_client
        if existing_voice and existing_voice.is_connected():
            if existing_voice.channel.id != channel.id:
                raise SourceError("บอทกำลังเล่นเพลงอยู่ในห้องเสียงอื่น")
            return existing_voice
        if existing_voice:
            try:
                await existing_voice.disconnect(force=True)
            except discord.DiscordException:
                logger.warning("Could not clean up stale voice connection in guild %s", interaction.guild_id)

        permissions = channel.permissions_for(interaction.guild.me)
        missing = []
        if not permissions.connect:
            missing.append("Connect")
        if not permissions.speak:
            missing.append("Speak")
        if missing:
            raise SourceError(f"บอทขาดสิทธิ์ในห้องเสียง: {', '.join(missing)}")

        try:
            return await channel.connect(timeout=30, reconnect=True, self_deaf=True)
        except asyncio.TimeoutError as exc:
            raise SourceError("เชื่อมต่อห้องเสียงหมดเวลา กรุณาลองใหม่") from exc
        except (discord.ClientException, discord.DiscordException) as exc:
            raise SourceError(f"เชื่อมต่อห้องเสียงไม่สำเร็จ: {exc}") from exc

    @app_commands.command(name="play", description="เล่นเพลงจาก YouTube หรือ Spotify")
    @app_commands.describe(query="ชื่อเพลง, YouTube URL หรือ Spotify track/album/playlist URL")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(3, 10, key=lambda interaction: interaction.user.id)
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        channel = self._user_voice_channel(interaction)
        if not channel:
            await interaction.response.send_message(
                embed=self._embed(
                    "🎧 ยังไม่ได้เข้าห้องเสียง",
                    "เข้าห้องเสียงที่ต้องการให้บอทเล่นเพลง แล้วเรียก `/play` อีกครั้ง",
                    EmbedColor.WARNING,
                ),
                ephemeral=True,
            )
            return
        if not interaction.guild or not interaction.channel:
            await interaction.response.send_message(
                embed=self._embed(
                    "❌ ใช้คำสั่งไม่ได้",
                    "คำสั่งเพลงใช้งานได้เฉพาะภายในเซิร์ฟเวอร์ Discord",
                    EmbedColor.ERROR,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        player = self._player(interaction.guild.id)
        try:
            remaining = MAX_GUILD_QUEUE_SIZE - len(player.queue) - (1 if player.current else 0)
            if remaining <= 0:
                raise SourceError("คิวเต็มแล้ว กรุณารอหรือใช้ `/stop`")
            tracks = await self.sources.resolve(query, interaction.user.display_name)
            tracks = tracks[:remaining]
            if not tracks:
                raise SourceError("ไม่พบเพลงที่รองรับ")
            voice = await self._connect(interaction, player, channel)
            player.attach(voice, interaction.channel)
            player.enqueue(tracks)
        except SourceError as exc:
            await interaction.followup.send(
                embed=self._embed("❌ โหลดเพลงไม่สำเร็จ", str(exc), EmbedColor.ERROR),
                ephemeral=True,
            )
            return
        except Exception:
            logger.exception("Unexpected /play failure")
            await interaction.followup.send(
                embed=self._embed(
                    "❌ โหลดเพลงไม่สำเร็จ",
                    "เกิดข้อผิดพลาดที่ไม่คาดคิด กรุณารอสักครู่แล้วลองใหม่",
                    EmbedColor.ERROR,
                ),
                ephemeral=True,
            )
            return

        first = tracks[0]
        if len(tracks) == 1:
            description = f"**[{first.display_name}]({first.webpage_url})**"
        else:
            description = (
                f"เพิ่ม **{len(tracks)} เพลง** เข้าคิวแล้ว\n"
                f"เพลงแรก: **[{first.display_name}]({first.webpage_url})**"
            )
        embed = self._embed("✅ เพิ่มเข้าคิวแล้ว", description, EmbedColor.SUCCESS)
        embed.add_field(name="ลิงก์ต้นทาง", value=first.source.title(), inline=True)
        embed.add_field(name="เพลงที่รอ", value=str(len(player.queue)), inline=True)
        if first.source == "spotify":
            embed.add_field(
                name="การเล่นเสียง",
                value="จับคู่ Spotify metadata ผ่าน YouTube",
                inline=False,
            )
        if first.thumbnail:
            embed.set_thumbnail(url=first.thumbnail)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="pause", description="พักเพลงที่กำลังเล่น")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not await self._require_same_voice(interaction, player):
            return
        paused = player.pause()
        embed = self._embed(
            "⏸️ พักเพลงแล้ว" if paused else "⚠️ ไม่มีเพลงให้พัก",
            "ใช้ `/resume` เมื่อต้องการเล่นต่อ" if paused else "ตอนนี้ไม่มีเพลงที่กำลังเล่น",
            EmbedColor.INFO if paused else EmbedColor.WARNING,
        )
        await interaction.response.send_message(embed=embed, ephemeral=not paused)

    @app_commands.command(name="resume", description="เล่นเพลงที่พักไว้ต่อ")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not await self._require_same_voice(interaction, player):
            return
        resumed = player.resume()
        embed = self._embed(
            "▶️ เล่นเพลงต่อแล้ว" if resumed else "⚠️ เล่นต่อไม่ได้",
            "กลับมาเล่นเพลงปัจจุบันเรียบร้อย" if resumed else "เพลงไม่ได้อยู่ในสถานะพัก",
            EmbedColor.SUCCESS if resumed else EmbedColor.WARNING,
        )
        await interaction.response.send_message(embed=embed, ephemeral=not resumed)

    @app_commands.command(name="skip", description="ข้ามไปเพลงถัดไป")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not await self._require_same_voice(interaction, player):
            return
        skipped = player.skip()
        embed = self._embed(
            "⏭️ ข้ามเพลงแล้ว" if skipped else "⚠️ ไม่มีเพลงให้ข้าม",
            "กำลังเตรียมเพลงถัดไปในคิว" if skipped else "ตอนนี้ไม่มีเพลงที่กำลังเล่น",
            EmbedColor.INFO if skipped else EmbedColor.WARNING,
        )
        await interaction.response.send_message(embed=embed, ephemeral=not skipped)

    @app_commands.command(name="stop", description="หยุดเพลง ล้างคิว และออกจากห้องเสียง")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not await self._require_same_voice(interaction, player):
            return
        await player.stop()
        await interaction.response.send_message(
            embed=self._embed(
                "⏹️ หยุดเล่นเพลงแล้ว",
                "ล้างคิวและออกจากห้องเสียงเรียบร้อย",
                EmbedColor.SUCCESS,
            )
        )

    @app_commands.command(name="queue", description="ดูเพลงปัจจุบันและรายการเพลงถัดไป")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not player.current and not player.queue:
            await interaction.response.send_message(
                embed=self._embed(
                    "📭 คิวเพลงว่าง",
                    "ใช้ `/play` เพื่อเพิ่มเพลงจาก YouTube หรือ Spotify",
                    EmbedColor.INFO,
                ),
                ephemeral=True,
            )
            return

        lines = []
        if player.current:
            lines.append(f"**กำลังเล่น**\n[🎵 {player.current.display_name}]({player.current.webpage_url})")
        if player.queue:
            lines.append("\n**เพลงถัดไป**")
            lines.extend(
                f"{index}. [{track.display_name}]({track.webpage_url}) — {track.requester}"
                for index, track in enumerate(list(player.queue)[:10], start=1)
            )
            if len(player.queue) > 10:
                lines.append(f"…และอีก {len(player.queue) - 10} เพลง")
        embed = make_embed(
            self.bot,
            "Music",
            title="📋 คิวเพลง",
            description="\n".join(lines),
            color=EmbedColor.INFO,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="nowplaying", description="ดูเพลงที่กำลังเล่น")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        track = self._player(interaction.guild_id or 0).current
        if not track:
            await interaction.response.send_message(
                embed=self._embed(
                    "🎵 ยังไม่มีเพลงที่กำลังเล่น",
                    "ใช้ `/play` เพื่อเริ่มเล่นเพลง",
                    EmbedColor.INFO,
                ),
                ephemeral=True,
            )
            return
        embed = make_embed(
            self.bot,
            "Music",
            title="🎵 กำลังเล่น",
            description=f"**[{track.display_name}]({track.webpage_url})**\nขอโดย: {track.requester}",
            color=EmbedColor.PRIMARY,
        )
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        if track.duration:
            minutes, seconds = divmod(int(track.duration), 60)
            embed.add_field(name="ความยาว", value=f"{minutes}:{seconds:02d}", inline=True)
        embed.add_field(name="ลิงก์ต้นทาง", value=track.source.title(), inline=True)
        embed.add_field(name="แหล่งเสียง", value="YouTube", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shuffle", description="สุ่มลำดับเพลงที่รอในคิว")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not await self._require_same_voice(interaction, player):
            return
        shuffled = player.shuffle()
        embed = self._embed(
            "🔀 สุ่มคิวเรียบร้อย" if shuffled else "⚠️ สุ่มคิวไม่ได้",
            f"จัดลำดับเพลงที่รอใหม่แล้วทั้งหมด {len(player.queue)} เพลง"
            if shuffled
            else "ต้องมีเพลงรอในคิวอย่างน้อย 2 เพลง",
            EmbedColor.SUCCESS if shuffled else EmbedColor.WARNING,
        )
        await interaction.response.send_message(embed=embed, ephemeral=not shuffled)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))
