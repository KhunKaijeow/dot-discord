"""Ordered, transactional SQLite schema migrations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import sqlite3
from typing import Callable, Sequence


logger = logging.getLogger("javis.database_migrations")


class MigrationError(RuntimeError):
    """Raised when migration history is invalid or an upgrade fails."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]
    operation: Callable[[sqlite3.Connection], None] | None = None


def _repair_legacy_guild_settings(connection: sqlite3.Connection) -> None:
    """Add columns omitted by early schemas and normalize unsafe legacy values."""
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(guild_settings)")
    }
    definitions = {
        "timezone": "TEXT NOT NULL DEFAULT 'Asia/Bangkok'",
        "digest_enabled": (
            "INTEGER NOT NULL DEFAULT 0 CHECK (digest_enabled IN (0, 1))"
        ),
        "digest_channel_id": "INTEGER",
        "digest_hour": (
            "INTEGER NOT NULL DEFAULT 8 CHECK (digest_hour BETWEEN 0 AND 23)"
        ),
        "digest_minute": (
            "INTEGER NOT NULL DEFAULT 0 CHECK (digest_minute BETWEEN 0 AND 59)"
        ),
        "digest_city": "TEXT NOT NULL DEFAULT 'Bangkok'",
        "alert_channel_id": "INTEGER",
        "last_digest_date": "TEXT",
    }
    for name, definition in definitions.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE guild_settings ADD COLUMN {name} {definition}"
            )

    connection.execute(
        """
        UPDATE guild_settings
        SET timezone = CASE
                WHEN timezone IS NULL OR trim(CAST(timezone AS TEXT)) = ''
                    THEN 'Asia/Bangkok'
                ELSE trim(CAST(timezone AS TEXT))
            END,
            digest_enabled = CASE
                WHEN CAST(digest_enabled AS INTEGER) = 1 THEN 1 ELSE 0
            END,
            digest_hour = CASE
                WHEN trim(CAST(digest_hour AS TEXT)) <> ''
                    AND trim(CAST(digest_hour AS TEXT)) NOT GLOB '*[^0-9]*'
                    AND CAST(digest_hour AS INTEGER) BETWEEN 0 AND 23
                    THEN CAST(digest_hour AS INTEGER)
                ELSE 8
            END,
            digest_minute = CASE
                WHEN trim(CAST(digest_minute AS TEXT)) <> ''
                    AND trim(CAST(digest_minute AS TEXT)) NOT GLOB '*[^0-9]*'
                    AND CAST(digest_minute AS INTEGER) BETWEEN 0 AND 59
                    THEN CAST(digest_minute AS INTEGER)
                ELSE 0
            END,
            digest_city = CASE
                WHEN digest_city IS NULL OR trim(CAST(digest_city AS TEXT)) = ''
                    THEN 'Bangkok'
                ELSE trim(CAST(digest_city AS TEXT))
            END
        """
    )


MIGRATIONS = (
    Migration(
        version=1,
        name="core_persistence",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                timezone TEXT NOT NULL DEFAULT 'Asia/Bangkok',
                digest_enabled INTEGER NOT NULL DEFAULT 0
                    CHECK (digest_enabled IN (0, 1)),
                digest_channel_id INTEGER,
                digest_hour INTEGER NOT NULL DEFAULT 8
                    CHECK (digest_hour BETWEEN 0 AND 23),
                digest_minute INTEGER NOT NULL DEFAULT 0
                    CHECK (digest_minute BETWEEN 0 AND 59),
                digest_city TEXT NOT NULL DEFAULT 'Bangkok',
                alert_channel_id INTEGER,
                last_digest_date TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message TEXT NOT NULL CHECK (length(message) BETWEEN 1 AND 1000),
                due_at TEXT NOT NULL,
                repeat_seconds INTEGER CHECK (
                    repeat_seconds IS NULL
                    OR repeat_seconds BETWEEN 60 AND 31536000
                ),
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS reminders_due_idx ON reminders(due_at)",
            """
            CREATE TABLE IF NOT EXISTS price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                asset_type TEXT NOT NULL
                    CHECK (asset_type IN ('stock', 'crypto', 'gold')),
                symbol TEXT NOT NULL CHECK (length(symbol) BETWEEN 1 AND 20),
                condition TEXT NOT NULL CHECK (condition IN ('above', 'below')),
                target_price REAL NOT NULL CHECK (target_price > 0),
                repeat_enabled INTEGER NOT NULL DEFAULT 0
                    CHECK (repeat_enabled IN (0, 1)),
                last_triggered_at TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS alerts_guild_idx ON price_alerts(guild_id)",
            """
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 50),
                created_at TEXT NOT NULL,
                UNIQUE(user_id, name)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS playlist_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL
                    REFERENCES playlists(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                youtube_url TEXT NOT NULL,
                requested_via TEXT NOT NULL,
                position INTEGER NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS playlists_user_idx ON playlists(user_id)",
        ),
    ),
    Migration(
        version=2,
        name="guild_automation",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS automation_settings (
                guild_id INTEGER PRIMARY KEY,
                dashboard_channel_id INTEGER,
                dashboard_message_id INTEGER,
                deals_channel_id INTEGER,
                x_channel_id INTEGER
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS notifier_seen_items (
                guild_id INTEGER NOT NULL,
                notifier TEXT NOT NULL CHECK (notifier IN ('deals', 'x')),
                item_id TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, notifier, item_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS notifier_seen_lookup_idx
                ON notifier_seen_items(guild_id, notifier, seen_at)
            """,
        ),
    ),
    Migration(
        version=3,
        name="repair_legacy_guild_settings",
        statements=(),
        operation=_repair_legacy_guild_settings,
    ),
    Migration(
        version=4,
        name="remove_legacy_music_data",
        statements=(
            "DROP TABLE IF EXISTS playlist_tracks",
            "DROP TABLE IF EXISTS playlists",
        ),
    ),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def _validate_registry(migrations: Sequence[Migration]) -> None:
    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(migrations) + 1)):
        raise MigrationError("Migration versions must be unique and contiguous from 1")
    if any(not migration.name.strip() for migration in migrations):
        raise MigrationError("Migration names must not be empty")
    if len({migration.name for migration in migrations}) != len(migrations):
        raise MigrationError("Migration names must be unique")


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> int:
    """Apply every pending migration and return the latest schema version."""
    _validate_registry(migrations)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY CHECK (version > 0),
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.commit()

    applied = {
        int(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        )
    }
    known_versions = {migration.version for migration in migrations}
    unknown_versions = set(applied) - known_versions
    if unknown_versions:
        raise MigrationError(
            f"Database schema is newer than this application: {max(unknown_versions)}"
        )
    if applied and set(applied) != set(range(1, max(applied) + 1)):
        raise MigrationError("Migration history has missing versions")

    for migration in migrations:
        recorded_name = applied.get(migration.version)
        if recorded_name is not None:
            if recorded_name != migration.name:
                raise MigrationError(
                    f"Migration {migration.version} name does not match history"
                )
            continue

        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in migration.statements:
                connection.execute(statement)
            if migration.operation is not None:
                migration.operation(connection)
            connection.execute(
                """
                INSERT INTO schema_migrations(version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()
        except Exception as error:
            connection.rollback()
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) failed"
            ) from error
        logger.info(
            "Applied database migration %d (%s)",
            migration.version,
            migration.name,
        )

    return migrations[-1].version if migrations else 0
