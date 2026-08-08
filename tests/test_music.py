import base64
import os
import stat
import unittest
from unittest.mock import patch

from src.music.models import Track
from src.music.player import GuildPlayer
from src.music.sources import CookieFile, SpotifyResolver, YouTubeResolver


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self, post_responses=(), get_responses=()):
        self.post_responses = list(post_responses)
        self.get_responses = list(get_responses)
        self.post_calls = []
        self.get_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)


class MusicSourceTests(unittest.TestCase):
    def test_spotify_references_support_urls_and_uris(self):
        self.assertEqual(
            SpotifyResolver.parse_reference("https://open.spotify.com/track/abc123?si=x"),
            ("track", "abc123"),
        )
        self.assertEqual(
            SpotifyResolver.parse_reference("spotify:playlist:PL123"),
            ("playlist", "PL123"),
        )
        self.assertIsNone(SpotifyResolver.parse_reference("https://youtube.com/watch?v=abc"))

    def test_youtube_metadata_becomes_a_queue_track(self):
        track = YouTubeResolver._track_from_info(
            {
                "id": "video123",
                "title": "Example Song",
                "channel": "Example Artist",
                "duration": 125,
            },
            "tester",
        )

        self.assertIsNotNone(track)
        self.assertEqual(track.source, "youtube")
        self.assertEqual(track.playback_query, "https://www.youtube.com/watch?v=video123")
        self.assertEqual(track.display_name, "Example Song — Example Artist")

    def test_cookie_file_is_private_and_removed(self):
        contents = b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n"
        cookie_file = CookieFile(None, base64.b64encode(contents).decode("ascii"))
        path = cookie_file.get()

        self.assertIsNotNone(path)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), contents)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

        cookie_file.close()
        self.assertFalse(os.path.exists(path))


class SpotifyResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_playlist_uses_current_items_endpoint_and_shape(self):
        http = FakeHttpClient(
            post_responses=[FakeResponse(200, {"access_token": "token", "expires_in": 3600})],
            get_responses=[
                FakeResponse(
                    200,
                    {
                        "items": [
                            {
                                "item": {
                                    "id": "track1",
                                    "type": "track",
                                    "name": "New Song",
                                    "artists": [{"name": "New Artist"}],
                                    "duration_ms": 180000,
                                    "external_urls": {
                                        "spotify": "https://open.spotify.com/track/track1"
                                    },
                                }
                            }
                        ],
                        "next": None,
                    },
                )
            ],
        )
        resolver = SpotifyResolver(http, "client", "secret")

        tracks = await resolver.resolve(("playlist", "playlist1"), "tester")

        self.assertEqual(http.get_calls[0][0], "https://api.spotify.com/v1/playlists/playlist1/items")
        self.assertTrue(http.post_calls[0][1]["headers"]["Authorization"].startswith("Basic "))
        self.assertEqual(tracks[0].display_name, "New Song — New Artist")
        self.assertEqual(tracks[0].playback_query, "New Song New Artist official audio")
        self.assertEqual(tracks[0].duration, 180)


class FakeSources:
    def __init__(self):
        self.requests = []

    async def stream_url(self, track):
        self.requests.append(track)
        return "https://audio.example/stream"


class FakeTextChannel:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, *, embed=None):
        self.messages.append((content, embed))


class FakeVoice:
    def __init__(self):
        self.connected = True
        self.playing = False
        self.paused = False

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.playing

    def is_paused(self):
        return self.paused

    def play(self, source, *, after):
        self.playing = True
        import asyncio

        asyncio.get_running_loop().call_soon(after, None)
        self.playing = False

    def stop(self):
        self.playing = False
        self.paused = False

    async def disconnect(self, *, force=False):
        self.connected = False


class FakeBot:
    user = None


class GuildPlayerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_resolves_plays_and_disconnects_when_idle(self):
        import asyncio

        sources = FakeSources()
        voice = FakeVoice()
        channel = FakeTextChannel()
        player = GuildPlayer(FakeBot(), 123, sources, idle_timeout=0.01)
        player.attach(voice, channel)
        track = Track(
            title="Song",
            artists="Artist",
            webpage_url="https://youtube.com/watch?v=1",
            playback_query="https://youtube.com/watch?v=1",
            source="youtube",
            requester="tester",
        )

        with (
            patch("src.music.player.discord.FFmpegPCMAudio", return_value=object()),
            patch("src.music.player.discord.PCMVolumeTransformer", return_value=object()),
        ):
            player.enqueue([track])
            for _ in range(20):
                if not voice.connected:
                    break
                await asyncio.sleep(0.01)

        self.assertEqual(sources.requests, [track])
        self.assertFalse(voice.connected)
        self.assertTrue(any(embed is not None for _, embed in channel.messages))


if __name__ == "__main__":
    unittest.main()
