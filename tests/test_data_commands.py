from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.cogs.admin import AdminCog
from src.cogs.dashboard import DashboardCog
from src.cogs.deals_notifier import DealsNotifierCog
from src.cogs.privacy import PrivacyCog
from src.cogs.x_notifier import XNotifierCog
from src.services.database import Database


class DataCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.db")
        self.bot = MagicMock()
        self.bot.database = self.database
        self.bot.user.display_avatar.url = "https://example.com/avatar.png"
        self.interaction = MagicMock()
        self.interaction.guild.id = 1
        self.interaction.user.id = 10
        self.interaction.response.send_message = AsyncMock()

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_disable_commands_only_clear_current_guild_settings(self):
        for guild_id in (1, 2):
            self.database.update_automation_settings(
                guild_id,
                dashboard_channel_id=100 + guild_id,
                dashboard_message_id=200 + guild_id,
                deals_channel_id=300 + guild_id,
                x_channel_id=400 + guild_id,
            )

        for cog_class, command in (
            (DashboardCog, DashboardCog.dashboard_disable),
            (DealsNotifierCog, DealsNotifierCog.deals_disable),
            (XNotifierCog, XNotifierCog.x_disable),
        ):
            cog = cog_class.__new__(cog_class)
            cog.bot = self.bot
            cog.database = self.database
            await command.callback(cog, self.interaction)

        disabled = self.database.get_automation_settings(1)
        untouched = self.database.get_automation_settings(2)
        self.assertIsNone(disabled["dashboard_channel_id"])
        self.assertIsNone(disabled["dashboard_message_id"])
        self.assertIsNone(disabled["deals_channel_id"])
        self.assertIsNone(disabled["x_channel_id"])
        self.assertEqual(untouched["dashboard_channel_id"], 102)
        self.assertEqual(untouched["deals_channel_id"], 302)
        self.assertEqual(untouched["x_channel_id"], 402)

    async def test_personal_data_command_requires_confirmation(self):
        self.database.create_reminder(
            10,
            1,
            100,
            "private reminder",
            datetime.now(timezone.utc) + timedelta(hours=1),
        )
        cog = PrivacyCog(self.bot)

        await PrivacyCog.my_data_delete.callback(cog, self.interaction, False)
        self.assertEqual(self.database.user_data_counts(10)["reminders"], 1)

        await PrivacyCog.my_data_delete.callback(cog, self.interaction, True)
        self.assertEqual(self.database.user_data_counts(10)["reminders"], 0)
        self.assertEqual(self.interaction.response.send_message.await_count, 2)

    async def test_settings_command_normalizes_legacy_display_values(self):
        bot = MagicMock()
        bot.user.display_avatar.url = "https://example.com/avatar.png"
        bot.database.get_settings.return_value = {
            "digest_enabled": None,
            "digest_hour": "bad",
            "digest_minute": None,
            "timezone": None,
        }
        interaction = MagicMock()
        interaction.guild.id = 1
        interaction.user.id = 10
        interaction.response.send_message = AsyncMock()

        with patch("src.cogs.admin.can_manage_guild", return_value=True):
            await AdminCog.settings.callback(AdminCog(bot), interaction)

        embed = interaction.response.send_message.await_args.kwargs["embed"]
        self.assertIn("`08:00`", embed.fields[1].value)
        self.assertIn("`Asia/Bangkok`", embed.fields[1].value)


if __name__ == "__main__":
    unittest.main()
