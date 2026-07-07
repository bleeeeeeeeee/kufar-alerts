from __future__ import annotations

import logging
from collections import defaultdict

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.users import User

logger = logging.getLogger(__name__)

MAX_TRACKED = 80
_user_messages: dict[int, list[int]] = defaultdict(list)


def auto_clear_enabled(user: User | None) -> bool:
    if user is None:
        return False
    return user.settings.auto_clear_chat


async def try_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        logger.debug("Could not delete message %s in %s", message_id, chat_id)


async def track_message(user_id: int, message_id: int) -> None:
    ids = _user_messages[user_id]
    if message_id not in ids:
        ids.append(message_id)
    if len(ids) > MAX_TRACKED:
        _user_messages[user_id] = ids[-MAX_TRACKED:]


async def untrack_message(user_id: int, message_id: int) -> None:
    ids = _user_messages.get(user_id, [])
    if message_id in ids:
        ids.remove(message_id)


async def clear_user_chat(
    bot: Bot,
    user_id: int,
    chat_id: int,
    *,
    keep: int | None = None,
) -> int:
    deleted = 0
    remaining: list[int] = []
    for mid in list(_user_messages.get(user_id, [])):
        if keep is not None and mid == keep:
            remaining.append(mid)
            continue
        await try_delete(bot, chat_id, mid)
        deleted += 1
    _user_messages[user_id] = remaining
    return deleted


async def prepare_menu_message(message: Message, user: User | None, state: FSMContext | None = None) -> None:
    """Clear chat before a new menu screen (reply keyboard navigation)."""
    if state is not None:
        await state.clear()
    if auto_clear_enabled(user):
        await clear_user_chat(message.bot, message.from_user.id, message.chat.id)


async def prepare_menu_callback(callback: CallbackQuery, user: User | None, state: FSMContext | None = None) -> None:
    """Clear old messages but keep the current inline panel."""
    if state is not None:
        await state.clear()
    if auto_clear_enabled(user):
        await clear_user_chat(
            callback.message.bot,
            callback.from_user.id,
            callback.message.chat.id,
            keep=callback.message.message_id,
        )
    await track_message(callback.from_user.id, callback.message.message_id)


async def send_menu_message(
    message: Message,
    user: User | None,
    text: str,
    state: FSMContext | None = None,
    **kwargs,
) -> Message:
    await prepare_menu_message(message, user, state)
    sent = await message.answer(text, **kwargs)
    await track_message(message.from_user.id, sent.message_id)
    return sent


class WizardCleaner:
    """Tracks and removes wizard messages to keep chat tidy."""

    def __init__(self, state: FSMContext, user: User | None = None) -> None:
        self.state = state
        self.user = user

    async def track(self, message_id: int, user_id: int) -> None:
        data = await self.state.get_data()
        ids: list[int] = data.get("wizard_ids", [])
        ids.append(message_id)
        await self.state.update_data(wizard_ids=ids)
        await track_message(user_id, message_id)

    async def delete_user(self, message: Message) -> None:
        await try_delete(message.bot, message.chat.id, message.message_id)

    async def cleanup_wizard(self, bot: Bot, chat_id: int, user_id: int) -> None:
        data = await self.state.get_data()
        for mid in data.get("wizard_ids", []):
            await try_delete(bot, chat_id, mid)
            await untrack_message(user_id, mid)
        await self.state.update_data(wizard_ids=[])

    async def begin(self, message: Message, state: FSMContext | None = None) -> None:
        """Start wizard: optionally clear chat and reset wizard message list."""
        if state is not None:
            await state.clear()
        if auto_clear_enabled(self.user):
            await clear_user_chat(message.bot, message.from_user.id, message.chat.id)

    async def begin_callback(self, callback: CallbackQuery, state: FSMContext | None = None) -> None:
        if state is not None:
            await state.clear()
        if auto_clear_enabled(self.user):
            await clear_user_chat(
                callback.message.bot,
                callback.from_user.id,
                callback.message.chat.id,
                keep=callback.message.message_id,
            )
        await self.state.update_data(wizard_ids=[callback.message.message_id])

    async def send(
        self,
        message: Message,
        text: str,
        *,
        delete_user: bool = False,
        **kwargs,
    ) -> Message:
        if delete_user:
            await self.delete_user(message)
        sent = await message.answer(text, **kwargs)
        await self.track(sent.message_id, message.from_user.id)
        return sent

    async def edit_or_send(self, callback: CallbackQuery, text: str, **kwargs) -> Message:
        try:
            await callback.message.edit_text(text, **kwargs)
            await self.track(callback.message.message_id, callback.from_user.id)
            return callback.message
        except Exception:
            sent = await callback.message.answer(text, **kwargs)
            await self.track(sent.message_id, callback.from_user.id)
            return sent
