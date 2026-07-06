from __future__ import annotations

import logging
from collections import defaultdict

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

logger = logging.getLogger(__name__)

MAX_TRACKED = 50
_user_messages: dict[int, list[int]] = defaultdict(list)


async def try_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        logger.debug("Could not delete message %s in %s", message_id, chat_id)


async def track_message(user_id: int, message_id: int) -> None:
    ids = _user_messages[user_id]
    ids.append(message_id)
    if len(ids) > MAX_TRACKED:
        _user_messages[user_id] = ids[-MAX_TRACKED:]


async def clear_user_chat(bot: Bot, user_id: int, chat_id: int) -> int:
    deleted = 0
    for mid in list(_user_messages.get(user_id, [])):
        await try_delete(bot, chat_id, mid)
        deleted += 1
    _user_messages[user_id] = []
    return deleted


class WizardCleaner:
    """Tracks and removes wizard messages to keep chat tidy."""

    def __init__(self, state: FSMContext) -> None:
        self.state = state

    async def track(self, message_id: int, user_id: int) -> None:
        data = await self.state.get_data()
        ids: list[int] = data.get("wizard_ids", [])
        ids.append(message_id)
        await self.state.update_data(wizard_ids=ids)
        await track_message(user_id, message_id)

    async def delete_user(self, message: Message) -> None:
        await try_delete(message.bot, message.chat.id, message.message_id)

    async def cleanup_wizard(self, bot: Bot, chat_id: int) -> None:
        data = await self.state.get_data()
        for mid in data.get("wizard_ids", []):
            await try_delete(bot, chat_id, mid)
        await self.state.update_data(wizard_ids=[])

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
