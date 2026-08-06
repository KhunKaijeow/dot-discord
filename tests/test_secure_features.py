from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

import discord

from src.cogs.admin import can_manage_guild
from src.cogs.ai_tools import AIToolsCog
from src.cogs.reminder import parse_duration
from src.services.database import Database
from src.services.market_data import normalize_symbol


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



class ValidationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
