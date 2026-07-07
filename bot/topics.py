from __future__ import annotations

import logging
from typing import Any

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)

NOTIFICATION_TOPIC_NAME = "Уведомления"
TOPIC_WELCOME_TEXT = (
    "📬 <b>Топик уведомлений</b>\n\n"
    "Сюда будут приходить новые объявления с Kufar.\n"
    "Меню и команды бота останутся в общем чате."
)


class TopicSetupError(Exception):
    def __init__(self, message: str, *, user_hint: str | None = None) -> None:
        super().__init__(message)
        self.user_hint = user_hint or message


async def bot_topics_enabled(bot: Bot) -> bool:
    me = await bot.get_me()
    return bool(getattr(me, "has_topics_enabled", False))


async def telegram_api(bot: Bot, method: str, **params: Any) -> Any:
    url = f"https://api.telegram.org/bot{bot.token}/{method}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=params) as response:
            payload = await response.json()
    if not payload.get("ok"):
        description = str(payload.get("description") or "Telegram API error")
        raise TopicSetupError(description)
    return payload.get("result")


async def create_notification_topic(bot: Bot, user_id: int) -> int:
    if not await bot_topics_enabled(bot):
        raise TopicSetupError(
            "У бота не включены темы в личных чатах",
            user_hint=(
                "Сначала включите темы для бота в @BotFather:\n"
                "откройте бота → <b>Bot Settings</b> → <b>Topics</b> → включите."
            ),
        )

    try:
        result = await telegram_api(
            bot,
            "createForumTopic",
            chat_id=user_id,
            name=NOTIFICATION_TOPIC_NAME,
            icon_color=7322096,
        )
    except TopicSetupError as exc:
        if "BOT_FORUM_CREATE_FORBIDDEN" in str(exc):
            raise TopicSetupError(
                str(exc),
                user_hint=(
                    "Telegram не разрешил создать тему.\n\n"
                    "В @BotFather откройте бота → <b>Bot Settings</b> → <b>Topics</b> "
                    "и включите темы в личных чатах."
                ),
            ) from exc
        raise

    topic_id = int(result["message_thread_id"])
    logger.info("Created notification topic %s for user %s", topic_id, user_id)
    return topic_id


def _topic_param_attempts(topic_id: int) -> list[dict[str, int]]:
    return [
        {"direct_messages_topic_id": topic_id},
        {"message_thread_id": topic_id},
    ]


async def send_text_to_topic(
    bot: Bot,
    user_id: int,
    text: str,
    topic_id: int,
    *,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
) -> None:
    last_error: Exception | None = None
    for extra in _topic_param_attempts(topic_id):
        try:
            await telegram_api(
                bot,
                "sendMessage",
                chat_id=user_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                **extra,
            )
            return
        except TopicSetupError as exc:
            last_error = exc
            logger.debug("sendMessage to topic failed (%s): %s", extra, exc)
    if last_error:
        raise last_error


async def send_photo_to_topic(
    bot: Bot,
    user_id: int,
    photo: str | BufferedInputFile,
    topic_id: int,
    *,
    caption: str | None = None,
    parse_mode: str = "HTML",
) -> None:
    last_error: Exception | None = None
    for extra in _topic_param_attempts(topic_id):
        try:
            if isinstance(photo, BufferedInputFile):
                # Raw API upload is awkward; use aiogram for file uploads.
                await bot.send_photo(
                    user_id,
                    photo=photo,
                    caption=caption,
                    parse_mode=parse_mode,
                    **extra,
                )
            else:
                await telegram_api(
                    bot,
                    "sendPhoto",
                    chat_id=user_id,
                    photo=photo,
                    caption=caption,
                    parse_mode=parse_mode,
                    **extra,
                )
            return
        except (TopicSetupError, TelegramBadRequest) as exc:
            last_error = exc
            logger.debug("sendPhoto to topic failed (%s): %s", extra, exc)
    if last_error:
        raise last_error
