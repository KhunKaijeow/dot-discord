from datetime import datetime, timedelta, timezone
from pathlib import Path
import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from src.cogs.admin import can_manage_guild
from src.cogs.ai_tools import AIToolsCog
from src.cogs.deals_notifier import DealsNotifierCog
from src.cogs.reminder import parse_duration
from src.services.database import Database
from src.services.market_data import normalize_symbol
from src.services.typhoon import TyphoonService
from src.ui import EmbedColor, make_embed, make_notice_embed, truncate_text


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_reminder_persistence_and_ownership(self):
        reminder_id = self.database.create_reminder(
            1, 10, 20, "hello", datetime.now(timezone.utc) + timedelta(minutes=5)
        )
        self.assertEqual(len(self.database.list_reminders(1, 10)), 1)
        self.assertFalse(self.database.delete_reminder(reminder_id, 999))
        self.assertTrue(self.database.delete_reminder(reminder_id, 1))

    def test_alert_limit_and_ownership(self):
        alert_id = self.database.create_alert(1, 10, 20, "crypto", "BTC", "above", 100.0, False)
        self.assertFalse(self.database.delete_alert(alert_id, 2))
        self.assertTrue(self.database.delete_alert(alert_id, 1))

    def test_settings_fields_are_allowlisted(self):
        with self.assertRaises(ValueError):
            self.database.update_settings(1, malicious_column="value")

    def test_automation_settings_are_isolated_by_guild(self):
        self.database.update_automation_settings(
            10,
            dashboard_channel_id=100,
            dashboard_message_id=101,
            deals_channel_id=102,
            x_channel_id=103,
        )
        self.database.update_automation_settings(20, deals_channel_id=202)

        guild_10 = self.database.get_automation_settings(10)
        guild_20 = self.database.get_automation_settings(20)
        self.assertEqual(guild_10["dashboard_channel_id"], 100)
        self.assertEqual(guild_10["deals_channel_id"], 102)
        self.assertIsNone(guild_20["dashboard_channel_id"])
        self.assertEqual(guild_20["deals_channel_id"], 202)
        self.assertEqual(
            [row["guild_id"] for row in self.database.configured_automation_settings("deals_channel_id")],
            [10, 20],
        )

    def test_notifier_seen_items_are_isolated_and_bounded(self):
        self.database.remember_notifier_items(
            10,
            "deals",
            ["1", "2", "3", "4", "5"],
            keep_limit=3,
        )
        self.database.remember_notifier_items(20, "deals", ["1"])

        self.assertEqual(
            self.database.seen_notifier_items(10, "deals"),
            {"3", "4", "5"},
        )
        self.assertEqual(self.database.seen_notifier_items(20, "deals"), {"1"})
        self.assertEqual(self.database.notifier_seen_count(10, "deals"), 3)
        self.assertEqual(self.database.seen_notifier_items(10, "x"), set())

    def test_automation_repository_rejects_unknown_fields(self):
        with self.assertRaises(ValueError):
            self.database.update_automation_settings(1, unknown_channel_id=123)
        with self.assertRaises(ValueError):
            self.database.configured_automation_settings("unknown_channel_id")
        with self.assertRaises(ValueError):
            self.database.seen_notifier_items(1, "unknown")

    def test_playlist_crud_and_limits(self):
        user_id = 42
        tracks = [
            ("Track 1", "https://youtube.com/watch?v=1", "YouTube"),
            ("Track 2", "https://youtube.com/watch?v=2", "Spotify → YouTube")
        ]
        
        # Test saving
        self.database.save_playlist(user_id, "my_list", tracks)
        self.assertEqual(self.database.count_user_playlists(user_id), 1)
        
        # Test loading
        loaded_tracks = self.database.load_playlist(user_id, "my_list")
        self.assertEqual(len(loaded_tracks), 2)
        self.assertEqual(loaded_tracks[0]["title"], "Track 1")
        self.assertEqual(loaded_tracks[1]["title"], "Track 2")
        self.assertEqual(loaded_tracks[0]["requested_via"], "YouTube")
        
        # Test listing
        playlists = self.database.list_playlists(user_id)
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0]["name"], "my_list")
        self.assertEqual(playlists[0]["track_count"], 2)
        
        # Test saving overrides (overwriting playlist)
        new_tracks = [("Track 3", "https://youtube.com/watch?v=3", "YouTube")]
        self.database.save_playlist(user_id, "my_list", new_tracks)
        self.assertEqual(self.database.count_user_playlists(user_id), 1) # count remains 1
        loaded_tracks = self.database.load_playlist(user_id, "my_list")
        self.assertEqual(len(loaded_tracks), 1) # now only 1 track
        self.assertEqual(loaded_tracks[0]["title"], "Track 3")
        
        # Test deleting
        self.assertTrue(self.database.delete_playlist(user_id, "my_list"))
        self.assertEqual(self.database.count_user_playlists(user_id), 0)
        self.assertFalse(self.database.delete_playlist(user_id, "my_list")) # delete again should be False

    def test_delete_user_data_is_atomic_and_isolated(self):
        due_at = datetime.now(timezone.utc) + timedelta(hours=1)
        for user_id in (10, 20):
            self.database.create_reminder(
                user_id,
                1,
                100,
                f"reminder-{user_id}",
                due_at,
            )
            self.database.create_alert(
                user_id,
                1,
                100,
                "crypto",
                "BTC",
                "above",
                100.0,
                False,
            )
            self.database.save_playlist(
                user_id,
                "private",
                [(f"track-{user_id}", "https://youtube.com/watch?v=1", "YouTube")],
            )
        self.database.update_automation_settings(1, deals_channel_id=999)

        removed = self.database.delete_user_data(10)

        self.assertEqual(
            removed,
            {
                "reminders": 1,
                "alerts": 1,
                "playlists": 1,
                "playlist_tracks": 1,
            },
        )
        self.assertEqual(
            self.database.user_data_counts(10),
            {
                "reminders": 0,
                "alerts": 0,
                "playlists": 0,
                "playlist_tracks": 0,
            },
        )
        self.assertEqual(
            self.database.user_data_counts(20),
            {
                "reminders": 1,
                "alerts": 1,
                "playlists": 1,
                "playlist_tracks": 1,
            },
        )
        self.assertEqual(
            self.database.get_automation_settings(1)["deals_channel_id"],
            999,
        )



