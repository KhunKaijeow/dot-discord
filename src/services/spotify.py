"""Spotify API service for resolving track, playlist, and album metadata."""

import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from .http_client import HttpClient

logger = logging.getLogger("discord.javis.spotify")


class SpotifyService:
    """Service to communicate with the Spotify Web API using Client Credentials flow."""

    def __init__(self, http_client: HttpClient) -> None:
        self.client_id = SPOTIFY_CLIENT_ID
        self.client_secret = SPOTIFY_CLIENT_SECRET
        self.http_client = http_client
        self.access_token: Optional[str] = None
        self.token_expires_at: float = 0.0

    async def get_token(self) -> str:
        """Fetch or refresh the Spotify Access Token."""
        now = time.time()
        if self.access_token and now < self.token_expires_at:
            return self.access_token

        if not self.client_id or not self.client_secret:
            logger.error("Spotify Client ID or Secret is missing in environment variables.")
            return ""

        auth_url = "https://accounts.spotify.com/api/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        try:
            async with self.http_client.post(auth_url, headers=headers, data=data) as resp:
                if resp.status != 200:
                    logger.error("Failed to authenticate with Spotify: HTTP %s", resp.status)
                    return ""
                res_json = await resp.json()
                self.access_token = res_json.get("access_token")
                expires_in = res_json.get("expires_in", 3600)
                self.token_expires_at = now + expires_in - 60
                return self.access_token or ""
        except Exception:
            logger.exception("Error while requesting Spotify access token")
            return ""

    async def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Fetch metadata for a single Spotify track."""
        token = await self.get_token()
        if not token:
            return None

        url = f"https://api.spotify.com/v1/tracks/{track_id}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with self.http_client.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.error("Spotify API error fetching track %s: HTTP %s", track_id, resp.status)
                    return None
                data = await resp.json()
                artists = ", ".join([a.get("name") for a in data.get("artists", []) if isinstance(a, dict) and a.get("name")])
                
                thumbnail = None
                album = data.get("album")
                if isinstance(album, dict) and album.get("images"):
                    images = album.get("images")
                    if isinstance(images, list) and len(images) > 0 and isinstance(images[0], dict):
                        thumbnail = images[0].get("url")

                return {
                    "title": data.get("name", "Unknown Title"),
                    "artist": artists,
                    "duration": (data.get("duration_ms") or 0) / 1000,
                    "url": f"https://open.spotify.com/track/{track_id}",
                    "thumbnail": thumbnail,
                    "spotify_id": track_id
                }
        except Exception:
            logger.exception("Error fetching Spotify track details")
            return None

    async def get_playlist_tracks(self, playlist_id: str) -> List[Dict[str, Any]]:
        """Fetch metadata for tracks in a Spotify playlist (up to 200 tracks)."""
        token = await self.get_token()
        if not token:
            return []

        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"limit": 100}

        tracks: List[Dict[str, Any]] = []
        next_url: Optional[str] = url
        pages_fetched = 0

        try:
            while next_url and pages_fetched < 2:
                async with self.http_client.get(next_url, headers=headers, params=params if pages_fetched == 0 else None) as resp:
                    if resp.status != 200:
                        logger.error("Spotify API error fetching playlist %s: HTTP %s", playlist_id, resp.status)
                        break
                    data = await resp.json()
                    items = data.get("items", [])
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        track = item.get("track")
                        if not track or not isinstance(track, dict):
                            continue
                        title = track.get("name")
                        if not title:
                            continue

                        artist_list = [a.get("name") for a in track.get("artists", []) if isinstance(a, dict) and a.get("name")]
                        artists = ", ".join(artist_list)

                        thumbnail = None
                        album = track.get("album")
                        if isinstance(album, dict) and album.get("images"):
                            images = album.get("images")
                            if isinstance(images, list) and len(images) > 0 and isinstance(images[0], dict):
                                thumbnail = images[0].get("url")

                        track_id = track.get("id")
                        tracks.append({
                            "title": title,
                            "artist": artists,
                            "duration": (track.get("duration_ms") or 0) / 1000,
                            "url": f"https://open.spotify.com/track/{track_id}" if track_id else "",
                            "thumbnail": thumbnail,
                            "spotify_id": track_id
                        })
                    next_url = data.get("next")
                    pages_fetched += 1
            return tracks
        except Exception:
            logger.exception("Error fetching Spotify playlist tracks")
            return []

    async def get_album_tracks(self, album_id: str) -> List[Dict[str, Any]]:
        """Fetch metadata for tracks in a Spotify album (up to 100 tracks)."""
        token = await self.get_token()
        if not token:
            return []

        headers = {"Authorization": f"Bearer {token}"}

        album_thumbnail = None
        try:
            album_url = f"https://api.spotify.com/v1/albums/{album_id}"
            async with self.http_client.get(album_url, headers=headers) as resp:
                if resp.status == 200:
                    album_data = await resp.json()
                    images = album_data.get("images", [])
                    if isinstance(images, list) and len(images) > 0 and isinstance(images[0], dict):
                        album_thumbnail = images[0].get("url")
        except Exception:
            logger.warning("Could not fetch album details for thumbnail", exc_info=True)

        tracks_url = f"https://api.spotify.com/v1/albums/{album_id}/tracks"
        params = {"limit": 100}
        tracks: List[Dict[str, Any]] = []

        try:
            async with self.http_client.get(tracks_url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logger.error("Spotify API error fetching album %s: HTTP %s", album_id, resp.status)
                    return []
                data = await resp.json()
                items = data.get("items", [])
                for track in items:
                    if not isinstance(track, dict):
                        continue
                    title = track.get("name")
                    if not title:
                        continue
                    artist_list = [a.get("name") for a in track.get("artists", []) if isinstance(a, dict) and a.get("name")]
                    artists = ", ".join(artist_list)
                    track_id = track.get("id")
                    tracks.append({
                        "title": title,
                        "artist": artists,
                        "duration": (track.get("duration_ms") or 0) / 1000,
                        "url": f"https://open.spotify.com/track/{track_id}" if track_id else "",
                        "thumbnail": album_thumbnail,
                        "spotify_id": track_id
                    })
            return tracks
        except Exception:
            logger.exception("Error fetching Spotify album tracks")
            return []

    async def parse_url(self, url: str) -> Optional[List[Dict[str, Any]]]:
        """Parse the Spotify URL and return metadata for any identified tracks."""
        pattern = re.compile(
            r"https?://open\.spotify\.com/(?:intl-[a-z]+/|user/[^/]+/)?(?P<type>track|playlist|album)/(?P<id>[a-zA-Z0-9]+)"
        )
        match = pattern.search(url)
        if not match:
            return None

        media_type = match.group("type")
        media_id = match.group("id")

        if media_type == "track":
            track = await self.get_track(media_id)
            return [track] if track else []
        elif media_type == "playlist":
            return await self.get_playlist_tracks(media_id)
        elif media_type == "album":
            return await self.get_album_tracks(media_id)

        return None
