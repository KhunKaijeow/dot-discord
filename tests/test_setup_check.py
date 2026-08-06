import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from src.cogs.setup_check import SetupCheckCog, permission_checks
from src.services.database_migrations import LATEST_SCHEMA_VERSION


class SetupCheckTests(unittest.IsolatedAsyncioTestCase):
    def make_interaction(
        self,
        *,
        manage_guild: bool = True,
        send_messages: bool = True,
    ) -> MagicMock:
        interaction = MagicMock()
        interaction.permissions = discord.Permissions(manage_guild=manage_guild)
        interaction.app_permissions = discord.Permissions(
            view_channel=True,
            send_messages=send_messages,
            embed_links=True,
            attach_files=True,
        )
        interaction.guild.me.guild_permissions = discord.Permissions(
            connect=True,
            speak=True,
        )
        interaction.response.send_message = AsyncMock()
        return interaction

    def make_bot(self) -> MagicMock:
        bot = MagicMock()
        bot.user.display_avatar.url = "https://example.com/avatar.png"
        bot.database.counts.return_value = {
            "schema_version": LATEST_SCHEMA_VERSION,
        }
        bot.external_http.is_started = True
        bot.command_sync_succeeded = True
        bot.command_sync_count = 59
        return bot

    async def test_healthy_core_has_no_required_failures(self):
        interaction = self.make_interaction()
        bot = self.make_bot()

        await SetupCheckCog.setup_check.callback(
            SetupCheckCog(bot),
            interaction,
        )

        embed = interaction.response.send_message.await_args.kwargs["embed"]
        self.assertNotIn("❌", embed.title)
        self.assertIn("ปัญหาหลัก `0` จุด", embed.description)
        self.assertIn("schema v", embed.fields[1].value)
        self.assertIn("sync แล้ว 59 คำสั่ง", embed.fields[1].value)
        self.assertTrue(
            interaction.response.send_message.await_args.kwargs["ephemeral"]
        )

    async def test_missing_user_and_bot_permissions_are_required_failures(self):
        interaction = self.make_interaction(
            manage_guild=False,
            send_messages=False,
        )

        checks = permission_checks(interaction)

        failures = [item.label for item in checks if item.required and not item.ok]
        self.assertEqual(failures, ["สิทธิ์ผู้เรียก", "Send Messages"])

    async def test_database_failure_is_reported_without_crashing(self):
        interaction = self.make_interaction()
        bot = self.make_bot()
        bot.database.counts.side_effect = OSError("private path must not leak")

        with self.assertLogs("javis.setup_check", level="ERROR"):
            await SetupCheckCog.setup_check.callback(
                SetupCheckCog(bot),
                interaction,
            )

        embed = interaction.response.send_message.await_args.kwargs["embed"]
        self.assertIn("❌", embed.title)
        self.assertIn("เปิดหรืออ่านฐานข้อมูลไม่สำเร็จ", embed.fields[1].value)
        self.assertNotIn("private path", str(embed.to_dict()))


if __name__ == "__main__":
    unittest.main()
