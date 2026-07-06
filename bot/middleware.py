from __future__ import annotations

from collections import deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from bot.database import Database
from bot.kufar import KufarClient


class InjectMiddleware(BaseMiddleware):
    def __init__(self, db: Database, kufar: KufarClient) -> None:
        self.db = db
        self.kufar = kufar

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        data["kufar"] = self.kufar
        return await handler(event, data)


class DedupMiddleware(BaseMiddleware):
    """Ignore duplicate Telegram updates (e.g. during deploy overlap)."""

    def __init__(self, max_size: int = 2000) -> None:
        self._seen: set[int] = set()
        self._order: deque[int] = deque()
        self._max_size = max_size

    def _remember(self, update_id: int) -> bool:
        if update_id in self._seen:
            return False
        self._seen.add(update_id)
        self._order.append(update_id)
        while len(self._order) > self._max_size:
            old = self._order.popleft()
            self._seen.discard(old)
        return True

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        update: Update | None = data.get("event_update")
        if update is not None and not self._remember(update.update_id):
            return None
        return await handler(event, data)
