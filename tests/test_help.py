import unittest
from unittest.mock import AsyncMock, MagicMock

from src.cogs.help import (
    CATEGORIES_BY_KEY,
    HELP_CATEGORIES,
    HelpCog,
    HelpView,
    build_help_embed,
)


class HelpTests(unittest.IsolatedAsyncioTestCase):
    def make_bot(self) -> MagicMock:
        bot = MagicMock()
        bot.user.display_avatar.url = "https://example.com/avatar.png"
        return bot

    def test_category_keys_are_unique_and_select_fits_discord_limit(self):
        self.assertEqual(len(CATEGORIES_BY_KEY), len(HELP_CATEGORIES))
        self.assertLessEqual(len(HELP_CATEGORIES) + 1, 25)

    def test_overview_lists_every_category(self):
        embed = build_help_embed(self.make_bot())

        self.assertEqual(len(embed.fields), len(HELP_CATEGORIES))
        for category in HELP_CATEGORIES:
            self.assertTrue(any(category.label in field.name for field in embed.fields))

    def test_category_page_lists_its_commands(self):
        embed = build_help_embed(self.make_bot(), "reminders")

        self.assertIn("/remind", embed.description)
        self.assertIn("/reminder-cancel", embed.description)
        self.assertIn("Reminder", embed.title)

    async def test_help_command_is_ephemeral_and_has_interactive_view(self):
        bot = self.make_bot()
        interaction = MagicMock()
        interaction.user.id = 42
        interaction.response.send_message = AsyncMock()

        await HelpCog.help_command.callback(HelpCog(bot), interaction)

        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertIsInstance(kwargs["view"], HelpView)
        self.assertEqual(len(kwargs["view"].children), 1)


if __name__ == "__main__":
    unittest.main()
