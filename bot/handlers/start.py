from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import Settings
from bot.database import Database
from bot.keyboards import MAIN_MENU, MAIN_MENU_BUTTONS
from bot.users import User
from bot.utils.chat import send_menu_message, track_message

router = Router()

HELP_TEXT = """
<b>📖 Kufar Alerts — инструкция</b>

Бот следит за новыми объявлениями на <a href="https://www.kufar.by">kufar.by</a> и присылает уведомления в Telegram.

<b>➕ Создать подписку</b>
• <b>Ссылка</b> — скопируйте URL поиска с Kufar и вставьте в бота
• <b>Вручную</b> — запрос, категория, регион, цена

<b>💰 Цена</b>
• <code>1500</code> — до 1500 BYN
• <code>500-1500</code> — диапазон
• <code>500+</code> — от 500 BYN
• <code>-</code> — без фильтра

<b>📋 Подписки</b> — список → выберите подписку → ✏️ Изменить

<b>⚙️ Настройки</b> — профиль, фото в уведомлениях, автоочистка чата

Проверка — каждые ~45 секунд. У каждого пользователя <b>свои</b> подписки и настройки.
"""


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    db: Database,
    user: User | None,
    app_settings: Settings,
) -> None:
    await state.clear()

    if user is None:
        access_hint = (
            "открытый — любой может пользоваться"
            if app_settings.access_mode == "open"
            else "по приглашению — нужен доступ от администратора"
        )
        sent = await message.answer(
            "👋 <b>Kufar Alerts</b>\n\n"
            f"🔒 Режим: {access_hint}.\n\n"
            "У вас пока нет доступа. Передайте администратору ваш Telegram ID:\n"
            f"<code>{message.from_user.id}</code>"
            + (f"\n📎 @{message.from_user.username}" if message.from_user.username else ""),
            parse_mode="HTML",
        )
        await track_message(message.from_user.id, sent.message_id)
        return

    alerts = await db.get_user_alerts(message.from_user.id)
    active = sum(1 for a in alerts if a.active)

    if alerts:
        status = f"\n\n📋 У вас <b>{len(alerts)}</b> подписок ({active} активных)."
        hint = "Откройте <b>📋 Мои подписки</b> для управления."
    else:
        status = ""
        hint = "Нажмите <b>➕ Новая подписка</b>, чтобы начать."

    sent = await send_menu_message(
        message,
        user,
        "👋 <b>Kufar Alerts</b>\n\n"
        f"Привет, <b>{user.display_name}</b>!\n"
        "Присылаю уведомления о новых объявлениях на Kufar."
        f"{status}\n\n{hint}",
        state,
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
    )


@router.message(Command("help"))
@router.message(F.text == MAIN_MENU_BUTTONS["help"])
async def cmd_help(message: Message, user: User | None, state) -> None:
    if user is None:
        sent = await message.answer("Сначала получите доступ — отправьте /start.")
        await track_message(message.from_user.id, sent.message_id)
        return
    await send_menu_message(
        message,
        user,
        HELP_TEXT,
        state,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("status"))
async def cmd_status(message: Message, db: Database, user: User | None, app_settings: Settings) -> None:
    if user is None:
        sent = await message.answer("Нет доступа. /start — ваш ID для администратора.")
        await track_message(message.from_user.id, sent.message_id)
        return
    alerts = await db.get_user_alerts(message.from_user.id)
    active = sum(1 for a in alerts if a.active)
    if not alerts:
        text = (
            f"📊 Подписок нет. Бот готов к работе.\n"
            f"Проверка: каждые ~{app_settings.poll_interval} сек, "
            f"последние {app_settings.search_size} объявлений по каждой подписке."
        )
    else:
        text = (
            f"📊 <b>Статус</b>\n\n"
            f"Подписок: {len(alerts)}\n"
            f"Активных: {active}\n"
            f"На паузе: {len(alerts) - active}\n\n"
            f"⏱ Интервал: ~{app_settings.poll_interval} сек\n"
            f"📥 Глубина поиска: {app_settings.search_size} последних объявлений"
        )
    sent = await message.answer(text, parse_mode="HTML")
    await track_message(message.from_user.id, sent.message_id)
