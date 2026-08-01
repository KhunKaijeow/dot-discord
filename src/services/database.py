"""Small, parameterized SQLite persistence layer for bot-owned state."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any


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
        schema = """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            timezone TEXT NOT NULL DEFAULT 'Asia/Bangkok',
            digest_enabled INTEGER NOT NULL DEFAULT 0 CHECK (digest_enabled IN (0, 1)),
            digest_channel_id INTEGER,
            digest_hour INTEGER NOT NULL DEFAULT 8 CHECK (digest_hour BETWEEN 0 AND 23),
            digest_minute INTEGER NOT NULL DEFAULT 0 CHECK (digest_minute BETWEEN 0 AND 59),
            digest_city TEXT NOT NULL DEFAULT 'Bangkok',
            alert_channel_id INTEGER,
            last_digest_date TEXT
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message TEXT NOT NULL CHECK (length(message) BETWEEN 1 AND 1000),
            due_at TEXT NOT NULL,
            repeat_seconds INTEGER CHECK (repeat_seconds IS NULL OR repeat_seconds BETWEEN 60 AND 31536000),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS reminders_due_idx ON reminders(due_at);
        CREATE TABLE IF NOT EXISTS price_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'crypto', 'gold')),
            symbol TEXT NOT NULL CHECK (length(symbol) BETWEEN 1 AND 20),
            condition TEXT NOT NULL CHECK (condition IN ('above', 'below')),
            target_price REAL NOT NULL CHECK (target_price > 0),
            repeat_enabled INTEGER NOT NULL DEFAULT 0 CHECK (repeat_enabled IN (0, 1)),
            last_triggered_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS alerts_guild_idx ON price_alerts(guild_id);
        """
        with self._lock, closing(self._connect()) as connection:
            connection.executescript(schema)
            connection.commit()

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
            }
