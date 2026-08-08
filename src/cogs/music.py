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
            "คุณต้องอยู่ในห้องเสียงเดียวกับบอทก่อนใช้คำสั่งนี้",
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
            await interaction.response.send_message("เข้าห้องเสียงก่อนใช้ `/play`", ephemeral=True)
            return
        if not interaction.guild or not interaction.channel:
            await interaction.response.send_message("คำสั่งนี้ใช้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)
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
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        except Exception:
            logger.exception("Unexpected /play failure")
            await interaction.followup.send("❌ โหลดเพลงไม่สำเร็จ กรุณาลองใหม่", ephemeral=True)
            return

        first = tracks[0]
        if len(tracks) == 1:
            message = f"✅ เพิ่ม **[{first.display_name}]({first.webpage_url})** เข้าคิวแล้ว"
        else:
            message = f"✅ เพิ่ม **{len(tracks)} เพลง** เข้าคิวแล้ว เริ่มจาก **{first.display_name}**"
        await interaction.followup.send(message)

    @app_commands.command(name="pause", description="พักเพลงที่กำลังเล่น")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not await self._require_same_voice(interaction, player):
            return
        message = "⏸️ พักเพลงแล้ว" if player.pause() else "ตอนนี้ไม่มีเพลงที่กำลังเล่น"
        await interaction.response.send_message(message, ephemeral=not player.voice)

    @app_commands.command(name="resume", description="เล่นเพลงที่พักไว้ต่อ")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not await self._require_same_voice(interaction, player):
            return
        message = "▶️ เล่นเพลงต่อแล้ว" if player.resume() else "เพลงไม่ได้อยู่ในสถานะพัก"
        await interaction.response.send_message(message)

    @app_commands.command(name="skip", description="ข้ามไปเพลงถัดไป")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not await self._require_same_voice(interaction, player):
            return
        message = "⏭️ ข้ามเพลงแล้ว" if player.skip() else "ตอนนี้ไม่มีเพลงที่กำลังเล่น"
        await interaction.response.send_message(message)

    @app_commands.command(name="stop", description="หยุดเพลง ล้างคิว และออกจากห้องเสียง")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not await self._require_same_voice(interaction, player):
            return
        await player.stop()
        await interaction.response.send_message("⏹️ หยุดเพลง ล้างคิว และออกจากห้องแล้ว")

    @app_commands.command(name="queue", description="ดูเพลงปัจจุบันและรายการเพลงถัดไป")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not player.current and not player.queue:
            await interaction.response.send_message("📭 คิวเพลงว่าง", ephemeral=True)
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
            await interaction.response.send_message("ตอนนี้ไม่มีเพลงที่กำลังเล่น", ephemeral=True)
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
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shuffle", description="สุ่มลำดับเพลงที่รอในคิว")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id or 0)
        if not await self._require_same_voice(interaction, player):
            return
        message = "🔀 สุ่มคิวเรียบร้อย" if player.shuffle() else "ต้องมีเพลงรออย่างน้อย 2 เพลง"
        await interaction.response.send_message(message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))
