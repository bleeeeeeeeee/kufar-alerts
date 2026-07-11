from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.access_config import ACCESS_MODE_INVITE, ACCESS_MODE_OPEN, access_mode_description, access_mode_label
from bot.config import Settings
from bot.database import Database
from bot.keyboards import MAIN_MENU, MAIN_MENU_BUTTONS
from bot.navigation import home_row
from bot.notifier import NOTIFY_CLEAR_MENU
from bot.notification_styles import NOTIFICATION_LAYOUTS, NOTIFICATION_STYLES, notification_layout_label, notification_style_label
from bot.timing import (
    NOTIFY_COOLDOWN_OPTIONS,
    POLL_INTERVAL_OPTIONS,
    format_notify_cooldown,
    format_poll_interval,
    notify_cooldown_label,
    poll_interval_label,
)
from bot.users import DISPLAY_FIELD_ICONS, DISPLAY_FIELD_LABELS, User
from bot.utils.chat import send_menu_message, sync_user_settings, forget_tracked_messages, track_message

logger = logging.getLogger(__name__)

router = Router()


def settings_keyboard(user: User, *, access_mode: str = "invite") -> InlineKeyboardMarkup:
    photos_label = "🖼 Фото: вкл" if user.settings.photos_enabled else "🖼 Фото: выкл"
    clear_label = "♻️ Автоочистка: вкл" if user.settings.auto_clear_chat else "♻️ Автоочистка: выкл"
    rows = [
        [InlineKeyboardButton(text=photos_label, callback_data="settings:toggle_photos")],
        [InlineKeyboardButton(text=clear_label, callback_data="settings:toggle_clear")],
        [InlineKeyboardButton(text="🧾 Поля уведомления", callback_data="settings:display_menu")],
        [InlineKeyboardButton(text="🎨 Стиль уведомлений", callback_data="settings:style_menu")],
        [InlineKeyboardButton(text="🧹 Очистить уведомления", callback_data=NOTIFY_CLEAR_MENU)],
        [InlineKeyboardButton(text="⏱ Задержки", callback_data="settings:timing_menu")],
    ]
    if user.is_admin:
        rows.append([InlineKeyboardButton(text="🔒 Доступ к боту", callback_data="settings:access_menu")])
        rows.append([InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def settings_screen(
    db: Database,
    user: User,
    app_settings: Settings,
) -> tuple[str, InlineKeyboardMarkup]:
    access_mode = await db.get_access_mode(app_settings.access_mode)
    return (
        format_settings_text(user, app_settings, access_mode=access_mode),
        settings_keyboard(user, access_mode=access_mode),
    )


def display_menu_keyboard(user: User) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    display = user.settings.notification_display
    for key in DISPLAY_FIELD_LABELS:
        enabled = getattr(display, key)
        mark = "✅" if enabled else "⬜️"
        icon = DISPLAY_FIELD_ICONS.get(key, "•")
        label = DISPLAY_FIELD_LABELS[key]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {icon} {label}",
                    callback_data=f"settings:display_toggle:{key}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_display_menu_text() -> str:
    return (
        "<b>🧾 Поля в уведомлениях</b>\n\n"
        "Выберите, что показывать в сообщениях о новых объявлениях.\n"
        "Название и ссылка отображаются всегда."
    )


def style_menu_keyboard(user: User) -> InlineKeyboardMarkup:
    current = user.settings.notification_style
    layout = user.settings.notification_layout
    rows: list[list[InlineKeyboardButton]] = []
    for key, meta in NOTIFICATION_STYLES.items():
        mark = "✓ " if current == key else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{meta['label']}",
                    callback_data=f"settings:set_style:{key}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=f"{'✓ ' if layout == 'row' else ''}{NOTIFICATION_LAYOUTS['row']['label']}",
                callback_data="settings:set_layout:row",
            ),
            InlineKeyboardButton(
                text=f"{'✓ ' if layout == 'column' else ''}{NOTIFICATION_LAYOUTS['column']['label']}",
                callback_data="settings:set_layout:column",
            ),
        ]
    )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_style_menu_text(user: User) -> str:
    current = notification_style_label(user.settings.notification_style)
    layout = notification_layout_label(user.settings.notification_layout)
    hint = NOTIFICATION_STYLES.get(user.settings.notification_style, {}).get("hint", "")
    layout_hint = NOTIFICATION_LAYOUTS.get(user.settings.notification_layout, {}).get("hint", "")
    return (
        "<b>🎨 Стиль уведомлений</b>\n\n"
        f"Тема: <b>{html.escape(current)}</b>\n"
        f"{html.escape(hint)}\n\n"
        f"Раскладка: <b>{html.escape(layout)}</b>\n"
        f"{html.escape(layout_hint)}\n\n"
        "Поля настраиваются отдельно в 🧾 Поля уведомления."
    )


