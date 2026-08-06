from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from src.cogs.dashboard import (
    DashboardCog,
    fetch_financial_metrics,
    parse_chart_metric,
)
from src.cogs.morning_digest import MorningDigestCog
from src.services.database import Database


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self, **_kwargs):
        return self.payload


class FakeHttpClient:
    def __init__(self, *, failed_symbol: str | None = None):
        self.failed_symbol = failed_symbol

    def get(self, url: str, **_kwargs):
        if "wttr.in" in url:
            return FakeResponse(
                {
                    "current_condition": [
                        {"temp_C": "30", "humidity": "70", "windspeedKmph": "8"}
                    ]
                }
            )
        if self.failed_symbol and self.failed_symbol in url:
            return FakeResponse({}, status=503)
        return FakeResponse(
            {
                "chart": {
                    "result": [
                        {"indicators": {"quote": [{"close": [100.0, None, 105.0]}]}}
                    ]
                }
            }
        )


class DashboardDigestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")

    def tearDown(self):
        self.temp.cleanup()

    def make_bot(self):
        bot = MagicMock()
        bot.user.display_avatar.url = "https://example.com/avatar.png"
        bot.external_http = FakeHttpClient()
        bot.database = self.database
        return bot

    def test_chart_parser_ignores_missing_closes(self):
        metric = parse_chart_metric(
            {
                "chart": {
                    "result": [
                        {"indicators": {"quote": [{"close": [100, None, 110]}]}}
                    ]
                }
            }
        )

        self.assertEqual(metric["price"], 110.0)
        self.assertEqual(metric["change"], 10.0)
        self.assertEqual(metric["pct_change"], 10.0)

    async def test_market_fetch_preserves_partial_results(self):
        metrics = await fetch_financial_metrics(
            FakeHttpClient(failed_symbol="SPY")
        )

        self.assertIsNone(metrics["SPY"])
        self.assertEqual(metrics["Gold"]["price"], 105.0)
        self.assertEqual(set(metrics), {"Gold", "SPY", "SET", "USDTHB"})

    async def test_dashboard_builds_when_news_is_unavailable(self):
        bot = self.make_bot()
        cog = DashboardCog.__new__(DashboardCog)
        cog.bot = bot
        cog.database = self.database
        cog.fetch_top_news = AsyncMock(return_value=[])

        embed = await cog.build_dashboard_embed()

        self.assertEqual(embed.title, "📊 Daily Dashboard")
        self.assertEqual(len(embed.fields), 2)
        self.assertIn("ยังไม่มีข้อมูลข่าว", embed.fields[1].value)

    async def test_digest_reuses_dashboard_and_adds_weather(self):
        bot = self.make_bot()
        dashboard = DashboardCog.__new__(DashboardCog)
        dashboard.bot = bot
        dashboard.database = self.database
        dashboard.fetch_top_news = AsyncMock(return_value=[])
        bot.get_cog.return_value = dashboard
        digest = MorningDigestCog.__new__(MorningDigestCog)
        digest.bot = bot
        digest.database = self.database

        embed = await digest._build("Bangkok")

        self.assertEqual(embed.title, "☀️ Morning Digest")
        self.assertEqual(embed.fields[1].name, "🌤️ อากาศ • Bangkok")
        self.assertIn("30°C", embed.fields[1].value)

    async def test_dashboard_setup_saves_message_after_publish(self):
        bot = self.make_bot()
        cog = DashboardCog.__new__(DashboardCog)
        cog.bot = bot
        cog.database = self.database
        cog.build_dashboard_embed = AsyncMock(return_value=discord.Embed(title="Dashboard"))
        interaction = MagicMock()
        interaction.guild.id = 7
        interaction.guild.me = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()
        channel = MagicMock()
        channel.id = 70
        channel.mention = "<#70>"
        channel.permissions_for.return_value = discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )
        published = MagicMock(id=700)
        channel.send = AsyncMock(return_value=published)

        await DashboardCog.dashboard_setup.callback(cog, interaction, channel)

        settings = self.database.get_automation_settings(7)
        self.assertEqual(settings["dashboard_channel_id"], 70)
        self.assertEqual(settings["dashboard_message_id"], 700)
        interaction.followup.send.assert_awaited_once()

    async def test_digest_setup_validates_channel_and_saves_schedule(self):
        bot = self.make_bot()
        cog = MorningDigestCog.__new__(MorningDigestCog)
        cog.bot = bot
        cog.database = self.database
        interaction = MagicMock()
        interaction.guild.id = 8
        interaction.guild.me = MagicMock()
        interaction.permissions.manage_guild = True
        interaction.response.send_message = AsyncMock()
        channel = MagicMock()
        channel.id = 80
        channel.mention = "<#80>"
        channel.permissions_for.return_value = discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
        )

        await MorningDigestCog.setup_digest.callback(
            cog,
            interaction,
            channel,
            9,
            30,
            "Asia/Bangkok",
            "Bangkok",
        )

        settings = self.database.get_settings(8)
        self.assertEqual(settings["digest_enabled"], 1)
        self.assertEqual(settings["digest_channel_id"], 80)
        self.assertEqual(settings["digest_hour"], 9)
        self.assertEqual(settings["digest_minute"], 30)


if __name__ == "__main__":
    unittest.main()
