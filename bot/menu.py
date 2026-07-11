from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonCommands

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="new", description="Новая подписка"),
    BotCommand(command="list", description="Мои подписки"),
    BotCommand(command="settings", description="Настройки"),
    BotCommand(command="help", description="Инструкция"),
]


async def setup_bot_menu(bot: Bot) -> None:
    """Menu button left of the input field — always shows bot commands."""
    await bot.set_my_commands(BOT_COMMANDS)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Bot menu button and commands configured")
