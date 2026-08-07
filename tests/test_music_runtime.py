import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from src.cogs.music import (
    GuildMusicState,
    MusicCog,
    MusicError,
    SpotifyTrackMetadata,
    Track,
    YOUTUBE_AUDIO_CLIENTS,
    YTDL_OPTIONS,
    _extract_youtube_info,
    _resolve_spotify_playlist,
    _resolve_single_youtube,
    _resolve_youtube_playlist,
    music_states,
    playback_error_message,
    playback_queries,
    resolve_tracks,
    text_permission_problem,
    voice_permission_problem,
)


class MusicRuntimeTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def async_response(payload, *, status=200):
        response = MagicMock()
        response.status = status
        response.json = AsyncMock(return_value=payload)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=None)
        return context

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

    def test_ytdl_proxy_option_matches_environment_configuration(self):
        from src.cogs.music import YOUTUBE_PROXY

        if YOUTUBE_PROXY and YOUTUBE_PROXY.strip():
            self.assertEqual(YTDL_OPTIONS["proxy"], YOUTUBE_PROXY.strip())
        else:
            self.assertNotIn("proxy", YTDL_OPTIONS)

    async def test_youtube_playlist_expands_entries_and_is_bounded(self):
        with patch("src.cogs.music.yt_dlp.YoutubeDL") as youtube_dl:
            youtube_dl.return_value.extract_info.return_value = {
                "entries": [
                    {"id": "first", "title": "First song"},
                    {"id": "second", "title": "Second song"},
                ]
            }

            tracks = await _resolve_youtube_playlist(
                "https://www.youtube.com/playlist?list=PL123",
                MagicMock(),
            )

        options = youtube_dl.call_args.args[0]
        self.assertFalse(options["noplaylist"])
        self.assertEqual(options["playlistend"], 200)
        self.assertEqual(len(tracks), 2)
        self.assertEqual(
            tracks[0].youtube_url,
            "https://www.youtube.com/watch?v=first",
        )

    async def test_spotify_playlist_uses_basic_auth_and_follows_pages(self):
        http_client = MagicMock()
        http_client.post.return_value = self.async_response(
            {"access_token": "access-token"}
        )
        http_client.get.side_effect = [
            self.async_response(
                {
                    "items": [
                        {
                            "item": {
                                "name": "First song",
                                "artists": [{"name": "First artist"}],
                                "external_urls": {
                                    "spotify": "https://open.spotify.com/track/first"
                                },
                                "is_local": False,
                            }
                        }
                    ],
                    "next": "https://api.spotify.com/v1/playlists/id/items?offset=50",
                }
            ),
            self.async_response(
                {
                    "items": [
                        {
                            "item": {
                                "name": "Second song",
                                "artists": [{"name": "Second artist"}],
                                "external_urls": {
                                    "spotify": "https://open.spotify.com/track/second"
                                },
                                "is_local": False,
                            }
                        },
                        {"item": {"name": "Local song", "is_local": True}},
                    ],
                    "next": None,
                }
            ),
        ]

        with (
            patch("src.cogs.music.SPOTIFY_CLIENT_ID", "client-id"),
            patch("src.cogs.music.SPOTIFY_CLIENT_SECRET", "client-secret"),
        ):
            tracks = await _resolve_spotify_playlist(
                "playlist123",
                MagicMock(),
                http_client,
            )

        token_kwargs = http_client.post.call_args.kwargs
        self.assertEqual(token_kwargs["data"], {"grant_type": "client_credentials"})
        self.assertEqual(
            token_kwargs["headers"]["Authorization"],
            "Basic Y2xpZW50LWlkOmNsaWVudC1zZWNyZXQ=",
        )
        self.assertEqual(http_client.get.call_count, 2)
        self.assertTrue(http_client.get.call_args_list[0].args[0].endswith("/items"))
        self.assertEqual(http_client.get.call_args_list[0].kwargs["params"]["limit"], 50)
        self.assertIsNone(http_client.get.call_args_list[1].kwargs["params"])
        self.assertEqual(len(tracks), 2)
        self.assertEqual(
            tracks[0].display_url,
            "https://open.spotify.com/track/first",
        )

    async def test_spotify_track_keeps_provider_and_uses_two_youtube_searches(self):
        metadata = SpotifyTrackMetadata(
            title="Spotify Song",
            artist="Spotify Artist",
            canonical_url="https://open.spotify.com/track/abc",
        )
        youtube_result = {
            "id": "video-id",
            "title": "YouTube title",
            "extractor_key": "Youtube",
        }

        with (
            patch(
                "src.cogs.music._spotify_track_metadata",
                AsyncMock(return_value=metadata),
            ),
            patch(
                "src.cogs.music._resolve_single_youtube",
                AsyncMock(return_value=youtube_result),
            ) as youtube_resolver,
        ):
            tracks = await resolve_tracks(
                "https://open.spotify.com/track/abc",
                MagicMock(),
                MagicMock(),
            )

        track = tracks[0]
        self.assertEqual(track.title, "Spotify Song — Spotify Artist")
        self.assertEqual(track.display_url, "https://open.spotify.com/track/abc")
        self.assertEqual(track.requested_via, "Spotify → YouTube")
        queries = youtube_resolver.await_args.args[0]
        self.assertEqual(len(queries), 2)
        self.assertTrue(queries[0].endswith("official audio"))
        self.assertNotIn("official audio", queries[1])
        self.assertTrue(youtube_resolver.await_args.kwargs["spotify_source"])

    async def test_spotify_youtube_resolution_failure_has_provider_context(self):
        with patch(
            "src.cogs.music._extract_youtube_info",
            side_effect=RuntimeError("youtube unavailable"),
        ):
            with self.assertRaises(MusicError) as raised:
                await _resolve_single_youtube(
                    ("ytsearch1:Song official audio", "ytsearch1:Song"),
                    spotify_source=True,
                )

        self.assertIn("อ่านข้อมูลเพลงจาก Spotify ได้แล้ว", str(raised.exception))
        self.assertIn("ส่วนเสียงจะเล่นผ่าน YouTube", str(raised.exception))

    def test_spotify_playlist_audio_has_broader_fallback(self):
        track = Track(
            title="Song",
            youtube_url="ytsearch1:Song Artist official audio",
            requester=MagicMock(),
            requested_via="Spotify Playlist",
        )

        queries = playback_queries(track)

        self.assertEqual(
            queries,
            (
                "ytsearch1:Song Artist official audio",
                "ytsearch1:Song Artist",
            ),
        )
        self.assertIn("Spotify", playback_error_message(track, MusicError("failed")))
        self.assertIn("YouTube", playback_error_message(track, MusicError("failed")))

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