class ValidationTests(unittest.TestCase):
    def test_embed_text_is_truncated_to_discord_limit(self):
        self.assertEqual(truncate_text("abc", 3), "abc")
        self.assertEqual(truncate_text("abcdef", 4), "abc…")
        with self.assertRaises(ValueError):
            truncate_text("abc", 1)

    def test_shared_embed_style_has_author_and_no_footer(self):
        bot = MagicMock()
        bot.user.display_avatar.url = "https://example.com/avatar.png"

        embed = make_embed(
            bot,
            "Test",
            title="สวัสดี",
            color=EmbedColor.PRIMARY,
        )

        self.assertEqual(embed.author.name, "Javis • Test")
        self.assertIsNone(embed.footer.text)

    def test_notice_embed_uses_shared_style_and_requested_color(self):
        bot = MagicMock()
        bot.user.display_avatar.url = "https://example.com/avatar.png"

        embed = make_notice_embed(
            bot,
            "Music",
            "เรียบร้อยแล้ว",
            color=EmbedColor.SUCCESS,
        )

        self.assertEqual(embed.author.name, "Javis • Music")
        self.assertEqual(embed.description, "เรียบร้อยแล้ว")
        self.assertEqual(embed.title, "✅ ดำเนินการเรียบร้อย")
        self.assertEqual(embed.color.value, EmbedColor.SUCCESS)

        error_embed = make_notice_embed(
            bot,
            "Music",
            "😅 โหลดข้อมูลไม่สำเร็จ",
            color=EmbedColor.ERROR,
        )
        self.assertEqual(error_embed.title, "❌ ดำเนินการไม่สำเร็จ")
        self.assertEqual(error_embed.description, "โหลดข้อมูลไม่สำเร็จ")

    def test_typhoon_response_extraction(self):
        payload = {"choices": [{"message": {"content": "  สวัสดีครับ  "}}]}
        self.assertEqual(TyphoonService._extract_content(payload), "สวัสดีครับ")

        with self.assertRaises(ValueError):
            TyphoonService._extract_content({"choices": []})

    def test_typhoon_uses_injected_http_client(self):
        http_client = MagicMock()
        response = MagicMock()
        response.json.return_value = {
            "choices": [{"message": {"content": "พร้อมครับ"}}]
        }
        http_client.request_sync.return_value = response
        service = TyphoonService(api_key="test-key", http_client=http_client)

        self.assertEqual(
            service.generate_from_messages([{"role": "user", "content": "สวัสดี"}]),
            "พร้อมครับ",
        )
        http_client.request_sync.assert_called_once()

    def test_typhoon_chat_is_reused_and_reset(self):
        service = TyphoonService(api_key="test-key")
        first = service.get_or_create_chat(123)
        self.assertIs(first, service.get_or_create_chat(123))

        service.reset_chat(123)
        self.assertIsNot(first, service.get_or_create_chat(123))

    def test_typhoon_chat_keeps_one_system_message(self):
        service = TyphoonService(api_key="test-key")
        service.generate_from_messages = MagicMock(return_value="คำตอบ")
        chat = service.get_or_create_chat(123)

        response = chat.send_message("คำถาม")

        self.assertEqual(response.text, "คำตอบ")
        self.assertEqual(
            [item["role"] for item in chat.messages],
            ["system", "user", "assistant"],
        )

    def test_admin_permission_uses_guild_member_permissions(self):
        member = MagicMock(spec=discord.Member)
        member.guild_permissions = discord.Permissions(manage_guild=True)
        interaction = MagicMock()
        interaction.guild = MagicMock()
        interaction.user = member
        self.assertTrue(can_manage_guild(interaction))

    def test_duration_bounds(self):
        self.assertEqual(parse_duration("2h"), 7200)
        with self.assertRaises(ValueError):
            parse_duration("1 second")
        with self.assertRaises(ValueError):
            parse_duration("999999w")

    def test_market_symbol_allowlist(self):
        self.assertEqual(normalize_symbol("stock", "ptt.bk"), "PTT.BK")
        self.assertEqual(normalize_symbol("gold", "ignored"), "GC=F")
        with self.assertRaises(ValueError):
            normalize_symbol("stock", "AAPL; DROP TABLE")

    def test_ai_rate_limit(self):
        cog = AIToolsCog.__new__(AIToolsCog)
        from collections import defaultdict, deque
        cog._usage = defaultdict(deque)
        self.assertFalse(cog._rate_limited(1))
        self.assertFalse(cog._rate_limited(1))
        self.assertFalse(cog._rate_limited(1))
        self.assertTrue(cog._rate_limited(1))

    def test_spotify_playlist_resolver_missing_credentials(self):
        from src.cogs.music import resolve_tracks, MusicError
        from unittest.mock import patch
        
        user = MagicMock(spec=discord.User)
        with patch("src.cogs.music.SPOTIFY_CLIENT_ID", None), patch("src.cogs.music.SPOTIFY_CLIENT_SECRET", None):
            with self.assertRaises(MusicError) as context:
                asyncio.run(
                    resolve_tracks(
                        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGo3712j",
                        user,
                        MagicMock(),
                    )
                )
            self.assertIn("บอทไม่ได้ตั้งค่าตัวแปร `SPOTIFY_CLIENT_ID`", str(context.exception))


class NotifierDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.channels = {10: MagicMock(), 20: MagicMock()}
        for channel in self.channels.values():
            channel.send = AsyncMock()
        self.bot = MagicMock()
        self.bot.database = self.database
        self.bot.get_channel.side_effect = self.channels.get
        self.cog = DealsNotifierCog.__new__(DealsNotifierCog)
        self.cog.bot = self.bot
        self.cog.database = self.database
        self.database.update_automation_settings(1, deals_channel_id=10)
        self.database.update_automation_settings(2, deals_channel_id=20)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_deals_are_seeded_and_delivered_once_per_guild(self):
        settings = self.database.configured_automation_settings("deals_channel_id")
        existing = [{"id": 1, "title": "Existing"}]
        for row in settings:
            await self.cog._deliver_to_guild(row, existing)

        self.channels[10].send.assert_not_awaited()
        self.channels[20].send.assert_not_awaited()

        updated = [{"id": 2, "title": "New"}, *existing]
        for row in settings:
            await self.cog._deliver_to_guild(row, updated)
            await self.cog._deliver_to_guild(row, updated)

        self.channels[10].send.assert_awaited_once()
        self.channels[20].send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
