"""OpenTyphoon client and per-channel conversation state."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from threading import Lock
import time
from typing import Any

import requests

from ..config import TYPHOON_API_KEY
from .http_client import HttpClient


logger = logging.getLogger("javis.typhoon")

TYPHOON_API_URL = "https://api.opentyphoon.ai/v1/chat/completions"
TYPHOON_MODEL = "typhoon-v2.5-30b-a3b-instruct"
MAX_HISTORY_MESSAGES = 20
DEFAULT_MAX_RETRIES = 3


class TyphoonServiceError(RuntimeError):
    """Raised when OpenTyphoon cannot return a usable response."""


@dataclass(frozen=True, slots=True)
class TyphoonResponse:
    text: str


class TyphoonChat:
    def __init__(self, service: TyphoonService, system_instruction: str):
        self.service = service
        self.messages = [{"role": "system", "content": system_instruction}]
        self._lock = Lock()

    def send_message(self, prompt: str) -> TyphoonResponse:
        with self._lock:
            self.messages.append({"role": "user", "content": prompt})
            self.messages = [self.messages[0], *self.messages[1:][-MAX_HISTORY_MESSAGES:]]

            try:
                reply = self.service.generate_from_messages(self.messages)
            except Exception:
                self.messages.pop()
                raise

            self.messages.append({"role": "assistant", "content": reply})
            return TyphoonResponse(reply)


class TyphoonService:
    """Synchronous OpenTyphoon client used from Discord worker threads."""

    def __init__(
        self,
        api_key: str | None = TYPHOON_API_KEY,
        http_client: HttpClient | None = None,
    ):
        if not api_key:
            raise ValueError("TYPHOON_API_KEY is required")
        self.api_key = api_key
        self.http = http_client or HttpClient()
        self.chat_sessions: dict[int, TyphoonChat] = {}

    def get_or_create_chat(self, channel_id: int) -> TyphoonChat:
        if channel_id not in self.chat_sessions:
            self.chat_sessions[channel_id] = TyphoonChat(
                self,
                "You are Javis, a helpful, cool, and polite Discord bot assistant. "
                "Keep your answers concise and formatted nicely for Discord chats "
                "using Markdown and emojis. Respond naturally in Thai.",
            )
        return self.chat_sessions[channel_id]

    def reset_chat(self, channel_id: int) -> None:
        self.chat_sessions.pop(channel_id, None)

    def generate_from_messages(
        self,
        messages: list[dict[str, str]],
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> str:
        if max_retries < 1:
            raise ValueError("max_retries must be at least 1")
        payload = {
            "model": TYPHOON_MODEL,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": 1500,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                response = self.http.request_sync(
                    "POST",
                    TYPHOON_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=30,
                )
                response.raise_for_status()
                return self._extract_content(response.json())
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                last_error = error
                logger.warning(
                    "OpenTyphoon request failed (attempt %d/%d): %s",
                    attempt,
                    max_retries,
                    type(error).__name__,
                )
                if attempt < max_retries:
                    time.sleep(attempt)

        raise TyphoonServiceError("OpenTyphoon request failed after retries") from last_error

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("OpenTyphoon returned no choices")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ValueError("OpenTyphoon returned an invalid choice")
        message = first_choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("OpenTyphoon returned empty content")
        return content.strip()

    def generate_response(self, prompt: str) -> str:
        return self.generate_from_messages([{"role": "user", "content": prompt}])

    def generate_complex_response(
        self,
        prompt: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> str:
        return self._generate_with_fallback(prompt, max_retries)

    def generate_with_retry(
        self,
        prompt: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> str:
        return self._generate_with_fallback(prompt, max_retries)

    def _generate_with_fallback(self, prompt: str, max_retries: int) -> str:
        try:
            return self.generate_from_messages(
                [{"role": "user", "content": prompt}],
                max_retries,
            )
        except TyphoonServiceError:
            return (
                "Sorry, I'm having trouble connecting to the AI right now. "
                "Please try again later."
            )
