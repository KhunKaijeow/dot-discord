from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.services.database import Database
from src.services.database_migrations import (
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    Migration,
    MigrationError,
    apply_migrations,
)


class DatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_database_applies_each_migration_once(self):
        database = Database(self.path)
        first_history = database.migration_history()

        reopened = Database(self.path)

        self.assertEqual(database.schema_version(), LATEST_SCHEMA_VERSION)
        self.assertEqual(
            [(row["version"], row["name"]) for row in first_history],
            [(migration.version, migration.name) for migration in MIGRATIONS],
        )
        self.assertEqual(reopened.migration_history(), first_history)

    def test_existing_unversioned_schema_is_adopted_without_data_loss(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute(MIGRATIONS[0].statements[0])
            connection.execute(
                "INSERT INTO guild_settings(guild_id, timezone) VALUES (?, ?)",
                (123, "Asia/Tokyo"),
            )

        database = Database(self.path)

        self.assertEqual(database.schema_version(), LATEST_SCHEMA_VERSION)
        self.assertEqual(database.get_settings(123)["timezone"], "Asia/Tokyo")

    def test_failed_migration_rolls_back_its_schema_and_history(self):
        migrations = (
            Migration(1, "base", ("CREATE TABLE stable (id INTEGER PRIMARY KEY)",)),
            Migration(
                2,
                "broken",
                (
                    "CREATE TABLE should_rollback (id INTEGER PRIMARY KEY)",
                    "INSERT INTO missing_table(id) VALUES (1)",
                ),
            ),
        )
        with sqlite3.connect(self.path) as connection:
            with self.assertRaises(MigrationError):
                apply_migrations(connection, migrations)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            history = connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()

        self.assertIn("stable", tables)
        self.assertNotIn("should_rollback", tables)
        self.assertEqual(history, [(1, "base")])

    def test_newer_database_version_is_rejected(self):
        with sqlite3.connect(self.path) as connection:
            apply_migrations(connection)
            connection.execute(
                """
                INSERT INTO schema_migrations(version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (LATEST_SCHEMA_VERSION + 1, "future", "2026-01-01T00:00:00+00:00"),
            )

        with self.assertRaises(MigrationError):
            Database(self.path)


if __name__ == "__main__":
    unittest.main()
