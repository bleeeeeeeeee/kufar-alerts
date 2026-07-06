from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router()

HELP_TEXT = """
<b>Kufar Alerts</b> — оповещения о новых объявлениях на kufar.by

<b>Команды:</b>
/new — создать подписку на поиск
/list — мои подписки
/pause ID — поставить на паузу
/resume ID — возобновить
/delete ID — удалить подписку
/help — справка

<b>Как создать подписку:</b>
1. Настройте поиск на <a href="https://www.kufar.by">kufar.by</a>
2. Скопируйте URL из адресной строки
3. Отправьте /new и вставьте ссылку

Или создайте подписку вручную — бот спросит запрос, категорию, регион и цену.

Бот проверяет новые объявления каждые ~45 секунд и присылает уведомление с фото и ссылкой.
"""


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Привет! Я слежу за новыми объявлениями на Kufar.\n\n"
        "Создай подписку командой /new или посмотри справку /help",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="HTML", disable_web_page_preview=True)
