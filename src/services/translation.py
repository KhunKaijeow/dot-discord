"""Async client for the Google Translate web endpoint."""

import aiohttp


GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"


class TranslationServiceError(Exception):
    """Raised when text cannot be translated."""


class TranslationService:
    """Translate text without coupling HTTP details to Discord commands."""

    def __init__(self, timeout_seconds: int = 15):
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def translate(
        self,
        text: str,
        target_language: str,
        source_language: str = "auto",
        session: aiohttp.ClientSession | None = None,
    ) -> tuple[str, str]:
        owns_session = session is None
        if session is None:
            session = aiohttp.ClientSession(timeout=self._timeout)

        try:
            async with session.get(
                GOOGLE_TRANSLATE_URL,
                params={
                    "client": "gtx",
                    "sl": source_language,
                    "tl": target_language,
                    "dt": "t",
                    "q": text.strip(),
                },
            ) as response:
                if response.status != 200:
                    raise TranslationServiceError(
                        f"Translation request failed ({response.status})"
                    )
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise TranslationServiceError("Translation service is unavailable") from error
        finally:
            if owns_session:
                await session.close()

        try:
            translated_text = "".join(
                segment[0] for segment in payload[0] if segment[0]
            )
            detected_language = payload[2] if len(payload) > 2 else source_language
        except (IndexError, TypeError):
            raise TranslationServiceError("Unexpected translation response") from None

        if not translated_text:
            raise TranslationServiceError("Translation response is empty")
        return translated_text, detected_language
