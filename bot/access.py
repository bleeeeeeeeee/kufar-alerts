from __future__ import annotations

from typing import Any

from aiogram.enums import MessageOriginType
from aiogram.types import CallbackQuery, Message, MessageOriginHiddenUser, MessageOriginUser, TelegramObject, Update, User as TgUser


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


def _command_token(text: str) -> str:
    return (text or "").strip().split()[0].lower()


def is_start_command(text: str | None) -> bool:
    if not text:
        return False
    token = _command_token(text)
    if token in ("/start", "start", "старт"):
        return True
    return token.startswith("/start@")


def is_help_command(text: str | None) -> bool:
    if not text:
        return False
    token = _command_token(text)
    if token in ("/help", "help"):
        return True
    return token.startswith("/help@")


def format_user_identity(tg_user: TgUser) -> str:
    lines = [f"🆔 <code>{tg_user.id}</code>"]
    if tg_user.username:
        lines.append(f"📎 @{tg_user.username}")
    name = " ".join(part for part in (tg_user.first_name, tg_user.last_name) if part)
    if name:
        lines.append(f"👤 {name}")
    return "\n".join(lines)


def format_invite_no_access_text(tg_user: TgUser, *, blocked: bool = False) -> str:
    if blocked:
        header = (
            "🔒 <b>Доступ закрыт</b>\n\n"
            "Администратор заблокировал ваш аккаунт.\n"
            "Если это ошибка — передайте администратору ваши данные:\n\n"
        )
    else:
        header = (
            "👋 <b>Kufar Alerts</b>\n\n"
            "Бот работает по приглашению.\n"
            "Передайте администратору ваши данные:\n\n"
        )
    return header + format_user_identity(tg_user)


def extract_forwarded_user(message: Message) -> tuple[int, dict[str, str | None]] | None:
    """Return Telegram user ID from a forwarded message, if available."""
    if message.forward_from:
        return message.forward_from.id, profile_from_user(message.forward_from)

    origin = message.forward_origin
    if origin is None:
        return None

    if isinstance(origin, MessageOriginUser):
        return origin.sender_user.id, profile_from_user(origin.sender_user)

    if origin.type == MessageOriginType.USER and getattr(origin, "sender_user", None):
        sender = origin.sender_user
        return sender.id, profile_from_user(sender)

    return None


def forwarded_user_error_hint(message: Message) -> str:
    origin = message.forward_origin
    if isinstance(origin, MessageOriginHiddenUser):
        return (
            "У этого пользователя скрыта пересылка — ID недоступен.\n"
            "Попросите его отправить боту /start или введите ID вручную."
        )
    if message.forward_origin or message.forward_from or message.forward_date:
        return (
            "Не удалось определить пользователя из пересылки.\n"
            "Попросите отправить боту /start или введите ID вручную."
        )
    return "Отправьте числовой ID или перешлите сообщение пользователя."


def extract_shared_user_ids(message: Message) -> list[int]:
    ids: list[int] = []
    if message.user_shared and message.user_shared.user_id:
        ids.append(int(message.user_shared.user_id))
    if message.users_shared:
        for user_id in message.users_shared.user_ids or []:
            ids.append(int(user_id))
        for shared in message.users_shared.users or []:
            if shared.user_id:
                ids.append(int(shared.user_id))
    return ids


def is_access_exempt(event: TelegramObject) -> bool:
    """Allow /start and help flows without full access."""
    if isinstance(event, CallbackQuery):
        data = event.data or ""
        return data in ("access:info",)
    if isinstance(event, Message):
        text = event.text or event.caption
        if is_start_command(text) or is_help_command(text):
            return True
    return False
