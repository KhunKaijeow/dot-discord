"""Resolve Spotify metadata and playable YouTube audio streams."""

from __future__ import annotations

import atexit
import base64
from itertools import islice
import logging
import os
import re
import tempfile
import time
from typing import Any

import yt_dlp

from ..services.http_client import HttpClient
from .models import Track


logger = logging.getLogger("discord.javis.music.sources")

MAX_TRACKS_PER_REQUEST = 100
SPOTIFY_URL_PATTERN = re.compile(
    r"(?:https?://open\.spotify\.com/(?:intl-[a-z-]+/)?|spotify:)"
    r"(?P<kind>track|album|playlist)[/:](?P<id>[A-Za-z0-9]+)",
    re.IGNORECASE,
)


class SourceError(RuntimeError):
    """A safe, user-facing error raised while resolving a music source."""


class YouTubeAuthenticationError(SourceError):
    """YouTube challenged the deployment IP and requires cookies."""


class CookieFile:
    """Materialize optional Base64 cookies as a private temporary file."""

    def __init__(self, path: str | None, encoded: str | None) -> None:
        self._configured_path = path
        self._encoded = encoded
        self._temporary_path: str | None = None

    def get(self) -> str | None:
        if self._configured_path:
            if os.path.isfile(self._configured_path):
                return self._configured_path
            raise SourceError("YOUTUBE_COOKIES_FILE ไม่ใช่ไฟล์ที่อ่านได้")

        if not self._encoded:
            return None
        if self._temporary_path and os.path.isfile(self._temporary_path):
            return self._temporary_path

        try:
            compact_value = "".join(self._encoded.split())
            cookie_data = base64.b64decode(compact_value, validate=True)
            if not cookie_data or len(cookie_data) > 2 * 1024 * 1024:
                raise ValueError("cookie data is empty or too large")
            if b"Netscape HTTP Cookie File" not in cookie_data[:256]:
                raise ValueError("cookies must use Netscape format")

            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix="javis-youtube-cookies-",
                suffix=".txt",
                delete=False,
            ) as cookie_file:
                cookie_file.write(cookie_data)
                self._temporary_path = cookie_file.name
            atexit.register(self.close)
            os.chmod(self._temporary_path, 0o600)
            return self._temporary_path
        except (ValueError, OSError) as exc:
            self.close()
            raise SourceError(f"YOUTUBE_COOKIES_BASE64 ไม่ถูกต้อง: {exc}") from exc

    def close(self) -> None:
        path = self._temporary_path
        self._temporary_path = None
        if not path:
            return
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Could not remove temporary YouTube cookie file")


