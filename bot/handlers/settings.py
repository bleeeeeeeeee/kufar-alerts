from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.database import Database
from bot.keyboards import MAIN_MENU, MAIN_MENU_BUTTONS
from bot.navigation import home_row
from bot.topics import (
    NOTIFICATION_TOPIC_NAME,
    TOPIC_WELCOME_TEXT,
    TopicSetupError,
    create_notification_topic,
    send_text_to_topic,
)
from bot.timing import (
    NOTIFY_COOLDOWN_OPTIONS,
    POLL_INTERVAL_OPTIONS,
    format_notify_cooldown,
    format_poll_interval,
    notify_cooldown_label,
    poll_interval_label,
)
from bot.users import DISPLAY_FIELD_ICONS, DISPLAY_FIELD_LABELS, User
from bot.utils.chat import send_menu_message, track_message

logger = logging.getLogger(__name__)

router = Router()


def settings_keyboard(user: User) -> InlineKeyboardMarkup:
    photos_label = "🖼 Фото: вкл" if user.settings.photos_enabled else "🖼 Фото: выкл"
    clear_label = "🧹 Автоочистка: вкл" if user.settings.auto_clear_chat else "🧹 Автоочистка: выкл"
    topic_label = (
        "📬 Топик уведомлений: вкл"
        if user.settings.notification_topic_id
        else "📬 Топик уведомлений: выкл"
    )
    rows = [
        [InlineKeyboardButton(text=photos_label, callback_data="settings:toggle_photos")],
        [InlineKeyboardButton(text=clear_label, callback_data="settings:toggle_clear")],
        [InlineKeyboardButton(text="🧾 Поля уведомления", callback_data="settings:display_menu")],
        [InlineKeyboardButton(text="⏱ Задержки", callback_data="settings:timing_menu")],
        [InlineKeyboardButton(text=topic_label, callback_data="settings:topic_menu")],
    ]
    if user.is_admin:
        rows.append([InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users")])
    rows.append(home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def topic_menu_keyboard(user: User) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if user.settings.notification_topic_id:
        rows.append(
            [InlineKeyboardButton(text="🔄 Пересоздать топик", callback_data="settings:topic_create")]
        )
        rows.append(
            [InlineKeyboardButton(text="❌ Отключить топик", callback_data="settings:topic_clear")]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="📬 Создать топик уведомлений", callback_data="settings:topic_create")]
        )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_settings_text(user: User, app_settings: Settings) -> str:
    access_label = "открытый" if app_settings.access_mode == "open" else "по приглашению"
    photos = "включены" if user.settings.photos_enabled else "выключены"
    auto_clear = "включена" if user.settings.auto_clear_chat else "выключена"
    topic = (
        f"включён — тема «{NOTIFICATION_TOPIC_NAME}»"
        if user.settings.notification_topic_id
        else "выключен — уведомления в общем чате"
    )
    role = "администратор" if user.is_admin else "пользователь"

    lines = [
        "<b>⚙️ Настройки</b>",
        "",
        f"👤 {user.display_name}",
        f"🆔 <code>{user.user_id}</code>",
        f"🔑 Роль: {role}",
        "",
        f"🖼 Фото в уведомлениях: {photos}",
        f"🧹 Автоочистка чата: {auto_clear}",
        f"🔍 Проверка Kufar: {format_poll_interval(user.settings.poll_interval, default=app_settings.poll_interval)}",
        f"⏳ Пауза между уведомлениями: {format_notify_cooldown(user.settings.notify_cooldown)}",
        f"📬 Топик уведомлений: {topic}",
        f"🔒 Режим доступа: {access_label}",
    ]
    if app_settings.access_mode == "invite" and not user.is_admin:
        lines.append("\n<i>Чтобы пригласить кого-то — передайте админу свой ID выше.</i>")
    return "\n".join(lines)


def format_topic_help_text(user: User | None = None) -> str:
    if user and user.settings.notification_topic_id:
        return (
            "<b>📬 Топик для уведомлений</b>\n\n"
            f"Топик <b>«{NOTIFICATION_TOPIC_NAME}»</b> уже создан — "
            "новые объявления приходят туда.\n\n"
            "Меню бота остаётся в общем чате."
        )
    return (
        "<b>📬 Топик для уведомлений</b>\n\n"
        "Бот сам создаст тему «Уведомления» в вашем чате.\n"
        "Туда будут приходить только новые объявления, "
        "а команды и меню останутся в общем чате.\n\n"
        "Нажмите кнопку ниже — больше ничего настраивать не нужно."
    )


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
    await send_menu_message(
        message,
        user,
        format_settings_text(user, app_settings),
        state,
        parse_mode="HTML",
        reply_markup=settings_keyboard(user),
    )


@router.callback_query(F.data == "settings:back")
async def settings_back(callback: CallbackQuery, user: User | None, db: Database, app_settings: Settings, state: FSMContext) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        format_settings_text(user, app_settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(user),
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


@router.callback_query(F.data == "settings:topic_menu")
async def topic_menu(callback: CallbackQuery, user: User | None, app_settings: Settings) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        format_topic_help_text(user),
        parse_mode="HTML",
        reply_markup=topic_menu_keyboard(user),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:topic_create")
async def topic_create(
    callback: CallbackQuery,
    user: User | None,
    db: Database,
    app_settings: Settings,
    state: FSMContext,
    bot: Bot,
) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await callback.answer("Создаю топик…")

    try:
        topic_id = await create_notification_topic(bot, user.user_id)
        updated = await db.update_user_settings(
            user.user_id,
            {"notification_topic_id": topic_id},
        )
        if not updated:
            await callback.message.edit_text("Не удалось сохранить топик.")
            return

        try:
            await send_text_to_topic(
                bot,
                user.user_id,
                TOPIC_WELCOME_TEXT,
                topic_id,
            )
        except Exception:
            logger.exception("Failed to send welcome message to topic %s", topic_id)

        await callback.message.edit_text(
            f"✅ Топик <b>«{NOTIFICATION_TOPIC_NAME}»</b> создан.\n\n"
            "Новые объявления будут приходить туда.\n\n"
            + format_settings_text(updated, app_settings),
            parse_mode="HTML",
            reply_markup=settings_keyboard(updated),
        )
    except TopicSetupError as exc:
        await callback.message.edit_text(
            f"⚠️ Не удалось создать топик.\n\n{exc.user_hint}",
            parse_mode="HTML",
            reply_markup=topic_menu_keyboard(user),
        )


@router.callback_query(F.data == "settings:topic_clear")
async def topic_clear(callback: CallbackQuery, user: User | None, db: Database, app_settings: Settings, state: FSMContext) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    updated = await db.update_user_settings(user.user_id, {"notification_topic_id": None})
    if not updated:
        await callback.answer("Ошибка", show_alert=True)
        return
    await callback.message.edit_text(
        format_settings_text(updated, app_settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(updated),
    )
    await callback.answer("Топик отключён")


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

    await callback.message.edit_text(
        format_settings_text(updated, app_settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(updated),
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

    await callback.message.edit_text(
        format_settings_text(updated, app_settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(updated),
    )
    await callback.answer("Автоочистка " + ("включена" if new_value else "выключена"))
