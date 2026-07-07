from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.database import Database
from bot.keyboards import MAIN_MENU, MAIN_MENU_BUTTONS
from bot.states import SettingsStates
from bot.users import DISPLAY_FIELD_ICONS, DISPLAY_FIELD_LABELS, User
from bot.utils.chat import send_menu_message, track_message

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
        [InlineKeyboardButton(text=topic_label, callback_data="settings:topic_menu")],
    ]
    if user.is_admin:
        rows.append([InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users")])
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


def topic_menu_keyboard(user: User) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if user.settings.notification_topic_id:
        rows.append(
            [InlineKeyboardButton(text="🔄 Сменить топик", callback_data="settings:topic_bind")]
        )
        rows.append(
            [InlineKeyboardButton(text="❌ Отключить топик", callback_data="settings:topic_clear")]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="📬 Привязать топик", callback_data="settings:topic_bind")]
        )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_settings_text(user: User, app_settings: Settings) -> str:
    access_label = "открытый" if app_settings.access_mode == "open" else "по приглашению"
    photos = "включены" if user.settings.photos_enabled else "выключены"
    auto_clear = "включена" if user.settings.auto_clear_chat else "выключена"
    topic = (
        f"включён (ID {user.settings.notification_topic_id})"
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
        f"📬 Топик уведомлений: {topic}",
        f"🔒 Режим доступа: {access_label}",
    ]
    if app_settings.access_mode == "invite" and not user.is_admin:
        lines.append("\n<i>Чтобы пригласить кого-то — передайте админу свой ID выше.</i>")
    return "\n".join(lines)


def format_topic_help_text() -> str:
    return (
        "<b>📬 Топик для уведомлений</b>\n\n"
        "Чтобы меню бота и уведомления не смешивались:\n"
        "1. В чате с ботом откройте меню ⋮ → <b>Темы</b>\n"
        "2. Создайте тему, например «Уведомления»\n"
        "3. Зайдите в эту тему и отправьте сюда любое сообщение\n\n"
        "<i>Команды и меню останутся в общем чате, а новые объявления придут в тему.</i>"
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


@router.callback_query(F.data == "settings:topic_menu")
async def topic_menu(callback: CallbackQuery, user: User | None, app_settings: Settings) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        format_topic_help_text(),
        parse_mode="HTML",
        reply_markup=topic_menu_keyboard(user),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:topic_bind")
async def topic_bind_start(callback: CallbackQuery, user: User | None, state: FSMContext) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(SettingsStates.waiting_notification_topic)
    await callback.message.edit_text(
        format_topic_help_text() + "\n\n<b>Жду сообщение из нужной темы…</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="settings:topic_cancel")]]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:topic_cancel")
async def topic_bind_cancel(
    callback: CallbackQuery,
    user: User | None,
    app_settings: Settings,
    state: FSMContext,
) -> None:
    if not user:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        format_topic_help_text(),
        parse_mode="HTML",
        reply_markup=topic_menu_keyboard(user),
    )
    await callback.answer("Отменено")


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


@router.message(SettingsStates.waiting_notification_topic)
async def topic_bind_message(
    message: Message,
    user: User | None,
    db: Database,
    app_settings: Settings,
    state: FSMContext,
) -> None:
    if not user:
        await state.clear()
        return

    topic_id = message.message_thread_id
    if not topic_id:
        sent = await message.answer(
            "Это сообщение не из темы.\n\n"
            "Создайте тему в чате с ботом и отправьте сообщение <b>внутри неё</b>.",
            parse_mode="HTML",
        )
        await track_message(message.from_user.id, sent.message_id)
        return

    updated = await db.update_user_settings(
        user.user_id,
        {"notification_topic_id": topic_id},
    )
    await state.clear()
    if not updated:
        sent = await message.answer("Не удалось сохранить топик.")
        await track_message(message.from_user.id, sent.message_id)
        return

    sent = await message.answer(
        "✅ Топик привязан. Новые объявления будут приходить сюда.\n\n"
        + format_settings_text(updated, app_settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(updated),
        message_thread_id=topic_id,
    )
    await track_message(message.from_user.id, sent.message_id)


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
