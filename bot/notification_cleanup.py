from __future__ import annotations

import logging

from aiogram import Bot

from bot.database import Database

logger = logging.getLogger(__name__)


async def purge_notifications(
    bot: Bot,
    db: Database,
    user_id: int,
    *,
    alert_id: int | None = None,
) -> int:
    rows = await db.pop_notification_messages(user_id, alert_id=alert_id)
    deleted = 0
    for chat_id, message_id in rows:
        try:
            await bot.delete_message(chat_id, message_id)
            deleted += 1
        except Exception:
            logger.debug(
                "Could not delete notification %s in chat %s",
                message_id,
                chat_id,
                exc_info=True,
            )
    return deleted
