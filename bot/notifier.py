from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)

CAPTION_MAX = 1024
MESSAGE_MAX = 4096


def truncate_text(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


async def send_ad_notification(
    bot: Bot,
    user_id: int,
    text: str,
    image_urls: list[str],
    download_image,
) -> str | None:
    """
    Send notification to user. Returns None on success, error reason string on failure.
    Tries photo by URL, then downloaded bytes, then plain text.
    """
    caption = truncate_text(text, CAPTION_MAX)
    message_text = truncate_text(text, MESSAGE_MAX)

    for image_url in image_urls:
        if await _try_send_photo_url(bot, user_id, image_url, caption):
            return None

        image_data = await download_image(image_url)
        if image_data and await _try_send_photo_bytes(bot, user_id, image_data, caption):
            return None

    if await _try_send_message(bot, user_id, message_text):
        return None

    return "send_failed"


async def _try_send_photo_url(bot: Bot, user_id: int, image_url: str, caption: str) -> bool:
    try:
        await bot.send_photo(user_id, photo=image_url, caption=caption, parse_mode="HTML")
        return True
    except TelegramBadRequest as exc:
        logger.debug("Photo URL failed for user %s: %s", user_id, exc)
        return False
    except TelegramForbiddenError:
        raise
    except Exception:
        logger.debug("Photo URL unexpected error for user %s", user_id, exc_info=True)
        return False


async def _try_send_photo_bytes(bot: Bot, user_id: int, image_data: bytes, caption: str) -> bool:
    try:
        photo = BufferedInputFile(image_data, filename="photo.jpg")
        await bot.send_photo(user_id, photo=photo, caption=caption, parse_mode="HTML")
        return True
    except TelegramBadRequest as exc:
        logger.debug("Photo upload failed for user %s: %s", user_id, exc)
        return False
    except TelegramForbiddenError:
        raise
    except Exception:
        logger.debug("Photo upload unexpected error for user %s", user_id, exc_info=True)
        return False


async def _try_send_message(bot: Bot, user_id: int, text: str) -> bool:
    try:
        await bot.send_message(
            user_id,
            text,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
        return True
    except TelegramBadRequest as exc:
        logger.warning("Message failed for user %s: %s", user_id, exc)
        return False
    except TelegramForbiddenError:
        raise
    except Exception:
        logger.exception("Message unexpected error for user %s", user_id)
        return False
