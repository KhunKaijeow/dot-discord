"""Prokerala Astrology API client with token and daily forecast caching."""

import asyncio
from datetime import datetime
import html
import time

import aiohttp

from .translation import TranslationService, TranslationServiceError


PROKERALA_TOKEN_URL = "https://api.prokerala.com/token"
PROKERALA_HOROSCOPE_URL = "https://api.prokerala.com/v2/horoscope/daily/advanced"
PREDICTION_TYPES = ("general", "love", "career", "health")


class ProkeralaServiceError(Exception):
    """Raised when a horoscope cannot be retrieved."""


class ProkeralaService:
    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        translator: TranslationService | None = None,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._translator = translator or TranslationService()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._forecast_lock = asyncio.Lock()
        self._forecast_cache: dict[tuple[str, str], dict[str, str]] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def get_daily_horoscope(
        self,
        sign: str,
        now: datetime,
    ) -> dict[str, str]:
        cache_key = (now.date().isoformat(), sign)
        if cached := self._forecast_cache.get(cache_key):
            return cached

        async with self._forecast_lock:
            if cached := self._forecast_cache.get(cache_key):
                return cached

            timeout = aiohttp.ClientTimeout(total=20)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    token = await self._get_access_token(session)
                    predictions = await self._fetch_predictions(
                        session, token, sign, now
                    )
                    translated = await asyncio.gather(
                        *(
                            self._translator.translate(
                                predictions[prediction_type],
                                target_language="th",
                                source_language="en",
                                session=session,
                            )
                            for prediction_type in PREDICTION_TYPES
                        )
                    )
            except (
                aiohttp.ClientError,
                TimeoutError,
                TranslationServiceError,
                ValueError,
            ) as error:
                raise ProkeralaServiceError(
                    "Daily horoscope service is unavailable"
                ) from error

            result = {
                prediction_type: translated[index][0]
                for index, prediction_type in enumerate(PREDICTION_TYPES)
            }
            self._forecast_cache = {
                key: value
                for key, value in self._forecast_cache.items()
                if key[0] == cache_key[0]
            }
            self._forecast_cache[cache_key] = result
            return result

    async def _get_access_token(self, session: aiohttp.ClientSession) -> str:
        if self._access_token and time.monotonic() < self._access_token_expires_at:
            return self._access_token

        async with self._token_lock:
            if (
                self._access_token
                and time.monotonic() < self._access_token_expires_at
            ):
                return self._access_token

            async with session.post(
                PROKERALA_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            ) as response:
                if response.status != 200:
                    raise ProkeralaServiceError(
                        f"Prokerala token request failed ({response.status})"
                    )
                payload = await response.json(content_type=None)

            token = payload.get("access_token")
            if not token:
                raise ProkeralaServiceError(
                    "Prokerala token response has no access_token"
                )
            expires_in = int(payload.get("expires_in", 3600))
            self._access_token = token
            self._access_token_expires_at = (
                time.monotonic() + max(expires_in - 60, 1)
            )
            return token

    async def _fetch_predictions(
        self,
        session: aiohttp.ClientSession,
        token: str,
        sign: str,
        now: datetime,
    ) -> dict[str, str]:
        async with session.get(
            PROKERALA_HOROSCOPE_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "datetime": now.isoformat(timespec="seconds"),
                "sign": sign,
                "type": "all",
            },
        ) as response:
            if response.status != 200:
                raise ProkeralaServiceError(
                    f"Prokerala horoscope request failed ({response.status})"
                )
            payload = await response.json(content_type=None)

        try:
            items = payload["data"]["daily_predictions"][0]["predictions"]
            predictions = {
                item["type"].lower(): html.unescape(item["prediction"]).strip()
                for item in items
                if item.get("type") and item.get("prediction")
            }
        except (KeyError, IndexError, TypeError):
            raise ProkeralaServiceError(
                "Unexpected Prokerala horoscope response"
            ) from None

        if not set(PREDICTION_TYPES).issubset(predictions):
            raise ProkeralaServiceError(
                "Prokerala response is missing prediction categories"
            )
        return predictions
