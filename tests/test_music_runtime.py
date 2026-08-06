import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from src.cogs.music import (
    GuildMusicState,
    MusicCog,
    Track,
    YOUTUBE_AUDIO_CLIENTS,
    YTDL_OPTIONS,
    _extract_youtube_info,
    music_states,
    text_permission_problem,
    voice_permission_problem,
)


class MusicRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_audio_extraction_prefers_hls_and_token_free_clients(self):
        with patch("src.cogs.music.yt_dlp.YoutubeDL") as youtube_dl:
            extractor = youtube_dl.return_value.__enter__.return_value
            extractor.extract_info.return_value = {
                "id": "video-id",
                "title": "Song",
                "url": "https://example.com/audio.m3u8",
            }

            result = _extract_youtube_info(
                "https://www.youtube.com/watch?v=video-id",
                flat=False,
            )

        options = youtube_dl.call_args.args[0]
        self.assertTrue(options["format"].startswith("bestaudio[protocol^=m3u8]"))
        self.assertEqual(
            options["extractor_args"]["youtube"]["player_client"],
            list(YOUTUBE_AUDIO_CLIENTS),
        )
        self.assertEqual(result["title"], "Song")

    def test_flat_search_does_not_force_audio_clients(self):
        with patch("src.cogs.music.yt_dlp.YoutubeDL") as youtube_dl:
            extractor = youtube_dl.return_value.__enter__.return_value
            extractor.extract_info.return_value = {
                "entries": [{"id": "video-id", "title": "Song"}]
            }

            _extract_youtube_info("ytsearch1:Song", flat=True)

        options = youtube_dl.call_args.args[0]
        self.assertEqual(options["extract_flat"], "in_playlist")
        self.assertNotIn("extractor_args", options)
        self.assertIn("js_runtimes", YTDL_OPTIONS)

    def test_voice_permissions_report_missing_capabilities(self):
        interaction = MagicMock()
        interaction.guild.me = MagicMock()
        interaction.user.voice.channel.permissions_for.return_value = discord.Permissions(
            view_channel=True,
            connect=False,
            speak=False,
        )

        problem = voice_permission_problem(interaction)

        self.assertIn("Connect", problem)
        self.assertIn("Speak", problem)

    def test_text_permissions_report_missing_capabilities(self):
        interaction = MagicMock()
        interaction.app_permissions = discord.Permissions(
            view_channel=True,
            send_messages=False,
            embed_links=False,
        )

        problem = text_permission_problem(interaction)

        self.assertIn("Send Messages", problem)
        self.assertIn("Embed Links", problem)
        self.assertNotIn("View Channel,", problem)

    async def test_play_reports_voice_timeout_instead_of_generic_error(self):
        bot = MagicMock()
        bot.external_http = MagicMock()
        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.app_permissions = discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )
        interaction.guild.id = 9876
        interaction.guild.voice_client = None
        interaction.guild.me = MagicMock()
        voice_channel = interaction.user.voice.channel
        voice_channel.permissions_for.return_value = discord.Permissions(
            view_channel=True,
            connect=True,
            speak=True,
        )
        voice_channel.connect = AsyncMock(side_effect=TimeoutError)
        track = Track(
            title="Song",
            youtube_url="https://youtube.com/watch?v=1",
            requester=interaction.user,
            requested_via="YouTube",
        )

        try:
            with (
                patch("src.cogs.music.FFMPEG_EXECUTABLE", "/usr/bin/ffmpeg"),
                patch("src.cogs.music.discord.opus.is_loaded", return_value=True),
                patch("src.cogs.music.resolve_tracks", AsyncMock(return_value=[track])),
            ):
                await MusicCog.play.callback(MusicCog(bot), interaction, "Song")
        finally:
            music_states.pop(9876, None)

        voice_channel.connect.assert_awaited_once_with(
            timeout=20.0,
            reconnect=True,
            self_deaf=True,
        )
        sent_message = interaction.followup.send.await_args.args[0]
        self.assertIn("20 วินาที", sent_message)

    async def test_playback_error_is_reported_and_not_looped_forever(self):
        bot = MagicMock()
        bot.user.display_avatar.url = "https://example.com/avatar.png"
        state = GuildMusicState(bot, 1)
        state.loop_mode = "track"
        state.current = Track(
            title="Song",
            youtube_url="https://youtube.com/watch?v=1",
            requester=MagicMock(),
            requested_via="YouTube",
        )
        state.text_channel = MagicMock()
        state.text_channel.send = AsyncMock()
        state.play_next = AsyncMock()

        await state._continue_after_track(RuntimeError("stream failed"))

        self.assertEqual(len(state.queue), 0)
        state.text_channel.send.assert_awaited_once()
        state.play_next.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