def timing_menu_keyboard(user: User, app_settings: Settings) -> InlineKeyboardMarkup:
    poll = format_poll_interval(user.settings.poll_interval, default=app_settings.poll_interval)
    cooldown = format_notify_cooldown(user.settings.notify_cooldown)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔍 Проверка Kufar: {poll}", callback_data="settings:poll_menu")],
            [InlineKeyboardButton(text=f"⏳ Пауза между уведомлениями: {cooldown}", callback_data="settings:cooldown_menu")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:back")],
        ]
    )


def format_timing_menu_text(user: User, app_settings: Settings) -> str:
    poll = format_poll_interval(user.settings.poll_interval, default=app_settings.poll_interval)
    cooldown = format_notify_cooldown(user.settings.notify_cooldown)
    return (
        "<b>⏱ Задержки</b>\n\n"
        f"🔍 <b>Проверка Kufar:</b> {poll}\n"
        "Как часто бот ищет новые объявления по вашим подпискам.\n\n"
        f"⏳ <b>Пауза между уведомлениями:</b> {cooldown}\n"
        "Минимальный интервал между сообщениями, если за раз нашлось несколько объявлений."
    )


def poll_interval_keyboard(user: User, app_settings: Settings) -> InlineKeyboardMarkup:
    current = user.settings.poll_interval
    rows: list[list[InlineKeyboardButton]] = []
    default_mark = "✓ " if current is None else ""
    rows.append(
        [
            InlineKeyboardButton(
                text=f"{default_mark}По умолчанию (~{app_settings.poll_interval} сек)",
                callback_data="settings:set_poll:default",
            )
        ]
    )
    for value in POLL_INTERVAL_OPTIONS:
        mark = "✓ " if current == value else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{poll_interval_label(value, default=app_settings.poll_interval)}",
                    callback_data=f"settings:set_poll:{value}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="settings:timing_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def notify_cooldown_keyboard(user: User) -> InlineKeyboardMarkup:
    current = user.settings.notify_cooldown
    rows: list[list[InlineKeyboardButton]] = []
    for value in NOTIFY_COOLDOWN_OPTIONS:
        mark = "✓ " if current == value else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{notify_cooldown_label(value)}",
                    callback_data=f"settings:set_cooldown:{value}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="settings:timing_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_settings_text(user: User, app_settings: Settings, *, access_mode: str) -> str:
    access_label = access_mode_label(access_mode)
    photos = "включены" if user.settings.photos_enabled else "выключены"
    auto_clear = "включена" if user.settings.auto_clear_chat else "выключена"
    role = "администратор" if user.is_admin else "пользователь"

    lines = [
        "<b>⚙️ Настройки</b>",
        "",
        f"👤 {user.display_name}",
        f"🆔 <code>{user.user_id}</code>",
        f"🔑 Роль: {role}",
        "",
        f"🖼 Фото в уведомлениях: {photos} — крупное превью ссылки Kufar",
        f"♻️ Автоочистка чата: {auto_clear}",
        f"🎨 Стиль: {notification_style_label(user.settings.notification_style)}, "
        f"{notification_layout_label(user.settings.notification_layout).lower()}",
        f"🔍 Проверка Kufar: {format_poll_interval(user.settings.poll_interval, default=app_settings.poll_interval)}",
        f"⏳ Пауза между уведомлениями: {format_notify_cooldown(user.settings.notify_cooldown)}",
    ]
    if user.is_admin:
        lines.append(f"🔒 Режим доступа: {access_label}")
    return "\n".join(lines)


def format_access_menu_text(access_mode: str) -> str:
    return (
        "<b>🔒 Доступ к боту</b>\n\n"
        f"Сейчас: <b>{access_mode_label(access_mode)}</b> — "
        f"{access_mode_description(access_mode)}.\n\n"
        "Уже добавленные пользователи сохраняют доступ в любом режиме.\n"
        "Новые пользователи — по правилам выбранного режима."
    )


