from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message

logger = logging.getLogger(__name__)

CAPTION_MAX = 1024
MESSAGE_MAX = 4096
NOTIFY_DELETE_CB = "notify:del"
NOTIFY_CLEAR_MENU = "notify:clear_menu"
NOTIFY_CLEAR_ALL = "notify:clear:all"
NOTIFY_CLEAR_ALERT_PREFIX = "notify:clear:alert:"
NOTIFY_CLEAR_ALERT_MENU_PREFIX = "notify:clear:alert_menu:"


def notification_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=NOTIFY_DELETE_CB)],
        ]
    )


def truncate_text(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def ad_link_preview(url: str, *, large: bool) -> LinkPreviewOptions:
    return LinkPreviewOptions(
        is_disabled=False,
        url=url,
        prefer_large_media=large,
        show_above_text=True,
    )


async def send_ad_notification(
    bot: Bot,
    user_id: int,
    text: str,
    image_urls: list[str],
    download_image,
    *,
    preview_url: str,
    photos_enabled: bool = True,
) -> Message | None:
    """Send notification to the main chat. Returns the sent message on success."""
    caption = truncate_text(text, CAPTION_MAX)
    message_text = truncate_text(text, MESSAGE_MAX)
    keyboard = notification_keyboard()
    preview = ad_link_preview(preview_url, large=photos_enabled)

    sent = await _try_send_message(bot, user_id, message_text, keyboard, preview)
    if sent is not None:
        return sent

    if photos_enabled:
        for image_url in image_urls:
            sent = await _try_send_photo_url(bot, user_id, image_url, caption, keyboard)
            if sent is not None:
                return sent

            image_data = await download_image(image_url)
            if image_data:
                sent = await _try_send_photo_bytes(bot, user_id, image_data, caption, keyboard)
                if sent is not None:
                    return sent

    return None


async def _try_send_photo_url(
    bot: Bot,
    user_id: int,
    image_url: str,
    caption: str,
    keyboard: InlineKeyboardMarkup,
) -> Message | None:
    try:
        return await bot.send_photo(
            user_id,
            photo=image_url,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except TelegramBadRequest as exc:
        logger.debug("Photo URL failed for user %s: %s", user_id, exc)
        return None
    except TelegramForbiddenError:
        raise
    except Exception:
        logger.debug("Photo URL unexpected error for user %s", user_id, exc_info=True)
        return None


async def _try_send_photo_bytes(
    bot: Bot,
    user_id: int,
    image_data: bytes,
    caption: str,
    keyboard: InlineKeyboardMarkup,
) -> Message | None:
    try:
        photo = BufferedInputFile(image_data, filename="photo.jpg")
        return await bot.send_photo(
            user_id,
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except TelegramBadRequest as exc:
        logger.debug("Photo upload failed for user %s: %s", user_id, exc)
        return None
    except TelegramForbiddenError:
        raise
    except Exception:
        logger.debug("Photo upload unexpected error for user %s", user_id, exc_info=True)
        return None


async def _try_send_message(
    bot: Bot,
    user_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup,
    preview: LinkPreviewOptions,
) -> Message | None:
    try:
        return await bot.send_message(
            user_id,
            text,
            parse_mode="HTML",
            link_preview_options=preview,
            reply_markup=keyboard,
        )
    except TelegramBadRequest as exc:
        logger.warning("Message failed for user %s: %s", user_id, exc)
        return None
    except TelegramForbiddenError:
        raise
    except Exception:
        logger.exception("Message unexpected error for user %s", user_id)
        return None
