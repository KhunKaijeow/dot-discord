import unittest

import discord
from discord.ext import commands

from src.services.http_client import HttpClient


class HttpClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_is_idempotent_and_close_releases_session(self):
        client = HttpClient()
        self.assertFalse(client.is_started)

        await client.start()
        session = client._session
        await client.start()

        self.assertTrue(client.is_started)
        self.assertIs(client._session, session)

        await client.close()
        self.assertFalse(client.is_started)
        self.assertTrue(session.closed)
        with self.assertRaises(RuntimeError):
            client.request_sync("GET", "https://example.com")

    async def test_request_requires_started_client(self):
        client = HttpClient()
        with self.assertRaises(RuntimeError):
            client.get("https://example.com")
        await client.close()

    async def test_external_client_does_not_replace_discord_http_client(self):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        external_http = HttpClient()
        bot.external_http = external_http

        self.assertTrue(hasattr(bot.http, "static_login"))
        self.assertIs(bot.external_http, external_http)
        self.assertIsNot(bot.http, external_http)

        await external_http.close()
        await bot.close()


if __name__ == "__main__":
    unittest.main()