class YouTubeResolver:
    """Use yt-dlp for YouTube search, playlist metadata, and fresh streams."""

    def __init__(self, cookie_file: CookieFile) -> None:
        self.cookie_file = cookie_file

    def _options(self, **overrides: Any) -> dict[str, Any]:
        options: dict[str, Any] = {
            "format": "bestaudio[acodec!=none]/bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 20,
            "retries": 2,
            "source_address": "0.0.0.0",
        }
        cookie_path = self.cookie_file.get()
        if cookie_path:
            options["cookiefile"] = cookie_path
        options.update(overrides)
        return options

    async def resolve(self, query: str, requester: str) -> list[Track]:
        import asyncio

        return await asyncio.to_thread(self._resolve_sync, query, requester)

    def _resolve_sync(self, query: str, requester: str) -> list[Track]:
        is_url = query.startswith(("http://", "https://"))
        is_playlist = is_url and ("list=" in query or "/playlist" in query)
        target = query if is_url else f"ytsearch1:{query}"
        options = self._options(
            noplaylist=not is_playlist,
            extract_flat="in_playlist" if is_playlist else False,
            ignoreerrors=True,
            playlistend=MAX_TRACKS_PER_REQUEST,
        )

        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                result = ydl.extract_info(target, download=False)
        except Exception as exc:
            self._raise_safe_error(exc)

        if not result:
            raise SourceError("ไม่พบเพลงจาก YouTube")

        entries = result.get("entries") if isinstance(result, dict) else None
        raw_tracks = islice(entries, MAX_TRACKS_PER_REQUEST) if entries is not None else [result]
        tracks = [
            track
            for item in raw_tracks
            if item and (track := self._track_from_info(item, requester))
        ]
        if not tracks:
            raise SourceError("ไม่พบเพลงที่เล่นได้จาก YouTube")
        return tracks

    @staticmethod
    def _track_from_info(info: dict[str, Any], requester: str) -> Track | None:
        title = str(info.get("title") or "").strip()
        if not title:
            return None
        webpage_url = str(info.get("webpage_url") or "").strip()
        if not webpage_url:
            video_id = str(info.get("id") or "").strip()
            raw_url = str(info.get("url") or "").strip()
            webpage_url = (
                raw_url
                if raw_url.startswith(("http://", "https://"))
                else f"https://www.youtube.com/watch?v={video_id or raw_url}"
            )
        return Track(
            title=title,
            artists=str(info.get("uploader") or info.get("channel") or "").strip(),
            webpage_url=webpage_url,
            playback_query=webpage_url,
            source="youtube",
            requester=requester,
            duration=float(info.get("duration") or 0),
            thumbnail=info.get("thumbnail"),
        )

    async def stream_url(self, track: Track) -> str:
        import asyncio

        return await asyncio.to_thread(self._stream_url_sync, track.playback_query)

    def _stream_url_sync(self, query: str) -> str:
        target = query if query.startswith(("http://", "https://")) else f"ytsearch1:{query}"
        try:
            with yt_dlp.YoutubeDL(self._options()) as ydl:
                info = ydl.extract_info(target, download=False)
        except Exception as exc:
            self._raise_safe_error(exc)

        if isinstance(info, dict) and info.get("entries") is not None:
            info = next((entry for entry in info["entries"] if entry), None)
        stream_url = info.get("url") if isinstance(info, dict) else None
        if not stream_url:
            raise SourceError("YouTube ไม่ส่ง audio stream สำหรับเพลงนี้")
        return str(stream_url)

    @staticmethod
    def _raise_safe_error(exc: Exception) -> None:
        message = str(exc)
        if "Sign in to confirm" in message or "not a bot" in message:
            raise YouTubeAuthenticationError(
                "YouTube ขอการยืนยันตัวตน กรุณาตั้งค่า YOUTUBE_COOKIES_BASE64"
            ) from exc
        if "Private video" in message or "Video unavailable" in message:
            raise SourceError("วิดีโอนี้เป็นส่วนตัวหรือไม่พร้อมให้เล่น") from exc
        logger.warning("yt-dlp failed: %s", message)
        raise SourceError("ดึงข้อมูลเพลงจาก YouTube ไม่สำเร็จ") from exc