def access_menu_keyboard(access_mode: str) -> InlineKeyboardMarkup:
    modes = (
        (ACCESS_MODE_INVITE, "По приглашению"),
        (ACCESS_MODE_OPEN, "Открытый"),
    )
    rows: list[list[InlineKeyboardButton]] = []
    for mode, title in modes:
        mark = "✅ " if mode == access_mode else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{title}",
                    callback_data=f"settings:set_access:{mode}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("settings"))
@router.message(F.text == MAIN_MENU_BUTTONS["settings"])
async def cmd_settings(
    message: Message,
    user: User | None,
    db: Database,
    app_settings: Settings,
    state: FSMContext,
) -> None:
    if not user:
        sent = await message.answer(
            "🔒 Нет доступа. Отправьте /start — там будет ваш ID для администратора.",
            parse_mode="HTML",
        )
        await track_message(message.from_user.id, sent.message_id)
        return

    await state.clear()
    text, keyboard = await settings_screen(db, user, app_settings)
    await send_menu_message(
        message,
        user,
        text,
        state,
        db,
        parse_mode="HTML",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "settings:back")
async def settings_back(callback: CallbackQuery, user: User | None, db: Database, app_settings: Settings, state: FSMContext) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    text, keyboard = await settings_screen(db, user, app_settings)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data == "settings:display_menu")
async def display_menu(callback: CallbackQuery, user: User | None) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        format_display_menu_text(),
        parse_mode="HTML",
        reply_markup=display_menu_keyboard(user),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:display_toggle:"))
async def display_toggle(
    callback: CallbackQuery,
    user: User | None,
    db: Database,
) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return

    field = callback.data.split(":")[-1]
    if field not in DISPLAY_FIELD_LABELS:
        await callback.answer("Неизвестное поле", show_alert=True)
        return

    current = user.settings.notification_display.to_dict()
    current[field] = not current[field]
    updated = await db.update_user_settings(user.user_id, {"notification_display": current})
    if not updated:
        await callback.answer("Ошибка", show_alert=True)
        return

    await callback.message.edit_text(
        format_display_menu_text(),
        parse_mode="HTML",
        reply_markup=display_menu_keyboard(updated),
    )
    state_label = "включено" if current[field] else "выключено"
    await callback.answer(f"{DISPLAY_FIELD_LABELS[field]}: {state_label}")


@router.callback_query(F.data == "settings:style_menu")
async def style_menu(callback: CallbackQuery, user: User | None) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        format_style_menu_text(user),
        parse_mode="HTML",
        reply_markup=style_menu_keyboard(user),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:set_style:"))
async def set_notification_style(
    callback: CallbackQuery,
    user: User | None,
    db: Database,
    app_settings: Settings,
) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return

    style = callback.data.split(":")[-1]
    if style not in NOTIFICATION_STYLES:
        await callback.answer("Неизвестный стиль", show_alert=True)
        return

    updated = await db.update_user_settings(user.user_id, {"notification_style": style})
    if not updated:
        await callback.answer("Ошибка", show_alert=True)
        return

    sync_user_settings(user, updated)
    await callback.message.edit_text(
        format_style_menu_text(updated),
        parse_mode="HTML",
        reply_markup=style_menu_keyboard(updated),
    )
    await callback.answer(f"Стиль: {notification_style_label(style)}")


@router.callback_query(F.data.startswith("settings:set_layout:"))
async def set_notification_layout(
    callback: CallbackQuery,
    user: User | None,
    db: Database,
) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return

    layout = callback.data.split(":")[-1]
    if layout not in NOTIFICATION_LAYOUTS:
        await callback.answer("Неизвестная раскладка", show_alert=True)
        return

    updated = await db.update_user_settings(user.user_id, {"notification_layout": layout})
    if not updated:
        await callback.answer("Ошибка", show_alert=True)
        return

    sync_user_settings(user, updated)
    await callback.message.edit_text(
        format_style_menu_text(updated),
        parse_mode="HTML",
        reply_markup=style_menu_keyboard(updated),
    )
    await callback.answer(f"Раскладка: {notification_layout_label(layout)}")


@router.callback_query(F.data == "settings:timing_menu")
async def timing_menu(callback: CallbackQuery, user: User | None, app_settings: Settings) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        format_timing_menu_text(user, app_settings),
        parse_mode="HTML",
        reply_markup=timing_menu_keyboard(user, app_settings),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:poll_menu")
