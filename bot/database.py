from __future__ import annotations

import json
import logging
from asyncio import Lock
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import asyncpg
from asyncpg import Connection, Pool, Record

from bot.access_config import ACCESS_MODE_KEY, normalize_access_mode

logger = logging.getLogger(__name__)

# Схема таблиц для PostgreSQL
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
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: Pool | None = None
        self._ready = False
        self._settings_locks: dict[int, Lock] = defaultdict(Lock)

    async def init(self, admin_user_ids: tuple[int, ...] = ()) -> None:
        """Инициализация пула соединений и создание таблиц."""
        logger.info("Connecting to PostgreSQL database...")
        
        # Создаем SSL-контекст с отключенной проверкой сертификата
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Создаем пул соединений
        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=1,
            max_size=5,
            timeout=60.0,
            ssl=ssl_context,
        )
        
        async with self._db() as conn:
            await conn.execute(SCHEMA)
            logger.info("Database schema created/verified")

        await self._bootstrap_users(admin_user_ids)
        alerts, seen = await self.stats()
        users = await self.count_users()
        logger.info("Database ready: %s alerts, %s seen, %s users", alerts, seen, users)
        self._ready = True

    async def count_users(self) -> int:
        async with self._db() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) FROM users")
        return row[0] if row else 0

    async def _bootstrap_users(self, admin_user_ids: tuple[int, ...]) -> None:
        if not admin_user_ids:
            return
        async with self._db() as conn:
            # Добавляем администраторов
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
            # Активируем пользователей, у которых есть подписки
            await conn.execute(
                """
                UPDATE users 
                SET active = 1 
                WHERE user_id IN (SELECT DISTINCT user_id FROM alerts)
                """
            )

    async def stats(self) -> tuple[int, int]:
        async with self._db() as conn:
            alerts = await conn.fetchval("SELECT COUNT(*) FROM alerts")
            seen = await conn.fetchval("SELECT COUNT(*) FROM seen_ads")
        return alerts or 0, seen or 0

    @asynccontextmanager
    async def _db(self) -> AsyncIterator[Connection]:
        """Получение соединения из пула."""
        if not self.pool:
            raise RuntimeError("Database not initialized")
        async with self.pool.acquire() as conn:
            yield conn

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
            created_at = row["created_at"]
        logger.info("Created alert %s for user %s", alert_id, user_id)
        alert = await self.get_alert(alert_id)
        assert alert is not None
        return alert

    async def get_user_alerts(self, user_id: int) -> list[Alert]:
        async with self._db() as conn:
            rows = await conn.fetch(
                "SELECT * FROM alerts WHERE user_id = $1 ORDER BY id DESC",
                user_id,
            )
        return [self._row_to_alert(row) for row in rows]

    async def get_active_alerts(self) -> list[Alert]:
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

    async def get_alert(self, alert_id: int, user_id: int | None = None) -> Alert | None:
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

    async def set_alert_active(self, alert_id: int, user_id: int, active: bool) -> bool:
        async with self._db() as conn:
            result = await conn.execute(
                "UPDATE alerts SET active = $1 WHERE id = $2 AND user_id = $3",
                1 if active else 0, alert_id, user_id,
            )
            return result != "UPDATE 0"

    async def delete_alert(self, alert_id: int, user_id: int) -> bool:
        async with self._db() as conn:
            # Сначала удаляем связанные записи
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

    async def record_notification(
        self,
        user_id: int,
        alert_id: int,
        chat_id: int,
        message_id: int,
    ) -> None:
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

    async def forget_notification(self, user_id: int, message_id: int) -> None:
        async with self._db() as conn:
            await conn.execute(
                "DELETE FROM notification_messages WHERE user_id = $1 AND message_id = $2",
                user_id, message_id,
            )

    async def pop_notification_messages(
        self,
        user_id: int,
        *,
        alert_id: int | None = None,
    ) -> list[tuple[int, int]]:
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

    async def count_notification_messages(
        self,
        user_id: int,
        *,
        alert_id: int | None = None,
    ) -> int:
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

    async def get_notification_counts_by_alert(self, user_id: int) -> dict[int, int]:
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

        async with self._db() as conn:
            await conn.execute(
                """
                UPDATE alerts
                SET name = $1, query = $2, params_json = $3
                WHERE id = $4 AND user_id = $5
                """,
                new_name, new_query, json.dumps(new_params, ensure_ascii=False), alert_id, user_id,
            )

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
        async with self._db() as conn:
            await conn.execute("DELETE FROM seen_ads WHERE alert_id = $1", alert_id)

    async def count_seen(self, alert_id: int) -> int:
        async with self._db() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM seen_ads WHERE alert_id = $1",
                alert_id,
            )
        return count or 0

    async def mark_seen(self, alert_id: int, ad_ids: list[int]) -> None:
        if not ad_ids:
            return
        async with self._db() as conn:
            # Используем COPY для массовой вставки, если много данных
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

    async def filter_unseen(self, alert_id: int, ad_ids: list[int]) -> list[int]:
        if not ad_ids:
            return []
        async with self._db() as conn:
            # Используем ANY для эффективного поиска
            rows = await conn.fetch(
                """
                SELECT ad_id FROM seen_ads
                WHERE alert_id = $1 AND ad_id = ANY($2::int[])
                """,
                alert_id, ad_ids,
            )
            seen = {row["ad_id"] for row in rows}
        return [ad_id for ad_id in ad_ids if ad_id not in seen]

    async def seed_seen(self, alert_id: int, ad_ids: list[int]) -> None:
        await self.mark_seen(alert_id, ad_ids)

    async def prune_old_seen(self, days: int = 30) -> int:
        async with self._db() as conn:
            result = await conn.execute(
                "DELETE FROM seen_ads WHERE seen_at < NOW() - INTERVAL '$1 DAYS'",
                days,
            )
            # Парсим результат для получения количества удаленных строк
            return int(result.split()[1]) if result and "DELETE" in result else 0

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

    async def get_user(self, user_id: int) -> "User | None":
        async with self._db() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return self._row_to_user(row) if row else None

    async def list_users(self, *, active_only: bool = False) -> list["User"]:
        query = "SELECT * FROM users"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY role DESC, created_at ASC"
        async with self._db() as conn:
            rows = await conn.fetch(query)
        return [self._row_to_user(row) for row in rows]

    async def count_user_alerts(self, user_id: int) -> int:
        async with self._db() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM alerts WHERE user_id = $1",
                user_id,
            )
        return count or 0

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
        async with self._db() as conn:
            result = await conn.execute(
                "UPDATE users SET active = $1 WHERE user_id = $2",
                1 if active else 0, user_id,
            )
            return result != "UPDATE 0"

    async def set_user_role(self, user_id: int, role: str) -> bool:
        async with self._db() as conn:
            result = await conn.execute(
                "UPDATE users SET role = $1 WHERE user_id = $2",
                role, user_id,
            )
            return result != "UPDATE 0"

    async def delete_user(self, user_id: int) -> bool:
        async with self._db() as conn:
            row = await conn.fetchrow("SELECT 1 FROM users WHERE user_id = $1", user_id)
            if not row:
                return False
            await conn.execute("DELETE FROM alerts WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM notification_messages WHERE user_id = $1", user_id)
            result = await conn.execute("DELETE FROM users WHERE user_id = $1", user_id)
            return result != "DELETE 0"

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
            async with self._db() as conn:
                await conn.execute(
                    "UPDATE users SET settings_json = $1 WHERE user_id = $2",
                    json.dumps(merged, ensure_ascii=False), user_id,
                )
            return await self.get_user(user_id)

    async def is_user_allowed(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return user is not None and user.active

    async def get_bot_config(self, key: str) -> str | None:
        async with self._db() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM bot_config WHERE key = $1",
                key,
            )
        return row["value"] if row else None

    async def set_bot_config(self, key: str, value: str) -> None:
        async with self._db() as conn:
            await conn.execute(
                """
                INSERT INTO bot_config (key, value)
                VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                key, value,
            )

    async def get_access_mode(self, default: str) -> str:
        stored = await self.get_bot_config(ACCESS_MODE_KEY)
        return normalize_access_mode(stored, default=normalize_access_mode(default))

    async def set_access_mode(self, mode: str, *, default: str) -> str:
        normalized = normalize_access_mode(mode, default=normalize_access_mode(default))
        await self.set_bot_config(ACCESS_MODE_KEY, normalized)
        return normalized


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