class SpotifyResolver:
    """Resolve Spotify track, album, and playlist metadata with Web API v1."""

    def __init__(self, http_client: HttpClient, client_id: str | None, client_secret: str | None) -> None:
        self.http_client = http_client
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: str | None = None
        self._expires_at = 0.0

    @staticmethod
    def parse_reference(value: str) -> tuple[str, str] | None:
        match = SPOTIFY_URL_PATTERN.search(value.strip())
        if not match:
            return None
        return match.group("kind").lower(), match.group("id")

    async def resolve(self, reference: tuple[str, str], requester: str) -> list[Track]:
        if not self.client_id or not self.client_secret:
            raise SourceError("ยังไม่ได้ตั้งค่า SPOTIFY_CLIENT_ID และ SPOTIFY_CLIENT_SECRET")
        kind, spotify_id = reference
        if kind == "track":
            data = await self._get_json(f"https://api.spotify.com/v1/tracks/{spotify_id}")
            track = self._track_from_item(data, requester)
            return [track] if track else []
        if kind == "album":
            album = await self._get_json(f"https://api.spotify.com/v1/albums/{spotify_id}")
            images = album.get("images") or []
            thumbnail = images[0].get("url") if images and isinstance(images[0], dict) else None
            return await self._paged_tracks(
                f"https://api.spotify.com/v1/albums/{spotify_id}/tracks",
                requester,
                thumbnail=thumbnail,
            )
        if kind == "playlist":
            return await self._paged_tracks(
                f"https://api.spotify.com/v1/playlists/{spotify_id}/items",
                requester,
            )
        raise SourceError("รองรับเฉพาะ Spotify track, album และ playlist")

    async def _token(self) -> str:
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token

        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")
        ).decode("ascii")
        async with self.http_client.post(
            "https://accounts.spotify.com/api/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
        ) as response:
            if response.status != 200:
                raise SourceError(f"Spotify authentication ล้มเหลว (HTTP {response.status})")
            payload = await response.json()

        token = payload.get("access_token")
        if not token:
            raise SourceError("Spotify ไม่ส่ง access token กลับมา")
        self._access_token = str(token)
        self._expires_at = time.monotonic() + max(int(payload.get("expires_in", 3600)) - 60, 60)
        return self._access_token

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = await self._token()
        async with self.http_client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        ) as response:
            if response.status == 429:
                raise SourceError("Spotify จำกัดจำนวนคำขอชั่วคราว กรุณาลองใหม่ภายหลัง")
            if response.status == 403:
                raise SourceError("Spotify ไม่อนุญาตให้แอปนี้อ่านรายการดังกล่าว")
            if response.status == 404:
                raise SourceError("ไม่พบรายการนี้ใน Spotify")
            if response.status != 200:
                raise SourceError(f"Spotify API ตอบกลับ HTTP {response.status}")
            payload = await response.json()
        if not isinstance(payload, dict):
            raise SourceError("Spotify ส่งข้อมูลกลับมาในรูปแบบที่ไม่ถูกต้อง")
        return payload

    async def _paged_tracks(
        self,
        url: str,
        requester: str,
        *,
        thumbnail: str | None = None,
    ) -> list[Track]:
        tracks: list[Track] = []
        next_url: str | None = url
        params: dict[str, Any] | None = {"limit": 50}

        while next_url and len(tracks) < MAX_TRACKS_PER_REQUEST:
            data = await self._get_json(next_url, params=params)
            params = None
            for wrapper in data.get("items") or []:
                if not isinstance(wrapper, dict):
                    continue
                item = wrapper.get("item") or wrapper.get("track") or wrapper
                if not isinstance(item, dict):
                    continue
                track = self._track_from_item(item, requester, thumbnail=thumbnail)
                if track:
                    tracks.append(track)
                if len(tracks) >= MAX_TRACKS_PER_REQUEST:
                    break
            next_url = data.get("next")

        if not tracks:
            raise SourceError("Spotify ไม่ส่งเพลงที่รองรับกลับมา อาจเป็น playlist ที่แอปไม่มีสิทธิ์อ่าน")
        return tracks

    @staticmethod
    def _track_from_item(
        item: dict[str, Any],
        requester: str,
        *,
        thumbnail: str | None = None,
    ) -> Track | None:
        title = str(item.get("name") or "").strip()
        if not title or item.get("type", "track") != "track":
            return None
        artists = ", ".join(
            str(artist.get("name"))
            for artist in item.get("artists") or []
            if isinstance(artist, dict) and artist.get("name")
        )
        album = item.get("album")
        if not thumbnail and isinstance(album, dict):
            images = album.get("images") or []
            if images and isinstance(images[0], dict):
                thumbnail = images[0].get("url")
        external_urls = item.get("external_urls") or {}
        spotify_id = str(item.get("id") or "")
        webpage_url = external_urls.get("spotify") or (
            f"https://open.spotify.com/track/{spotify_id}" if spotify_id else "https://open.spotify.com"
        )
        playback_query = " ".join(part for part in (title, artists, "official audio") if part)
        return Track(
            title=title,
            artists=artists,
            webpage_url=str(webpage_url),
            playback_query=playback_query,
            source="spotify",
            requester=requester,
            duration=float(item.get("duration_ms") or 0) / 1000,
            thumbnail=thumbnail,
        )


class MusicSourceResolver:
    """Route input to Spotify metadata or YouTube and provide playable streams."""

    def __init__(
        self,
        http_client: HttpClient,
        *,
        spotify_client_id: str | None,
        spotify_client_secret: str | None,
        youtube_cookies_file: str | None,
        youtube_cookies_base64: str | None,
    ) -> None:
        self.cookies = CookieFile(youtube_cookies_file, youtube_cookies_base64)
        self.youtube = YouTubeResolver(self.cookies)
        self.spotify = SpotifyResolver(http_client, spotify_client_id, spotify_client_secret)

    async def resolve(self, query: str, requester: str) -> list[Track]:
        clean_query = query.strip()
        if not clean_query:
            raise SourceError("กรุณาระบุชื่อเพลงหรือลิงก์")
        spotify_reference = self.spotify.parse_reference(clean_query)
        if spotify_reference:
            return await self.spotify.resolve(spotify_reference, requester)
        return await self.youtube.resolve(clean_query, requester)

    async def stream_url(self, track: Track) -> str:
        return await self.youtube.stream_url(track)

    def close(self) -> None:
        self.cookies.close()
