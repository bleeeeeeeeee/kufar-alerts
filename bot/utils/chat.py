from __future__ import annotations

import logging
from collections import defaultdict

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.database import Database
from bot.error_handling import safe_edit_text
from bot.users import User


def sync_user_settings(user: User, updated: User) -> None:
    user.settings = updated.settings


def forget_tracked_messages(user_id: int) -> None:
    _user_messages.pop(user_id, None)
    _ui_message_ids.pop(user_id, None)

logger = logging.getLogger(__name__)

MAX_TRACKED = 80
_user_messages: dict[int, list[int]] = defaultdict(list)
_ui_message_ids: dict[int, int] = {}


async def send_to_main_chat(bot: Bot, user_id: int, text: str, **kwargs) -> Message:
    return await bot.send_message(user_id, text, **kwargs)


async def reply_user(message: Message, text: str, user: User | None = None, **kwargs) -> Message:
    return await message.answer(text, **kwargs)


def auto_clear_enabled(user: User | None) -> bool:
    if user is None:
        return False
    return user.settings.auto_clear_chat


def _panel_message_id(user_id: int, user: User | None) -> int | None:
    if user_id in _ui_message_ids:
        return _ui_message_ids[user_id]
    if user and user.settings.ui_message_id:
        _ui_message_ids[user_id] = user.settings.ui_message_id
        return user.settings.ui_message_id
    return None


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


async def save_panel(db: Database | None, user_id: int, message_id: int, user: User | None) -> None:
    _ui_message_ids[user_id] = message_id
    if user is not None:
        user.settings.ui_message_id = message_id
    if db is not None:
        await db.update_user_settings(user_id, {"ui_message_id": message_id})


async def clear_panel_cache(db: Database | None, user_id: int, user: User | None) -> None:
    _ui_message_ids.pop(user_id, None)
    if user is not None:
        user.settings.ui_message_id = None
    if db is not None:
        await db.update_user_settings(user_id, {"ui_message_id": None})


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


async def delete_panel_messages(
    bot: Bot,
    chat_id: int,
    user_id: int,
    user: User | None,
    db: Database | None,
    *,
    keep: int | None = None,
) -> None:
    panel_id = _panel_message_id(user_id, user)
    if panel_id is not None and panel_id != keep:
        await try_delete(bot, chat_id, panel_id)
        await untrack_message(user_id, panel_id)
        await clear_panel_cache(db, user_id, user)

    await clear_user_chat(bot, user_id, chat_id, keep=keep)


async def prepare_menu_message(
    message: Message,
    user: User | None,
    state: FSMContext | None,
    db: Database | None,
) -> None:
    """Clear old bot panels and the user's menu-button message."""
    if state is not None:
        await state.clear()
    if not auto_clear_enabled(user):
        return

    await delete_panel_messages(
        message.bot,
        message.chat.id,
        message.from_user.id,
        user,
        db,
    )
    await try_delete(message.bot, message.chat.id, message.message_id)


async def prepare_menu_callback(
    callback: CallbackQuery,
    user: User | None,
    state: FSMContext | None,
    db: Database | None,
) -> None:
    """Clear old bot messages but keep the current inline panel."""
    if state is not None:
        await state.clear()
    keep_id = callback.message.message_id
    if auto_clear_enabled(user):
        await delete_panel_messages(
            callback.message.bot,
            callback.message.chat.id,
            callback.from_user.id,
            user,
            db,
            keep=keep_id,
        )
    await track_message(callback.from_user.id, keep_id)
    if db is not None:
        await save_panel(db, callback.from_user.id, keep_id, user)


async def send_menu_message(
    message: Message,
    user: User | None,
    text: str,
    state: FSMContext | None,
    db: Database,
    **kwargs,
) -> Message:
    await prepare_menu_message(message, user, state, db)
    sent = await reply_user(message, text, user=user, **kwargs)
    await track_message(message.from_user.id, sent.message_id)
    await save_panel(db, message.from_user.id, sent.message_id, user)
    return sent


async def send_panel_message(
    bot: Bot,
    chat_id: int,
    user_id: int,
    user: User | None,
    db: Database,
    text: str,
    *,
    cleanup: bool = False,
    **kwargs,
) -> Message:
    if cleanup and auto_clear_enabled(user):
        await delete_panel_messages(bot, chat_id, user_id, user, db)
    sent = await bot.send_message(chat_id, text, **kwargs)
    await track_message(user_id, sent.message_id)
    await save_panel(db, user_id, sent.message_id, user)
    return sent


class WizardCleaner:
    """Tracks and removes wizard messages to keep chat tidy."""

    def __init__(
        self,
        state: FSMContext,
        user: User | None = None,
        db: Database | None = None,
    ) -> None:
        self.state = state
        self.user = user
        self.db = db

    async def track(self, message_id: int, user_id: int) -> None:
        data = await self.state.get_data()
        ids: list[int] = data.get("wizard_ids", [])
        ids.append(message_id)
        await self.state.update_data(wizard_ids=ids)
        await track_message(user_id, message_id)

    async def delete_user(self, message: Message) -> None:
        if not auto_clear_enabled(self.user):
            return
        await try_delete(message.bot, message.chat.id, message.message_id)

    async def cleanup_wizard(self, bot: Bot, chat_id: int, user_id: int) -> None:
        data = await self.state.get_data()
        wizard_ids = data.get("wizard_ids", [])
        if auto_clear_enabled(self.user):
            for mid in wizard_ids:
                await try_delete(bot, chat_id, mid)
                await untrack_message(user_id, mid)
        await self.state.update_data(wizard_ids=[])

    async def begin(self, message: Message, state: FSMContext | None = None) -> None:
        if state is not None:
            await state.clear()
        if auto_clear_enabled(self.user):
            await delete_panel_messages(
                message.bot,
                message.chat.id,
                message.from_user.id,
                self.user,
                self.db,
            )
            await try_delete(message.bot, message.chat.id, message.message_id)

    async def begin_callback(self, callback: CallbackQuery, state: FSMContext | None = None) -> None:
        await prepare_menu_callback(callback, self.user, state, self.db)
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
        sent = await reply_user(message, text, user=self.user, **kwargs)
        await self.track(sent.message_id, message.from_user.id)
        if self.db is not None:
            await save_panel(self.db, message.from_user.id, sent.message_id, self.user)
        return sent

    async def edit_or_send(self, callback: CallbackQuery, text: str, **kwargs) -> Message:
        edited = await safe_edit_text(callback.message, text, **kwargs)
        if edited:
            await self.track(callback.message.message_id, callback.from_user.id)
            if self.db is not None:
                await save_panel(self.db, callback.from_user.id, callback.message.message_id, self.user)
            return callback.message

        sent = await callback.message.answer(text, **kwargs)
        await self.track(sent.message_id, callback.from_user.id)
        if self.db is not None:
            await save_panel(self.db, callback.from_user.id, sent.message_id, self.user)
        return sent
