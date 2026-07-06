from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import MAIN_MENU, MAIN_MENU_BUTTONS
from bot.utils.chat import clear_user_chat, track_message

router = Router()

HELP_TEXT = """
<b>📖 Инструкция — Kufar Alerts</b>

Бот присылает уведомления о <b>новых</b> объявлениях на kufar.by по вашим фильтрам.

<b>➕ Создать подписку</b>
1. Настройте поиск на <a href="https://www.kufar.by">kufar.by</a>
2. Скопируйте ссылку из адресной строки
3. Нажмите «Новая подписка» и вставьте ссылку

Или настройте вручную — бот спросит запрос, категорию, регион и цену.

<b>📍 Место</b>
Выберите регион → город или район кнопками.
Можно выбрать «Вся область» или пропустить.

<b>📂 Категория</b>
Выбирается из списка — можно зайти в подкатегории.

<b>💰 Как вводить цену</b>
• <code>1500</code> — до 1500 BYN
• <code>500-1500</code> — от 500 до 1500 BYN
• <code>500+</code> — от 500 BYN и выше
• <code>-</code> — без фильтра по цене

<b>📍 Регионы</b> (выбираются кнопками)
Минск, Минская обл., Брестская, Гомельская и др.

<b>📋 Управление</b>
• Подписки — список всех подписок
• Редактировать — изменить фильтры
• Очистить чат — удалить сообщения бота

Проверка новых объявлений — каждые ~45 секунд.
"""


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    sent = await message.answer(
        "👋 <b>Kufar Alerts</b>\n\n"
        "Слежу за новыми объявлениями на Kufar и присылаю уведомления.\n\n"
        "Нажмите <b>➕ Новая подписка</b> или откройте <b>📖 Инструкцию</b>.",
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
    )
    await track_message(message.from_user.id, sent.message_id)


@router.message(Command("help"))
@router.message(F.text == MAIN_MENU_BUTTONS["help"])
async def cmd_help(message: Message) -> None:
    sent = await message.answer(HELP_TEXT, parse_mode="HTML", disable_web_page_preview=True)
    await track_message(message.from_user.id, sent.message_id)


@router.message(Command("clear"))
@router.message(F.text == MAIN_MENU_BUTTONS["clear"])
async def cmd_clear(message: Message, state: FSMContext) -> None:
    await state.clear()
    deleted = await clear_user_chat(message.bot, message.from_user.id, message.chat.id)
    try:
        await message.delete()
    except Exception:
        pass
    sent = await message.answer(
        f"🧹 Удалено сообщений: {deleted}",
        reply_markup=MAIN_MENU,
    )
    await track_message(message.from_user.id, sent.message_id)