async def poll_menu(callback: CallbackQuery, user: User | None, app_settings: Settings) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "<b>🔍 Как часто проверять Kufar</b>\n\nВыберите интервал для ваших подписок:",
        parse_mode="HTML",
        reply_markup=poll_interval_keyboard(user, app_settings),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:cooldown_menu")
async def cooldown_menu(callback: CallbackQuery, user: User | None) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "<b>⏳ Пауза между уведомлениями</b>\n\n"
        "Если за один проход нашлось несколько объявлений, бот будет ждать перед следующим:",
        parse_mode="HTML",
        reply_markup=notify_cooldown_keyboard(user),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:set_poll:"))
async def set_poll_interval(
    callback: CallbackQuery,
    user: User | None,
    db: Database,
    app_settings: Settings,
) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return

    raw = callback.data.split(":")[-1]
    poll_value = None if raw == "default" else int(raw)
    updated = await db.update_user_settings(user.user_id, {"poll_interval": poll_value})
    if not updated:
        await callback.answer("Ошибка", show_alert=True)
        return

    await callback.message.edit_text(
        format_timing_menu_text(updated, app_settings),
        parse_mode="HTML",
        reply_markup=timing_menu_keyboard(updated, app_settings),
    )
    label = format_poll_interval(updated.settings.poll_interval, default=app_settings.poll_interval)
    await callback.answer(f"Проверка: {label}")


@router.callback_query(F.data.startswith("settings:set_cooldown:"))
async def set_notify_cooldown(
    callback: CallbackQuery,
    user: User | None,
    db: Database,
    app_settings: Settings,
) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return

    value = int(callback.data.split(":")[-1])
    updated = await db.update_user_settings(user.user_id, {"notify_cooldown": value})
    if not updated:
        await callback.answer("Ошибка", show_alert=True)
        return

    await callback.message.edit_text(
        format_timing_menu_text(updated, app_settings),
        parse_mode="HTML",
        reply_markup=timing_menu_keyboard(updated, app_settings),
    )
    await callback.answer(f"Пауза: {format_notify_cooldown(value)}")


@router.callback_query(F.data == "settings:toggle_photos")
async def toggle_photos(callback: CallbackQuery, user: User | None, db: Database, app_settings: Settings) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return

    new_value = not user.settings.photos_enabled
    updated = await db.update_user_settings(user.user_id, {"photos_enabled": new_value})
    if not updated:
        await callback.answer("Ошибка", show_alert=True)
        return

    sync_user_settings(user, updated)

    text, keyboard = await settings_screen(db, updated, app_settings)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer("Фото " + ("включены" if new_value else "выключены"))


@router.callback_query(F.data == "settings:toggle_clear")
async def toggle_clear(callback: CallbackQuery, user: User | None, db: Database, app_settings: Settings) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return

    new_value = not user.settings.auto_clear_chat
    updated = await db.update_user_settings(user.user_id, {"auto_clear_chat": new_value})
    if not updated:
        await callback.answer("Ошибка", show_alert=True)
        return

    sync_user_settings(user, updated)
    if not new_value:
        forget_tracked_messages(user.user_id)

    text, keyboard = await settings_screen(db, updated, app_settings)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer("Автоочистка " + ("включена" if new_value else "выключена"))


@router.callback_query(F.data == "settings:access_menu")
async def access_menu(callback: CallbackQuery, user: User | None, db: Database, app_settings: Settings) -> None:
    if not user or not user.is_admin:
        await callback.answer("Только для администраторов", show_alert=True)
        return

    access_mode = await db.get_access_mode(app_settings.access_mode)
    await callback.message.edit_text(
        format_access_menu_text(access_mode),
        parse_mode="HTML",
        reply_markup=access_menu_keyboard(access_mode),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:set_access:"))
async def set_access_mode(callback: CallbackQuery, user: User | None, db: Database, app_settings: Settings) -> None:
    if not user or not user.is_admin:
        await callback.answer("Только для администраторов", show_alert=True)
        return

    mode = callback.data.split(":")[-1]
    if mode not in (ACCESS_MODE_OPEN, ACCESS_MODE_INVITE):
        await callback.answer("Неизвестный режим", show_alert=True)
        return

    await db.set_access_mode(mode, default=app_settings.access_mode)
    await callback.message.edit_text(
        format_access_menu_text(mode),
        parse_mode="HTML",
        reply_markup=access_menu_keyboard(mode),
    )
    await callback.answer(f"Режим: {access_mode_label(mode)}")
