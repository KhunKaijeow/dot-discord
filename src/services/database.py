"""Small, parameterized SQLite persistence layer for bot-owned state."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any

from .database_migrations import apply_migrations


DATABASE_PATH = Path("data/javis.db")


class Database:
    """Thread-safe repository. Values are always bound, never interpolated into SQL."""

    def __init__(self, path: Path = DATABASE_PATH):
        self.path = path
        self._lock = threading.RLock()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._initialize()
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            apply_migrations(connection)

    def migration_history(self) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
        )

    def schema_version(self) -> int:
        rows = self._rows(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        )
        return int(rows[0]["version"])

    def _rows(self, sql: str, values: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock, closing(self._connect()) as connection:
            return [dict(row) for row in connection.execute(sql, values).fetchall()]

    def _write(self, sql: str, values: tuple[Any, ...] = ()) -> int:
        with self._lock, closing(self._connect()) as connection:
            cursor = connection.execute(sql, values)
            connection.commit()
            return int(cursor.lastrowid or cursor.rowcount)

    def get_settings(self, guild_id: int) -> dict[str, Any]:
        self._write("INSERT OR IGNORE INTO guild_settings(guild_id) VALUES (?)", (guild_id,))
        return self._rows("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))[0]

    def update_settings(self, guild_id: int, **changes: Any) -> None:
        allowed = {
            "timezone", "digest_enabled", "digest_channel_id", "digest_hour",
            "digest_minute", "digest_city", "alert_channel_id", "last_digest_date",
        }
        if not changes or not set(changes).issubset(allowed):
            raise ValueError("Unsupported settings field")
        self.get_settings(guild_id)
        assignments = ", ".join(f"{key} = ?" for key in changes)
        self._write(
            f"UPDATE guild_settings SET {assignments} WHERE guild_id = ?",  # keys are allowlisted
            (*changes.values(), guild_id),
        )

    def all_digest_settings(self) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM guild_settings WHERE digest_enabled = 1 AND digest_channel_id IS NOT NULL"
        )

    def get_automation_settings(self, guild_id: int) -> dict[str, Any]:
        self._write(
            "INSERT OR IGNORE INTO automation_settings(guild_id) VALUES (?)",
            (guild_id,),
        )
        return self._rows(
            "SELECT * FROM automation_settings WHERE guild_id = ?",
            (guild_id,),
        )[0]

    def update_automation_settings(self, guild_id: int, **changes: Any) -> None:
        allowed = {
            "dashboard_channel_id",
            "dashboard_message_id",
            "deals_channel_id",
            "x_channel_id",
        }
        if not changes or not set(changes).issubset(allowed):
            raise ValueError("Unsupported automation settings field")
        self.get_automation_settings(guild_id)
        assignments = ", ".join(f"{key} = ?" for key in changes)
        self._write(
            f"UPDATE automation_settings SET {assignments} WHERE guild_id = ?",
            (*changes.values(), guild_id),
        )

    def configured_automation_settings(self, channel_field: str) -> list[dict[str, Any]]:
        allowed = {"dashboard_channel_id", "deals_channel_id", "x_channel_id"}
        if channel_field not in allowed:
            raise ValueError("Unsupported automation channel field")
        return self._rows(
            f"SELECT * FROM automation_settings WHERE {channel_field} IS NOT NULL"
        )

    @staticmethod
    def _validate_notifier(notifier: str) -> None:
        if notifier not in {"deals", "x"}:
            raise ValueError("Unsupported notifier")

    def seen_notifier_items(self, guild_id: int, notifier: str) -> set[str]:
        self._validate_notifier(notifier)
        return {
            row["item_id"]
            for row in self._rows(
                "SELECT item_id FROM notifier_seen_items WHERE guild_id = ? AND notifier = ?",
                (guild_id, notifier),
            )
        }

    def remember_notifier_items(
        self,
        guild_id: int,
        notifier: str,
        item_ids: list[str],
        *,
        keep_limit: int = 200,
    ) -> None:
        self._validate_notifier(notifier)
        clean_ids = list(dict.fromkeys(str(item_id) for item_id in item_ids if item_id))
        if not clean_ids:
            return
        if keep_limit < 1:
            raise ValueError("keep_limit must be positive")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, closing(self._connect()) as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO notifier_seen_items(guild_id, notifier, item_id, seen_at) VALUES (?,?,?,?)",
                [(guild_id, notifier, item_id, now) for item_id in clean_ids],
            )
            connection.execute(
                """
                DELETE FROM notifier_seen_items
                WHERE rowid IN (
                    SELECT rowid FROM notifier_seen_items
                    WHERE guild_id = ? AND notifier = ?
                    ORDER BY seen_at DESC, rowid DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (guild_id, notifier, keep_limit),
            )
            connection.commit()

    def notifier_seen_count(self, guild_id: int, notifier: str) -> int:
        self._validate_notifier(notifier)
        return int(
            self._rows(
                "SELECT COUNT(*) AS count FROM notifier_seen_items WHERE guild_id = ? AND notifier = ?",
                (guild_id, notifier),
            )[0]["count"]
        )

    def create_reminder(self, user_id: int, guild_id: int, channel_id: int,
                        message: str, due_at: datetime, repeat_seconds: int | None = None) -> int:
        return self._write(
            "INSERT INTO reminders(user_id,guild_id,channel_id,message,due_at,repeat_seconds,created_at) VALUES (?,?,?,?,?,?,?)",
            (user_id, guild_id, channel_id, message, due_at.astimezone(timezone.utc).isoformat(),
             repeat_seconds, datetime.now(timezone.utc).isoformat()),
        )

    def due_reminders(self, now: datetime, limit: int = 50) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM reminders WHERE due_at <= ? ORDER BY due_at LIMIT ?",
            (now.astimezone(timezone.utc).isoformat(), limit),
        )

    def list_reminders(self, user_id: int, guild_id: int) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM reminders WHERE user_id = ? AND guild_id = ? ORDER BY due_at LIMIT 25",
            (user_id, guild_id),
        )

    def delete_reminder(self, reminder_id: int, user_id: int) -> bool:
        return self._write("DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id)) > 0

    def finish_reminder(self, reminder_id: int, repeat_seconds: int | None, next_due: datetime | None) -> None:
        if repeat_seconds and next_due:
            self._write("UPDATE reminders SET due_at = ? WHERE id = ?", (next_due.isoformat(), reminder_id))
        else:
            self._write("DELETE FROM reminders WHERE id = ?", (reminder_id,))

    def create_alert(self, user_id: int, guild_id: int, channel_id: int, asset_type: str,
                     symbol: str, condition: str, target_price: float, repeat_enabled: bool) -> int:
        count = self._rows("SELECT COUNT(*) AS count FROM price_alerts WHERE user_id = ?", (user_id,))[0]["count"]
        if count >= 20:
            raise ValueError("Alert limit reached")
        return self._write(
            "INSERT INTO price_alerts(user_id,guild_id,channel_id,asset_type,symbol,condition,target_price,repeat_enabled,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, guild_id, channel_id, asset_type, symbol, condition, target_price,
             int(repeat_enabled), datetime.now(timezone.utc).isoformat()),
        )

    def all_alerts(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM price_alerts ORDER BY id")

    def list_alerts(self, user_id: int, guild_id: int) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM price_alerts WHERE user_id = ? AND guild_id = ? ORDER BY id", (user_id, guild_id))

    def delete_alert(self, alert_id: int, user_id: int) -> bool:
        return self._write("DELETE FROM price_alerts WHERE id = ? AND user_id = ?", (alert_id, user_id)) > 0

    def mark_alert_triggered(self, alert_id: int, repeat_enabled: bool) -> None:
        if repeat_enabled:
            self._write("UPDATE price_alerts SET last_triggered_at = ? WHERE id = ?",
                        (datetime.now(timezone.utc).isoformat(), alert_id))
        else:
            self._write("DELETE FROM price_alerts WHERE id = ?", (alert_id,))

    def counts(self) -> dict[str, int]:
        with self._lock, closing(self._connect()) as connection:
            return {
                "reminders": connection.execute("SELECT COUNT(*) FROM reminders").fetchone()[0],
                "alerts": connection.execute("SELECT COUNT(*) FROM price_alerts").fetchone()[0],
                "digests": connection.execute("SELECT COUNT(*) FROM guild_settings WHERE digest_enabled = 1").fetchone()[0],
                "schema_version": connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()[0],
            }

    def user_data_counts(self, user_id: int) -> dict[str, int]:
        """Count persistent records owned by one Discord user across all guilds."""
        if user_id < 1:
            raise ValueError("user_id must be positive")
        with self._lock, closing(self._connect()) as connection:
            return self._user_data_counts(connection, user_id)

    @staticmethod
    def _user_data_counts(
        connection: sqlite3.Connection,
        user_id: int,
    ) -> dict[str, int]:
        return {
            "reminders": connection.execute(
                "SELECT COUNT(*) FROM reminders WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0],
            "alerts": connection.execute(
                "SELECT COUNT(*) FROM price_alerts WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0],
        }

    def delete_user_data(self, user_id: int) -> dict[str, int]:
        """Delete one user's persistent data atomically and return removed counts."""
        if user_id < 1:
            raise ValueError("user_id must be positive")
        with self._lock, closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                counts = self._user_data_counts(connection, user_id)
                connection.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
                connection.execute("DELETE FROM price_alerts WHERE user_id = ?", (user_id,))
                connection.commit()
                return counts
            except Exception:
                connection.rollback()
                raise
