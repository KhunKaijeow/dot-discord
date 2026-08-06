import unittest
from unittest.mock import MagicMock

import discord
from discord import app_commands

from src.bot import app_command_error_message
from src.cogs.draw import ImageGenerationError, image_generation_error_message


class ErrorMessageTests(unittest.TestCase):
    def test_forbidden_embed_error_lists_missing_bot_permissions(self):
        response = MagicMock()
        response.status = 403
        response.reason = "Forbidden"
        response.headers = {}
        forbidden = discord.Forbidden(
            response,
            {"code": 50013, "message": "Missing Permissions"},
        )
        error = app_commands.AppCommandError()
        error.original = forbidden
        interaction = MagicMock()
        interaction.app_permissions = discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=False,
            attach_files=True,
        )

        message = app_command_error_message(interaction, error)

        self.assertIn("Embed Links", message)
        self.assertNotIn("Attach Files", message)

    def test_timeout_has_actionable_message(self):
        error = app_commands.AppCommandError()
        error.original = TimeoutError()

        message = app_command_error_message(MagicMock(), error)

        self.assertIn("ตอบช้า", message)

    def test_together_unauthorized_identifies_invalid_key(self):
        message = image_generation_error_message(
            ImageGenerationError("Together AI returned HTTP 401")
        )

        self.assertIn("TOGETHER_API_KEY", message)
        self.assertIn("restart", message)


if __name__ == "__main__":
    unittest.main()
