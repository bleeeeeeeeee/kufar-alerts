from __future__ import annotations

from typing import Any

from aiogram.types import CallbackQuery, Message, TelegramObject, Update, User as TgUser


def get_telegram_user(event: TelegramObject) -> TgUser | None:
    if isinstance(event, Message):
        return event.from_user
    if isinstance(event, CallbackQuery):
        return event.from_user
    if isinstance(event, Update):
        if event.message:
            return event.message.from_user
        if event.callback_query:
            return event.callback_query.from_user
    return None


def profile_from_user(user: TgUser) -> dict[str, str | None]:
    return {
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


def is_access_exempt(event: TelegramObject) -> bool:
    """Allow /start and settings access-denied flows without full access."""
    if isinstance(event, CallbackQuery):
        data = event.data or ""
        return data in ("access:info",)
    if isinstance(event, Message):
        text = (event.text or "").strip().lower()
        return text in ("/start", "/help") or text.startswith("/start ")
    return False
