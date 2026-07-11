from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.access import format_invite_no_access_text, is_start_command
from bot.config import Settings
from bot.database import Database
from bot.error_handling import safe_answer
from bot.keyboards import MAIN_MENU, MAIN_MENU_BUTTONS
from bot.navigation import format_home_text, home_row
from bot.users import User
from bot.utils.chat import (
    WizardCleaner,
    auto_clear_enabled,
    send_menu_message,
    send_panel_message,
    track_message,
)

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

<b>☰ Меню</b> — кнопка слева от поля ввода.

Уведомления приходят сюда — под каждым есть кнопка <b>🗑 Удалить</b>.

Проверка — каждые ~15 сек (интервал подписки настраивается в ⚙️).
"""


@router.message(CommandStart())
@router.message(F.text.func(is_start_command))
async def cmd_start(
    message: Message,
    state: FSMContext,
    db: Database,
    user: User | None,
    app_settings: Settings,
) -> None:
    await state.clear()

    if user is None:
        stored = await db.get_user(message.from_user.id)
        if stored and not stored.active:
            sent = await message.answer(
                format_invite_no_access_text(message.from_user, blocked=True),
                parse_mode="HTML",
            )
            await track_message(message.from_user.id, sent.message_id)
            return

        access_mode = await db.get_access_mode(app_settings.access_mode)
        if access_mode == "open":
            sent = await message.answer(
                "👋 <b>Kufar Alerts</b>\n\n"
                "Не удалось открыть доступ. Попробуйте отправить /start ещё раз.",
                parse_mode="HTML",
            )
            await track_message(message.from_user.id, sent.message_id)
            return

        sent = await message.answer(
            format_invite_no_access_text(message.from_user),
            parse_mode="HTML",
        )
        await track_message(message.from_user.id, sent.message_id)
        return

    alerts = await db.get_user_alerts(message.from_user.id)
    active = sum(1 for a in alerts if a.active)

    home_text = format_home_text(user.display_name, len(alerts), active)
    home_text += "\n\n🔔 Уведомления приходят сюда — под каждым есть кнопка <b>🗑 Удалить</b>."

    await send_menu_message(
        message,
        user,
        home_text,
        state,
        db,
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
    )


@router.callback_query(F.data == "nav:home")
async def nav_home(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    user: User | None,
) -> None:
    if not user:
        await safe_answer(callback, "Нет доступа", show_alert=True)
        return

    cleaner = WizardCleaner(state, user, db)
    await cleaner.cleanup_wizard(callback.message.bot, callback.message.chat.id, callback.from_user.id)
    await state.clear()

    alerts = await db.get_user_alerts(callback.from_user.id)
    active = sum(1 for a in alerts if a.active)
    text = format_home_text(user.display_name, len(alerts), active)

    if auto_clear_enabled(user):
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

    await send_panel_message(
        callback.message.bot,
        callback.from_user.id,
        callback.from_user.id,
        user,
        db,
        text,
        cleanup=True,
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
    )
    await safe_answer(callback)


@router.message(Command("help"))
@router.message(F.text == MAIN_MENU_BUTTONS["help"])
async def cmd_help(message: Message, user: User | None, state: FSMContext, db: Database) -> None:
    if user is None:
        sent = await message.answer(
            format_invite_no_access_text(message.from_user),
            parse_mode="HTML",
        )
        await track_message(message.from_user.id, sent.message_id)
        return
    await send_menu_message(
        message,
        user,
        HELP_TEXT,
        state,
        db,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[home_row()]),
    )


@router.message(Command("status"))
async def cmd_status(
    message: Message,
    db: Database,
    user: User | None,
    app_settings: Settings,
    state: FSMContext,
) -> None:
    if user is None:
        sent = await message.answer("Нет доступа. /start — ваш ID для администратора.")
        await track_message(message.from_user.id, sent.message_id)
        return
    alerts = await db.get_user_alerts(message.from_user.id)
    active = sum(1 for a in alerts if a.active)
    poll = user.settings.poll_interval or app_settings.poll_interval
    if not alerts:
        text = (
            f"📊 Подписок нет. Бот готов к работе.\n"
            f"Проверка: каждые ~{poll} сек, "
            f"последние {app_settings.search_size} объявлений по каждой подписке."
        )
    else:
        text = (
            f"📊 <b>Статус</b>\n\n"
            f"Подписок: {len(alerts)}\n"
            f"Активных: {active}\n"
            f"На паузе: {len(alerts) - active}\n\n"
            f"⏱ Интервал: ~{poll} сек\n"
            f"📥 Глубина поиска: {app_settings.search_size} объявлений"
        )
    await send_menu_message(message, user, text, state, db, parse_mode="HTML")
