from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseMiddleware):
    """Catch unexpected exceptions so one bad update does not crash the bot."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception:
            logger.exception("Unhandled exception while processing update")
            return None


async def safe_answer(callback: CallbackQuery, *args: Any, **kwargs: Any) -> bool:
    try:
        await callback.answer(*args, **kwargs)
        return True
    except Exception:
        logger.debug("callback.answer failed", exc_info=True)
        return False


async def safe_edit_text(message: Any, text: str, **kwargs: Any) -> bool:
    try:
        await message.edit_text(text, **kwargs)
        return True
    except Exception:
        logger.debug("message.edit_text failed", exc_info=True)
        return False
