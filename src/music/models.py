"""Models shared by music sources and the Discord player."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MusicSource = Literal["spotify", "youtube"]


@dataclass(frozen=True, slots=True)
class Track:
    """A queue item whose audio stream is resolved immediately before playback."""

    title: str
    artists: str
    webpage_url: str
    playback_query: str
    source: MusicSource
    requester: str
    duration: float = 0
    thumbnail: str | None = None

    @property
    def display_name(self) -> str:
        if self.artists:
            return f"{self.title} — {self.artists}"
        return self.title
