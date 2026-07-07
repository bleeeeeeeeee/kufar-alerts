from __future__ import annotations

from collections import deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from bot.access import get_telegram_user, is_access_exempt, profile_from_user
from bot.config import Settings
from bot.database import Database
from bot.kufar import KufarClient


class InjectMiddleware(BaseMiddleware):
    def __init__(self, db: Database, kufar: KufarClient, settings: Settings) -> None:
        self.db = db
        self.kufar = kufar
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        data["kufar"] = self.kufar
        data["app_settings"] = self.settings
        return await handler(event, data)


class AccessMiddleware(BaseMiddleware):
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def _resolve_user(self, tg_user) -> Any | None:
        user = await self.db.get_user(tg_user.id)
        if user and user.active:
            await self.db.touch_user(tg_user.id, **profile_from_user(tg_user))
            return await self.db.get_user(tg_user.id)

        if tg_user.id in self.settings.admin_user_ids:
            return await self.db.upsert_user(
                tg_user.id,
                **profile_from_user(tg_user),
                role="admin",
                active=True,
            )

        if self.settings.access_mode == "open":
            return await self.db.upsert_user(
                tg_user.id,
                **profile_from_user(tg_user),
                role="user",
                active=True,
            )

        if user and not user.active:
            return None

        return None

    async def _send_denied(self, event: TelegramObject, tg_user) -> None:
        text = (
            "🔒 <b>Нет доступа к боту</b>\n\n"
            "Бот работает по приглашениям. Попросите администратора добавить вас.\n\n"
            f"Ваш Telegram ID: <code>{tg_user.id}</code>\n"
            f"{'@' + tg_user.username if tg_user.username else ''}"
        )
        if isinstance(event, CallbackQuery):
            await event.answer("Нет доступа", show_alert=True)
            await event.message.answer(text, parse_mode="HTML")
        elif isinstance(event, Message):
            await event.answer(text, parse_mode="HTML")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = get_telegram_user(event)
        if tg_user is None:
            return await handler(event, data)

        user = await self._resolve_user(tg_user)
        if user:
            data["user"] = user
            return await handler(event, data)

        if is_access_exempt(event):
            data["user"] = None
            return await handler(event, data)

        await self._send_denied(event, tg_user)
        return None


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
