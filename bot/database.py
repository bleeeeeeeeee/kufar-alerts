from __future__ import annotations

import json
import logging
import ssl
import sqlite3
from asyncio import Lock
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg
from asyncpg import Connection, Pool, Record

from bot.access_config import ACCESS_MODE_KEY, normalize_access_mode

logger = logging.getLogger(__name__)

# Схема таблиц для PostgreSQL (Neon) - для бэкапов
SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS seen_ads (
    alert_id INTEGER NOT NULL,
    ad_id INTEGER NOT NULL,
    seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (alert_id, ad_id),
    FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(active);
CREATE INDEX IF NOT EXISTS idx_seen_ads_alert ON seen_ads(alert_id);

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_active ON users(active);

CREATE TABLE IF NOT EXISTS notification_messages (
    user_id BIGINT NOT NULL,
    alert_id INTEGER NOT NULL,
    chat_id BIGINT NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, message_id),
    FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notification_messages_user ON notification_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_messages_alert ON notification_messages(alert_id);

CREATE TABLE IF NOT EXISTS bot_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Схема для SQLite
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS seen_ads (
    alert_id INTEGER NOT NULL,
    ad_id INTEGER NOT NULL,
    seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (alert_id, ad_id)
);

CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(active);
CREATE INDEX IF NOT EXISTS idx_seen_ads_alert ON seen_ads(alert_id);

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_active ON users(active);

CREATE TABLE IF NOT EXISTS notification_messages (
    user_id INTEGER NOT NULL,
    alert_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_notification_messages_user ON notification_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_messages_alert ON notification_messages(alert_id);

CREATE TABLE IF NOT EXISTS bot_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class Alert:
    id: int
    user_id: int
    name: str
    query: str
    params: dict[str, Any] = field(default_factory=dict)
    active: bool = True
    created_at: str | None = None

    @property
    def search_params(self) -> dict[str, str]:
        from bot.kufar_params import normalize_params_for_api
        from bot.price import prc_for_api

        params = normalize_params_for_api(
            {k: str(v) for k, v in self.params.items() if not str(k).startswith("_")}
        )
        if "prc" in params:
            api_prc = prc_for_api(params["prc"])
            if api_prc:
                params["prc"] = api_prc
            else:
                params.pop("prc")
        params["query"] = self.query
        return params


class Database:
    def __init__(self, dsn: str | None = None, db_path: str | None = None) -> None:
        """Инициализация БД. Если dsn указан - используем PostgreSQL, иначе SQLite."""
        self.dsn = dsn
        self.db_path = db_path or "data/kufar_alerts.db"
        self.pool: Pool | None = None
        self.sqlite_conn: sqlite3.Connection | None = None
        self._ready = False
        self._settings_locks: dict[int, Lock] = defaultdict(Lock)
        self._use_postgres = bool(dsn)

    async def init(self, admin_user_ids: tuple[int, ...] = ()) -> None:
        """Инициализация базы данных."""
        if self._use_postgres:
            await self._init_postgres(admin_user_ids)
        else:
            await self._init_sqlite(admin_user_ids)

    async def _init_postgres(self, admin_user_ids: tuple[int, ...]) -> None:
        """Инициализация PostgreSQL (Supabase)."""
        logger.info("Connecting to Supabase PostgreSQL database...")
        
        # Создаем SSL-контекст для Supabase
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=1,
            max_size=5,
            timeout=60.0,
            ssl=ssl_context,
            statement_cache_size=0  # ОТКЛЮЧАЕМ prepared statements
        )
        
        async with self._db() as conn:
            await conn.execute(SCHEMA)
            logger.info("Supabase schema created/verified")

        await self._bootstrap_users(admin_user_ids)
        alerts, seen = await self.stats()
        users = await self.count_users()
        logger.info("Supabase ready: %s alerts, %s seen, %s users", alerts, seen, users)
        self._ready = True

    async def _init_sqlite(self, admin_user_ids: tuple[int, ...]) -> None:
        """Инициализация SQLite - основная БД."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.sqlite_conn = sqlite3.connect(self.db_path)
        self.sqlite_conn.row_factory = sqlite3.Row
        
        with self.sqlite_conn:
            self.sqlite_conn.executescript(SQLITE_SCHEMA)
            logger.info("SQLite schema created/verified at %s", self.db_path)

        # Добавляем админов
        for admin_id in admin_user_ids:
            self.sqlite_conn.execute(
                """
                INSERT OR REPLACE INTO users (user_id, role, active)
                VALUES (?, 'admin', 1)
                """,
                (admin_id,)
            )
        self.sqlite_conn.commit()
        
        alerts, seen = await self.stats()
        users = await self.count_users()
        logger.info("SQLite ready: %s alerts, %s seen, %s users", alerts, seen, users)
        self._ready = True

    @asynccontextmanager
    async def _db(self) -> AsyncIterator[Connection]:
        """Контекстный менеджер для PostgreSQL."""
        if not self.pool:
            raise RuntimeError("PostgreSQL not initialized")
        async with self.pool.acquire() as conn:
            yield conn

    def _sqlite_conn(self):
        """Получить SQLite соединение."""
        if not self.sqlite_conn:
            raise RuntimeError("SQLite not initialized")
        return self.sqlite_conn

    # --- ОСНОВНЫЕ МЕТОДЫ (работают с SQLite или PostgreSQL) ---

    async def count_users(self) -> int:
        if self._use_postgres:
            async with self._db() as conn:
                row = await conn.fetchrow("SELECT COUNT(*) FROM users")
                return row[0] if row else 0
        else:
            cursor = self._sqlite_conn().execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0] or 0

    async def stats(self) -> tuple[int, int]:
        if self._use_postgres:
            async with self._db() as conn:
                alerts = await conn.fetchval("SELECT COUNT(*) FROM alerts")
                seen = await conn.fetchval("SELECT COUNT(*) FROM seen_ads")
                return alerts or 0, seen or 0
        else:
            conn = self._sqlite_conn()
            alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] or 0
            seen = conn.execute("SELECT COUNT(*) FROM seen_ads").fetchone()[0] or 0
            return alerts, seen

    async def _bootstrap_users(self, admin_user_ids: tuple[int, ...]) -> None:
        if not admin_user_ids or not self._use_postgres:
            return
        async with self._db() as conn:
            for admin_id in admin_user_ids:
                await conn.execute(
                    """
                    INSERT INTO users (user_id, role, active)
                    VALUES ($1, 'admin', 1)
                    ON CONFLICT (user_id) DO UPDATE 
                    SET role = 'admin', active = 1
                    """,
                    admin_id,
                )

    @staticmethod
    def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
        from bot.kufar_params import normalize_params_for_storage

        params = {k: v for k, v in params.items() if not str(k).startswith("_")}
        if params.get("prc"):
            from bot.price import normalize_prc

            normalized = normalize_prc(params["prc"])
            if normalized:
                params["prc"] = normalized
            else:
                params.pop("prc", None)
        return normalize_params_for_storage({k: str(v) for k, v in params.items() if v})

    async def create_alert(
        self,
        user_id: int,
        name: str,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        active: bool = True,
    ) -> Alert:
        params = self._normalize_params(params or {})
        
        if self._use_postgres:
            async with self._db() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO alerts (user_id, name, query, params_json, active)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id, created_at
                    """,
                    user_id, name, query, json.dumps(params, ensure_ascii=False), 1 if active else 0,
                )
                alert_id = row["id"]
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute(
                """
                INSERT INTO alerts (user_id, name, query, params_json, active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, name, query, json.dumps(params, ensure_ascii=False), 1 if active else 0)
            )
            conn.commit()
            alert_id = cursor.lastrowid
        
        logger.info("Created alert %s for user %s", alert_id, user_id)
        alert = await self.get_alert(alert_id)
        assert alert is not None
        return alert

    async def get_user_alerts(self, user_id: int) -> list[Alert]:
        if self._use_postgres:
            async with self._db() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM alerts WHERE user_id = $1 ORDER BY id DESC",
                    user_id,
                )
            return [self._row_to_alert(row) for row in rows]
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute(
                "SELECT * FROM alerts WHERE user_id = ? ORDER BY id DESC",
                (user_id,)
            )
            return [self._row_to_alert_sqlite(row) for row in cursor.fetchall()]

    async def get_active_alerts(self) -> list[Alert]:
        if self._use_postgres:
            async with self._db() as conn:
                rows = await conn.fetch(
                    """
                    SELECT a.* FROM alerts a
                    WHERE a.active = 1
                      AND (
                        NOT EXISTS (SELECT 1 FROM users u WHERE u.user_id = a.user_id)
                        OR EXISTS (SELECT 1 FROM users u WHERE u.user_id = a.user_id AND u.active = 1)
                      )
                    """
                )
            return [self._row_to_alert(row) for row in rows]
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute("""
                SELECT a.* FROM alerts a
                WHERE a.active = 1
                  AND (
                    NOT EXISTS (SELECT 1 FROM users u WHERE u.user_id = a.user_id)
                    OR EXISTS (SELECT 1 FROM users u WHERE u.user_id = a.user_id AND u.active = 1)
                  )
            """)
            return [self._row_to_alert_sqlite(row) for row in cursor.fetchall()]

    async def get_alert(self, alert_id: int, user_id: int | None = None) -> Alert | None:
        if self._use_postgres:
            async with self._db() as conn:
                if user_id is not None:
                    row = await conn.fetchrow(
                        "SELECT * FROM alerts WHERE id = $1 AND user_id = $2",
                        alert_id, user_id,
                    )
                else:
                    row = await conn.fetchrow(
                        "SELECT * FROM alerts WHERE id = $1",
                        alert_id,
                    )
            return self._row_to_alert(row) if row else None
        else:
            conn = self._sqlite_conn()
            if user_id is not None:
                cursor = conn.execute(
                    "SELECT * FROM alerts WHERE id = ? AND user_id = ?",
                    (alert_id, user_id)
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM alerts WHERE id = ?",
                    (alert_id,)
                )
            row = cursor.fetchone()
            return self._row_to_alert_sqlite(row) if row else None

    async def set_alert_active(self, alert_id: int, user_id: int, active: bool) -> bool:
        if self._use_postgres:
            async with self._db() as conn:
                result = await conn.execute(
                    "UPDATE alerts SET active = $1 WHERE id = $2 AND user_id = $3",
                    1 if active else 0, alert_id, user_id,
                )
                return result != "UPDATE 0"
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute(
                "UPDATE alerts SET active = ? WHERE id = ? AND user_id = ?",
                (1 if active else 0, alert_id, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    async def delete_alert(self, alert_id: int, user_id: int) -> bool:
        if self._use_postgres:
            async with self._db() as conn:
                await conn.execute(
                    "DELETE FROM notification_messages WHERE alert_id = $1 AND user_id = $2",
                    alert_id, user_id,
                )
                await conn.execute("DELETE FROM seen_ads WHERE alert_id = $1", alert_id)
                result = await conn.execute(
                    "DELETE FROM alerts WHERE id = $1 AND user_id = $2",
                    alert_id, user_id,
                )
                return result != "DELETE 0"
        else:
            conn = self._sqlite_conn()
            conn.execute(
                "DELETE FROM notification_messages WHERE alert_id = ? AND user_id = ?",
                (alert_id, user_id)
            )
            conn.execute("DELETE FROM seen_ads WHERE alert_id = ?", (alert_id,))
            cursor = conn.execute(
                "DELETE FROM alerts WHERE id = ? AND user_id = ?",
                (alert_id, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    async def record_notification(
        self,
        user_id: int,
        alert_id: int,
        chat_id: int,
        message_id: int,
    ) -> None:
        if self._use_postgres:
            async with self._db() as conn:
                await conn.execute(
                    """
                    INSERT INTO notification_messages (user_id, alert_id, chat_id, message_id)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id, message_id) DO UPDATE SET
                        alert_id = EXCLUDED.alert_id,
                        chat_id = EXCLUDED.chat_id
                    """,
                    user_id, alert_id, chat_id, message_id,
                )
        else:
            conn = self._sqlite_conn()
            conn.execute(
                """
                INSERT OR REPLACE INTO notification_messages (user_id, alert_id, chat_id, message_id)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, alert_id, chat_id, message_id)
            )
            conn.commit()

    async def forget_notification(self, user_id: int, message_id: int) -> None:
        if self._use_postgres:
            async with self._db() as conn:
                await conn.execute(
                    "DELETE FROM notification_messages WHERE user_id = $1 AND message_id = $2",
                    user_id, message_id,
                )
        else:
            conn = self._sqlite_conn()
            conn.execute(
                "DELETE FROM notification_messages WHERE user_id = ? AND message_id = ?",
                (user_id, message_id)
            )
            conn.commit()

    async def pop_notification_messages(
        self,
        user_id: int,
        *,
        alert_id: int | None = None,
    ) -> list[tuple[int, int]]:
        if self._use_postgres:
            async with self._db() as conn:
                if alert_id is None:
                    rows = await conn.fetch(
                        """
                        SELECT chat_id, message_id
                        FROM notification_messages
                        WHERE user_id = $1
                        ORDER BY created_at ASC
                        """,
                        user_id,
                    )
                    await conn.execute(
                        "DELETE FROM notification_messages WHERE user_id = $1",
                        user_id,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT chat_id, message_id
                        FROM notification_messages
                        WHERE user_id = $1 AND alert_id = $2
                        ORDER BY created_at ASC
                        """,
                        user_id, alert_id,
                    )
                    await conn.execute(
                        "DELETE FROM notification_messages WHERE user_id = $1 AND alert_id = $2",
                        user_id, alert_id,
                    )
            return [(row["chat_id"], row["message_id"]) for row in rows]
        else:
            conn = self._sqlite_conn()
            if alert_id is None:
                cursor = conn.execute(
                    "SELECT chat_id, message_id FROM notification_messages WHERE user_id = ? ORDER BY created_at ASC",
                    (user_id,)
                )
                rows = cursor.fetchall()
                conn.execute("DELETE FROM notification_messages WHERE user_id = ?", (user_id,))
            else:
                cursor = conn.execute(
                    "SELECT chat_id, message_id FROM notification_messages WHERE user_id = ? AND alert_id = ? ORDER BY created_at ASC",
                    (user_id, alert_id)
                )
                rows = cursor.fetchall()
                conn.execute(
                    "DELETE FROM notification_messages WHERE user_id = ? AND alert_id = ?",
                    (user_id, alert_id)
                )
            conn.commit()
            return [(row["chat_id"], row["message_id"]) for row in rows]

    async def count_notification_messages(
        self,
        user_id: int,
        *,
        alert_id: int | None = None,
    ) -> int:
        if self._use_postgres:
            async with self._db() as conn:
                if alert_id is None:
                    count = await conn.fetchval(
                        "SELECT COUNT(*) FROM notification_messages WHERE user_id = $1",
                        user_id,
                    )
                else:
                    count = await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM notification_messages
                        WHERE user_id = $1 AND alert_id = $2
                        """,
                        user_id, alert_id,
                    )
            return count or 0
        else:
            conn = self._sqlite_conn()
            if alert_id is None:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM notification_messages WHERE user_id = ?",
                    (user_id,)
                )
            else:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM notification_messages WHERE user_id = ? AND alert_id = ?",
                    (user_id, alert_id)
                )
            return cursor.fetchone()[0] or 0

    async def get_notification_counts_by_alert(self, user_id: int) -> dict[int, int]:
        if self._use_postgres:
            async with self._db() as conn:
                rows = await conn.fetch(
                    """
                    SELECT alert_id, COUNT(*) as count
                    FROM notification_messages
                    WHERE user_id = $1
                    GROUP BY alert_id
                    """,
                    user_id,
                )
            return {row["alert_id"]: row["count"] for row in rows if row["count"] > 0}
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute(
                """
                SELECT alert_id, COUNT(*) as count
                FROM notification_messages
                WHERE user_id = ?
                GROUP BY alert_id
                """,
                (user_id,)
            )
            return {row["alert_id"]: row["count"] for row in cursor.fetchall() if row["count"] > 0}

    async def update_alert(
        self,
        alert_id: int,
        user_id: int,
        *,
        name: str | None = None,
        query: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Alert | None:
        alert = await self.get_alert(alert_id, user_id)
        if not alert:
            return None

        new_name = name if name is not None else alert.name
        new_query = query if query is not None else alert.query
        new_params = params if params is not None else alert.params
        new_params = self._normalize_params(new_params)

        if self._use_postgres:
            async with self._db() as conn:
                await conn.execute(
                    """
                    UPDATE alerts
                    SET name = $1, query = $2, params_json = $3
                    WHERE id = $4 AND user_id = $5
                    """,
                    new_name, new_query, json.dumps(new_params, ensure_ascii=False), alert_id, user_id,
                )
        else:
            conn = self._sqlite_conn()
            conn.execute(
                """
                UPDATE alerts
                SET name = ?, query = ?, params_json = ?
                WHERE id = ? AND user_id = ?
                """,
                (new_name, new_query, json.dumps(new_params, ensure_ascii=False), alert_id, user_id)
            )
            conn.commit()

        return Alert(
            id=alert_id,
            user_id=user_id,
            name=new_name,
            query=new_query,
            params=new_params,
            active=alert.active,
            created_at=alert.created_at,
        )

    async def clear_seen(self, alert_id: int) -> None:
        if self._use_postgres:
            async with self._db() as conn:
                await conn.execute("DELETE FROM seen_ads WHERE alert_id = $1", alert_id)
        else:
            conn = self._sqlite_conn()
            conn.execute("DELETE FROM seen_ads WHERE alert_id = ?", (alert_id,))
            conn.commit()

    async def count_seen(self, alert_id: int) -> int:
        if self._use_postgres:
            async with self._db() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM seen_ads WHERE alert_id = $1",
                    alert_id,
                )
            return count or 0
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute(
                "SELECT COUNT(*) FROM seen_ads WHERE alert_id = ?",
                (alert_id,)
            )
            return cursor.fetchone()[0] or 0

    async def mark_seen(self, alert_id: int, ad_ids: list[int]) -> None:
        if not ad_ids:
            return
        
        if self._use_postgres:
            async with self._db() as conn:
                if len(ad_ids) > 100:
                    await conn.executemany(
                        "INSERT INTO seen_ads (alert_id, ad_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        [(alert_id, ad_id) for ad_id in ad_ids],
                    )
                else:
                    for ad_id in ad_ids:
                        await conn.execute(
                            "INSERT INTO seen_ads (alert_id, ad_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                            alert_id, ad_id,
                        )
        else:
            conn = self._sqlite_conn()
            conn.executemany(
                "INSERT OR IGNORE INTO seen_ads (alert_id, ad_id) VALUES (?, ?)",
                [(alert_id, ad_id) for ad_id in ad_ids]
            )
            conn.commit()

    async def filter_unseen(self, alert_id: int, ad_ids: list[int]) -> list[int]:
        if not ad_ids:
            return []
        
        if self._use_postgres:
            async with self._db() as conn:
                rows = await conn.fetch(
                    """
                    SELECT ad_id FROM seen_ads
                    WHERE alert_id = $1 AND ad_id = ANY($2::int[])
                    """,
                    alert_id, ad_ids,
                )
                seen = {row["ad_id"] for row in rows}
        else:
            conn = self._sqlite_conn()
            placeholders = ','.join(['?'] * len(ad_ids))
            cursor = conn.execute(
                f"SELECT ad_id FROM seen_ads WHERE alert_id = ? AND ad_id IN ({placeholders})",
                (alert_id, *ad_ids)
            )
            seen = {row["ad_id"] for row in cursor.fetchall()}
        
        return [ad_id for ad_id in ad_ids if ad_id not in seen]

    async def seed_seen(self, alert_id: int, ad_ids: list[int]) -> None:
        await self.mark_seen(alert_id, ad_ids)

    async def prune_old_seen(self, days: int = 30) -> int:
        if self._use_postgres:
            async with self._db() as conn:
                result = await conn.execute(
                    "DELETE FROM seen_ads WHERE seen_at < NOW() - INTERVAL '$1 DAYS'",
                    days,
                )
                return int(result.split()[1]) if result and "DELETE" in result else 0
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute(
                "DELETE FROM seen_ads WHERE seen_at < datetime('now', ?)",
                (f'-{days} days',)
            )
            conn.commit()
            return cursor.rowcount

    # --- Вспомогательные методы для конвертации ---

    def _row_to_alert(self, row: Record) -> Alert:
        params = json.loads(row["params_json"] or "{}")
        return Alert(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            query=row["query"] or "",
            params=params,
            active=bool(row["active"]),
            created_at=row["created_at"].isoformat() if row["created_at"] else None,
        )

    def _row_to_alert_sqlite(self, row: sqlite3.Row) -> Alert:
        params = json.loads(row["params_json"] or "{}")
        return Alert(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            query=row["query"] or "",
            params=params,
            active=bool(row["active"]),
            created_at=row["created_at"],
        )

    def _row_to_user(self, row: Record) -> "User":
        from bot.users import User, UserSettings

        return User(
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            role=row["role"] or "user",
            active=bool(row["active"]),
            settings=UserSettings.from_dict(json.loads(row["settings_json"] or "{}")),
        )

    def _row_to_user_sqlite(self, row: sqlite3.Row) -> "User":
        from bot.users import User, UserSettings

        return User(
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            role=row["role"] or "user",
            active=bool(row["active"]),
            settings=UserSettings.from_dict(json.loads(row["settings_json"] or "{}")),
        )

    # --- Методы для пользователей ---

    async def get_user(self, user_id: int) -> "User | None":
        if self._use_postgres:
            async with self._db() as conn:
                row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            return self._row_to_user(row) if row else None
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return self._row_to_user_sqlite(row) if row else None

    async def list_users(self, *, active_only: bool = False) -> list["User"]:
        query = "SELECT * FROM users"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY role DESC, created_at ASC"
        
        if self._use_postgres:
            async with self._db() as conn:
                rows = await conn.fetch(query)
            return [self._row_to_user(row) for row in rows]
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute(query)
            return [self._row_to_user_sqlite(row) for row in cursor.fetchall()]

    async def count_user_alerts(self, user_id: int) -> int:
        if self._use_postgres:
            async with self._db() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM alerts WHERE user_id = $1",
                    user_id,
                )
            return count or 0
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE user_id = ?",
                (user_id,)
            )
            return cursor.fetchone()[0] or 0

    async def upsert_user(
        self,
        user_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        role: str | None = None,
        active: bool | None = None,
    ) -> "User":
        existing = await self.get_user(user_id)
        
        if self._use_postgres:
            async with self._db() as conn:
                if existing:
                    await conn.execute(
                        """
                        UPDATE users
                        SET username = COALESCE($1, username),
                            first_name = COALESCE($2, first_name),
                            last_name = COALESCE($3, last_name),
                            role = COALESCE($4, role),
                            active = COALESCE($5, active),
                            last_seen_at = NOW()
                        WHERE user_id = $6
                        """,
                        username,
                        first_name,
                        last_name,
                        role,
                        1 if active else 0 if active is not None else None,
                        user_id,
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO users (user_id, username, first_name, last_name, role, active, last_seen_at)
                        VALUES ($1, $2, $3, $4, $5, $6, NOW())
                        """,
                        user_id,
                        username,
                        first_name,
                        last_name,
                        role or "user",
                        1 if active is None else (1 if active else 0),
                    )
        else:
            conn = self._sqlite_conn()
            if existing:
                conn.execute(
                    """
                    UPDATE users
                    SET username = COALESCE(?, username),
                        first_name = COALESCE(?, first_name),
                        last_name = COALESCE(?, last_name),
                        role = COALESCE(?, role),
                        active = COALESCE(?, active),
                        last_seen_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                    """,
                    (username, first_name, last_name, role, 
                     1 if active else 0 if active is not None else None, user_id)
                )
            else:
                conn.execute(
                    """
                    INSERT INTO users (user_id, username, first_name, last_name, role, active, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (user_id, username, first_name, last_name, role or "user",
                     1 if active is None else (1 if active else 0))
                )
            conn.commit()
        
        user = await self.get_user(user_id)
        assert user is not None
        return user

    async def touch_user(self, user_id: int, **profile: str | None) -> None:
        await self.upsert_user(
            user_id,
            username=profile.get("username"),
            first_name=profile.get("first_name"),
            last_name=profile.get("last_name"),
        )

    async def set_user_active(self, user_id: int, active: bool) -> bool:
        if self._use_postgres:
            async with self._db() as conn:
                result = await conn.execute(
                    "UPDATE users SET active = $1 WHERE user_id = $2",
                    1 if active else 0, user_id,
                )
                return result != "UPDATE 0"
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute(
                "UPDATE users SET active = ? WHERE user_id = ?",
                (1 if active else 0, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    async def set_user_role(self, user_id: int, role: str) -> bool:
        if self._use_postgres:
            async with self._db() as conn:
                result = await conn.execute(
                    "UPDATE users SET role = $1 WHERE user_id = $2",
                    role, user_id,
                )
                return result != "UPDATE 0"
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute(
                "UPDATE users SET role = ? WHERE user_id = ?",
                (role, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    async def delete_user(self, user_id: int) -> bool:
        if self._use_postgres:
            async with self._db() as conn:
                row = await conn.fetchrow("SELECT 1 FROM users WHERE user_id = $1", user_id)
                if not row:
                    return False
                await conn.execute("DELETE FROM alerts WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM notification_messages WHERE user_id = $1", user_id)
                result = await conn.execute("DELETE FROM users WHERE user_id = $1", user_id)
                return result != "DELETE 0"
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            if not cursor.fetchone():
                return False
            conn.execute("DELETE FROM alerts WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM notification_messages WHERE user_id = ?", (user_id,))
            cursor = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    async def update_user_settings(self, user_id: int, settings: dict[str, Any]) -> "User | None":
        async with self._settings_locks[user_id]:
            user = await self.get_user(user_id)
            if not user:
                return None
            merged = {**user.settings.to_dict(), **settings}
            if isinstance(settings.get("notification_display"), dict):
                merged["notification_display"] = {
                    **user.settings.notification_display.to_dict(),
                    **settings["notification_display"],
                }
            if settings.get("poll_interval") is None and "poll_interval" in settings:
                merged.pop("poll_interval", None)
            if settings.get("ui_message_id") is None and "ui_message_id" in settings:
                merged.pop("ui_message_id", None)
            for key, value in list(merged.items()):
                if value is None:
                    merged.pop(key, None)
            
            if self._use_postgres:
                async with self._db() as conn:
                    await conn.execute(
                        "UPDATE users SET settings_json = $1 WHERE user_id = $2",
                        json.dumps(merged, ensure_ascii=False), user_id,
                    )
            else:
                conn = self._sqlite_conn()
                conn.execute(
                    "UPDATE users SET settings_json = ? WHERE user_id = ?",
                    (json.dumps(merged, ensure_ascii=False), user_id)
                )
                conn.commit()
            return await self.get_user(user_id)

    async def is_user_allowed(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return user is not None and user.active

    # --- Конфиг ---

    async def get_bot_config(self, key: str) -> str | None:
        if self._use_postgres:
            async with self._db() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM bot_config WHERE key = $1",
                    key,
                )
            return row["value"] if row else None
        else:
            conn = self._sqlite_conn()
            cursor = conn.execute("SELECT value FROM bot_config WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    async def set_bot_config(self, key: str, value: str) -> None:
        if self._use_postgres:
            async with self._db() as conn:
                await conn.execute(
                    """
                    INSERT INTO bot_config (key, value)
                    VALUES ($1, $2)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    key, value,
                )
        else:
            conn = self._sqlite_conn()
            conn.execute(
                """
                INSERT INTO bot_config (key, value)
                VALUES (?, ?)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, value)
            )
            conn.commit()

    async def get_access_mode(self, default: str) -> str:
        stored = await self.get_bot_config(ACCESS_MODE_KEY)
        return normalize_access_mode(stored, default=normalize_access_mode(default))

    async def set_access_mode(self, mode: str, *, default: str) -> str:
        normalized = normalize_access_mode(mode, default=normalize_access_mode(default))
        await self.set_bot_config(ACCESS_MODE_KEY, normalized)
        return normalized

    # --- ДЛЯ БЭКАПА В NEON ---

    async def get_all_data(self) -> dict:
        """Получение всех данных из SQLite для бэкапа в Neon."""
        if self._use_postgres:
            # Если используем PostgreSQL, возвращаем данные из него
            async with self._db() as conn:
                users = await conn.fetch("SELECT * FROM users")
                alerts = await conn.fetch("SELECT * FROM alerts")
                seen_ads = await conn.fetch("SELECT * FROM seen_ads")
                notifications = await conn.fetch(
                    "SELECT * FROM notification_messages WHERE created_at > NOW() - INTERVAL '1 day'"
                )
                config = await conn.fetch("SELECT * FROM bot_config")
                return {
                    'users': users,
                    'alerts': alerts,
                    'seen_ads': seen_ads,
                    'notification_messages': notifications,
                    'bot_config': config,
                }
        else:
            # Из SQLite
            conn = self._sqlite_conn()
            return {
                'users': conn.execute("SELECT * FROM users").fetchall(),
                'alerts': conn.execute("SELECT * FROM alerts").fetchall(),
                'seen_ads': conn.execute("SELECT * FROM seen_ads").fetchall(),
                'notification_messages': conn.execute(
                    "SELECT * FROM notification_messages WHERE created_at > datetime('now', '-1 day')"
                ).fetchall(),
                'bot_config': conn.execute("SELECT * FROM bot_config").fetchall(),
            }


def parse_kufar_url(url: str) -> tuple[str, dict[str, str]]:
    """Extract search query and API params from a kufar.by search URL."""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url.strip())
    if "kufar.by" not in parsed.netloc:
        raise ValueError("Это не ссылка с kufar.by")

    qs = parse_qs(parsed.query)
    params: dict[str, str] = {}
    query = ""

    skip_keys = {"query", "cursor", "page", "size", "lang", "sort"}
    for key, values in qs.items():
        if not values:
            continue
        if key == "query":
            query = values[0]
        elif key not in skip_keys:
            params[key] = values[0]

    if params.get("prc"):
        from bot.price import normalize_prc

        params["prc"] = normalize_prc(params["prc"]) or params["prc"]

    path_parts = [p for p in parsed.path.split("/") if p]
    for part in path_parts:
        if part.startswith("r~"):
            from bot.locations import region_id_from_slug

            region_id = region_id_from_slug(part[2:])
            if region_id is not None:
                params.setdefault("rgn", str(region_id))
        elif part.isdigit() and len(part) >= 4 and not params.get("cat"):
            params.setdefault("cat", part)

    return query, params


def format_alert_summary(alert: Alert) -> str:
    from bot.ui import format_alert_card

    return format_alert_card(alert)