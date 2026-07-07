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
"""


@dataclass
class Alert:
    id: int
    user_id: int
    name: str
    query: str
    params: dict[str, Any] = field(default_factory=dict)
    active: bool = True

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

    async def init(self) -> None:
        db_path = Path(self.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Database path: %s (exists=%s)", self.path, db_path.exists())

        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.executescript(SCHEMA)
            await db.commit()

        alerts, seen = await self.stats()
        logger.info("Database ready: %s alerts, %s seen records", alerts, seen)
        self._ready = True

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
    ) -> Alert:
        params = self._normalize_params(params or {})
        async with self._db() as db:
            cursor = await db.execute(
                """
                INSERT INTO alerts (user_id, name, query, params_json)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, name, query, json.dumps(params, ensure_ascii=False)),
            )
            await db.commit()
            alert_id = cursor.lastrowid
        logger.info("Created alert %s for user %s", alert_id, user_id)
        return Alert(id=alert_id, user_id=user_id, name=name, query=query, params=params)

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
            cursor = await db.execute("SELECT * FROM alerts WHERE active = 1")
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
        )


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
    if not params.get("cat") and path_parts:
        for part in path_parts:
            if part.isdigit() and len(part) >= 4:
                params.setdefault("cat", part)
                break

    return query, params


from bot.catalog import category_name
from bot.kufar import build_search_url
from bot.locations import format_location


def format_alert_summary(alert: Alert) -> str:
    lines = [f"<b>{alert.name}</b>", f"ID: {alert.id}"]
    if alert.query:
        lines.append(f"🔎 Запрос: <code>{alert.query}</code>")
    if alert.params.get("cat"):
        lines.append(f"📂 {category_name(alert.params['cat'])}")
    location = format_location(alert.params)
    if location:
        lines.append(f"📍 {location}")
    if alert.params.get("prc"):
        from bot.price import format_price_display

        lines.append(f"💰 {format_price_display(alert.params['prc'])}")
    lines.append("✅ Активна" if alert.active else "⏸ На паузе")

    search_params = {k: v for k, v in alert.params.items() if not str(k).startswith("_")}
    url = build_search_url(alert.query, **search_params)
    lines.append(f'🔗 <a href="{url}">Поиск на Kufar</a>')

    return "\n".join(lines)
