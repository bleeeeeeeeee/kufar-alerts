from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import parse_qs, urlparse

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS seen_ads (
    alert_id INTEGER NOT NULL,
    ad_id INTEGER NOT NULL,
    seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (alert_id, ad_id),
    FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE
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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_active ON users(active);
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
        from bot.price import prc_for_api

        params = {k: v for k, v in self.params.items() if not str(k).startswith("_")}
        if "prc" in params:
            api_prc = prc_for_api(params["prc"])
            if api_prc:
                params["prc"] = api_prc
            else:
                params.pop("prc")
        params["query"] = self.query
        return params


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._ready = False

    async def init(self, admin_user_ids: tuple[int, ...] = ()) -> None:
        db_path = Path(self.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Database path: %s (exists=%s)", self.path, db_path.exists())

        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.executescript(SCHEMA)
            await db.commit()

        await self._bootstrap_users(admin_user_ids)

        alerts, seen = await self.stats()
        users = await self.count_users()
        logger.info("Database ready: %s alerts, %s seen, %s users", alerts, seen, users)
        self._ready = True

    async def count_users(self) -> int:
        async with self._db() as db:
            row = await (await db.execute("SELECT COUNT(*) FROM users")).fetchone()
        return int(row[0])

    async def _bootstrap_users(self, admin_user_ids: tuple[int, ...]) -> None:
        async with self._db() as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO users (user_id, active)
                SELECT DISTINCT user_id, 1 FROM alerts
                """
            )
            for admin_id in admin_user_ids:
                await db.execute(
                    """
                    INSERT INTO users (user_id, role, active)
                    VALUES (?, 'admin', 1)
                    ON CONFLICT(user_id) DO UPDATE SET role = 'admin', active = 1
                    """,
                    (admin_id,),
                )
            await db.commit()

    async def stats(self) -> tuple[int, int]:
        async with self._db() as db:
            alerts = (await (await db.execute("SELECT COUNT(*) FROM alerts")).fetchone())[0]
            seen = (await (await db.execute("SELECT COUNT(*) FROM seen_ads")).fetchone())[0]
        return int(alerts), int(seen)

    @asynccontextmanager
    async def _db(self) -> AsyncIterator[aiosqlite.Connection]:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            yield db

    @staticmethod
    def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
        params = {k: v for k, v in params.items() if not str(k).startswith("_")}
        if params.get("prc"):
            from bot.price import normalize_prc

            normalized = normalize_prc(params["prc"])
            if normalized:
                params["prc"] = normalized
            else:
                params.pop("prc", None)
        return params

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
        async with self._db() as db:
            cursor = await db.execute(
                """
                INSERT INTO alerts (user_id, name, query, params_json, active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, name, query, json.dumps(params, ensure_ascii=False), 1 if active else 0),
            )
            await db.commit()
            alert_id = cursor.lastrowid
        logger.info("Created alert %s for user %s", alert_id, user_id)
        alert = await self.get_alert(alert_id)
        assert alert is not None
        return alert

    async def get_user_alerts(self, user_id: int) -> list[Alert]:
        async with self._db() as db:
            cursor = await db.execute(
                "SELECT * FROM alerts WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            )
            rows = await cursor.fetchall()
        return [self._row_to_alert(row) for row in rows]

    async def get_active_alerts(self) -> list[Alert]:
        async with self._db() as db:
            cursor = await db.execute(
                """
                SELECT a.* FROM alerts a
                WHERE a.active = 1
                  AND (
                    NOT EXISTS (SELECT 1 FROM users u WHERE u.user_id = a.user_id)
                    OR EXISTS (SELECT 1 FROM users u WHERE u.user_id = a.user_id AND u.active = 1)
                  )
                """
            )
            rows = await cursor.fetchall()
        return [self._row_to_alert(row) for row in rows]

    async def get_alert(self, alert_id: int, user_id: int | None = None) -> Alert | None:
        async with self._db() as db:
            if user_id is not None:
                cursor = await db.execute(
                    "SELECT * FROM alerts WHERE id = ? AND user_id = ?",
                    (alert_id, user_id),
                )
            else:
                cursor = await db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,))
            row = await cursor.fetchone()
        return self._row_to_alert(row) if row else None

    async def set_alert_active(self, alert_id: int, user_id: int, active: bool) -> bool:
        async with self._db() as db:
            cursor = await db.execute(
                "UPDATE alerts SET active = ? WHERE id = ? AND user_id = ?",
                (1 if active else 0, alert_id, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete_alert(self, alert_id: int, user_id: int) -> bool:
        async with self._db() as db:
            await db.execute("DELETE FROM seen_ads WHERE alert_id = ?", (alert_id,))
            cursor = await db.execute(
                "DELETE FROM alerts WHERE id = ? AND user_id = ?",
                (alert_id, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0

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

        async with self._db() as db:
            await db.execute(
                """
                UPDATE alerts
                SET name = ?, query = ?, params_json = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    new_name,
                    new_query,
                    json.dumps(new_params, ensure_ascii=False),
                    alert_id,
                    user_id,
                ),
            )
            await db.commit()

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
        async with self._db() as db:
            await db.execute("DELETE FROM seen_ads WHERE alert_id = ?", (alert_id,))
            await db.commit()

    async def mark_seen(self, alert_id: int, ad_ids: list[int]) -> None:
        if not ad_ids:
            return
        async with self._db() as db:
            await db.executemany(
                "INSERT OR IGNORE INTO seen_ads (alert_id, ad_id) VALUES (?, ?)",
                [(alert_id, ad_id) for ad_id in ad_ids],
            )
            await db.commit()

    async def filter_unseen(self, alert_id: int, ad_ids: list[int]) -> list[int]:
        if not ad_ids:
            return []
        placeholders = ",".join("?" * len(ad_ids))
        async with self._db() as db:
            cursor = await db.execute(
                f"""
                SELECT ad_id FROM seen_ads
                WHERE alert_id = ? AND ad_id IN ({placeholders})
                """,
                [alert_id, *ad_ids],
            )
            seen = {row[0] for row in await cursor.fetchall()}
        return [ad_id for ad_id in ad_ids if ad_id not in seen]

    async def seed_seen(self, alert_id: int, ad_ids: list[int]) -> None:
        await self.mark_seen(alert_id, ad_ids)

    async def prune_old_seen(self, days: int = 30) -> int:
        async with self._db() as db:
            cursor = await db.execute(
                "DELETE FROM seen_ads WHERE seen_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            await db.commit()
            return cursor.rowcount

    def _row_to_alert(self, row: aiosqlite.Row) -> Alert:
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

    def _row_to_user(self, row: aiosqlite.Row) -> "User":
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
        async with self._db() as db:
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
        return self._row_to_user(row) if row else None

    async def list_users(self, *, active_only: bool = False) -> list["User"]:
        query = "SELECT * FROM users"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY role DESC, created_at ASC"
        async with self._db() as db:
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    async def count_user_alerts(self, user_id: int) -> int:
        async with self._db() as db:
            row = await (
                await db.execute("SELECT COUNT(*) FROM alerts WHERE user_id = ?", (user_id,))
            ).fetchone()
        return int(row[0])

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
        async with self._db() as db:
            if existing:
                await db.execute(
                    """
                    UPDATE users
                    SET username = COALESCE(?, username),
                        first_name = COALESCE(?, first_name),
                        last_name = COALESCE(?, last_name),
                        role = COALESCE(?, role),
                        active = COALESCE(?, active),
                        last_seen_at = datetime('now')
                    WHERE user_id = ?
                    """,
                    (
                        username,
                        first_name,
                        last_name,
                        role,
                        None if active is None else (1 if active else 0),
                        user_id,
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO users (user_id, username, first_name, last_name, role, active, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        user_id,
                        username,
                        first_name,
                        last_name,
                        role or "user",
                        1 if active is None else (1 if active else 0),
                    ),
                )
            await db.commit()
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
        async with self._db() as db:
            cursor = await db.execute(
                "UPDATE users SET active = ? WHERE user_id = ?",
                (1 if active else 0, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def set_user_role(self, user_id: int, role: str) -> bool:
        async with self._db() as db:
            cursor = await db.execute(
                "UPDATE users SET role = ? WHERE user_id = ?",
                (role, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def update_user_settings(self, user_id: int, settings: dict[str, Any]) -> "User | None":
        user = await self.get_user(user_id)
        if not user:
            return None
        merged = {**user.settings.to_dict(), **settings}
        for key, value in list(merged.items()):
            if value is None:
                merged.pop(key, None)
        async with self._db() as db:
            await db.execute(
                "UPDATE users SET settings_json = ? WHERE user_id = ?",
                (json.dumps(merged, ensure_ascii=False), user_id),
            )
            await db.commit()
        return await self.get_user(user_id)

    async def is_user_allowed(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return user is not None and user.active


def parse_kufar_url(url: str) -> tuple[str, dict[str, str]]:
    """Extract search query and API params from a kufar.by search URL."""
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
