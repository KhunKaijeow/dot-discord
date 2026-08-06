"""Thai weekday colors sourced from Wikimedia."""

import asyncio
from dataclasses import dataclass
import re
import time

import aiohttp
from bs4 import BeautifulSoup

from .http_client import HttpClient


MEDIAWIKI_API_URL = "https://en.wikipedia.org/w/api.php"
SOURCE_PAGE_URL = "https://en.wikipedia.org/wiki/Colors_of_the_day_in_Thailand"
SOURCE_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
SOURCE_PAGE_NAME = "Colors_of_the_day_in_Thailand"
CACHE_SECONDS = 24 * 60 * 60

WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

THAI_WEEKDAYS = (
    "วันจันทร์",
    "วันอังคาร",
    "วันพุธ",
    "วันพฤหัสบดี",
    "วันศุกร์",
    "วันเสาร์",
    "วันอาทิตย์",
)

# Thai labels and embed colors are presentation metadata. The selected color
# itself always comes from the source table.
COLOR_PRESENTATION = {
    "red": ("แดง", 0xE74C3C),
    "yellow or cream": ("เหลืองหรือครีม", 0xF1C40F),
    "pink": ("ชมพู", 0xFF69B4),
    "green": ("เขียว", 0x2ECC71),
    "orange": ("ส้ม", 0xE67E22),
    "light blue": ("ฟ้าอ่อน", 0x3498DB),
    "purple": ("ม่วง", 0x8E44AD),
}


@dataclass(frozen=True)
class DailyColor:
    weekday: int
    day_name_th: str
    color_name_th: str
    source_color_name: str
    embed_color: int


class DailyColorServiceError(Exception):
    """Raised when the source table cannot be retrieved or parsed."""


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


class ThaiDailyColorService:
    """Fetch and cache the openly licensed Thai weekday-color table."""

    def __init__(self, http_client: HttpClient, cache_seconds: int = CACHE_SECONDS):
        self._http = http_client
        self._cache_seconds = cache_seconds
        self._colors: dict[int, DailyColor] = {}
        self._cache_expires_at = 0.0
        self._refresh_lock = asyncio.Lock()

    async def get_color(self, weekday: int) -> DailyColor:
        if weekday not in range(7):
            raise ValueError("weekday must be between 0 and 6")

        if self._cache_is_fresh:
            return self._colors[weekday]

        async with self._refresh_lock:
            if self._cache_is_fresh:
                return self._colors[weekday]

            try:
                colors = await self._fetch_colors()
            except DailyColorServiceError:
                if self._colors:
                    return self._colors[weekday]
                raise

            self._colors = colors
            self._cache_expires_at = time.monotonic() + self._cache_seconds
            return colors[weekday]

    @property
    def _cache_is_fresh(self) -> bool:
        return bool(self._colors) and time.monotonic() < self._cache_expires_at

    async def _fetch_colors(self) -> dict[int, DailyColor]:
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with self._http.get(
                MEDIAWIKI_API_URL,
                timeout=timeout,
                params={
                    "action": "parse",
                    "page": SOURCE_PAGE_NAME,
                    "prop": "text",
                    "format": "json",
                    "formatversion": "2",
                },
                headers={
                    "User-Agent": (
                        "JavisDiscordBot/1.0 "
                        "(https://github.com/KhunKaijeow/dot-discord)"
                    )
                },
            ) as response:
                if response.status != 200:
                    raise DailyColorServiceError(
                        f"Wikimedia request failed ({response.status})"
                    )
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise DailyColorServiceError(
                "Wikimedia color source is unavailable"
            ) from error

        try:
            page_html = payload["parse"]["text"]
        except (KeyError, TypeError):
            raise DailyColorServiceError(
                "Unexpected Wikimedia response"
            ) from None
        return self._parse_color_table(page_html)

    @staticmethod
    def _parse_color_table(page_html: str) -> dict[int, DailyColor]:
        soup = BeautifulSoup(page_html, "html.parser")

        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if header_row is None:
                continue
            header_cells = header_row.find_all(["th", "td"], recursive=False)
            headers = [
                _normalize(cell.get_text(" ", strip=True)) for cell in header_cells
            ]
            day_index = next(
                (index for index, header in enumerate(headers) if header == "day"),
                None,
            )
            color_index = next(
                (
                    index
                    for index, header in enumerate(headers)
                    if "color of the day" in header
                ),
                None,
            )
            if day_index is None or color_index is None:
                continue

            colors: dict[int, DailyColor] = {}
            for row in table.find_all("tr")[1:]:
                cells = row.find_all(["th", "td"], recursive=False)
                if max(day_index, color_index) >= len(cells):
                    continue

                day_key = _normalize(cells[day_index].get_text(" ", strip=True))
                source_color = _normalize(
                    cells[color_index].get_text(" ", strip=True)
                )
                weekday = WEEKDAY_INDEX.get(day_key)
                presentation = COLOR_PRESENTATION.get(source_color)
                if weekday is None or presentation is None:
                    continue

                color_name_th, embed_color = presentation
                colors[weekday] = DailyColor(
                    weekday=weekday,
                    day_name_th=THAI_WEEKDAYS[weekday],
                    color_name_th=color_name_th,
                    source_color_name=source_color.capitalize(),
                    embed_color=embed_color,
                )

            if len(colors) == 7:
                return colors

        raise DailyColorServiceError(
            "Thai weekday-color table could not be parsed"
        )
