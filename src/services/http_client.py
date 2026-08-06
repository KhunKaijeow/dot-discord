"""Shared HTTP transports owned by the bot lifecycle."""

from __future__ import annotations

from threading import Lock, local
from typing import Any

import aiohttp
import requests


DEFAULT_TIMEOUT_SECONDS = 20


class HttpClient:
    """Reuse connection pools for all outbound HTTP requests."""

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None
        self._sync_local = local()
        self._sync_sessions: list[requests.Session] = []
        self._sync_lock = Lock()
        self._closed = False

    @property
    def is_started(self) -> bool:
        return self._session is not None and not self._session.closed

    async def start(self) -> None:
        if self.is_started:
            return
        if self._closed:
            raise RuntimeError("HTTP client has already been closed")
        connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
        self._session = aiohttp.ClientSession(
            timeout=self._timeout,
            connector=connector,
            raise_for_status=False,
        )

    async def close(self) -> None:
        self._closed = True
        session = self._session
        self._session = None
        if session and not session.closed:
            await session.close()
        with self._sync_lock:
            for sync_session in self._sync_sessions:
                sync_session.close()
            self._sync_sessions.clear()

    def request(self, method: str, url: str, **kwargs: Any):
        if not self.is_started:
            raise RuntimeError("HTTP client has not been started")
        assert self._session is not None
        return self._session.request(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any):
        return self.request("POST", url, **kwargs)

    def request_sync(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Make a pooled blocking request from a worker thread."""
        if self._closed:
            raise RuntimeError("HTTP client has already been closed")
        sync_session = getattr(self._sync_local, "session", None)
        if sync_session is None:
            sync_session = requests.Session()
            self._sync_local.session = sync_session
            with self._sync_lock:
                self._sync_sessions.append(sync_session)
        return sync_session.request(method, url, **kwargs)
