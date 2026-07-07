from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.database import Database
from bot.keyboards import MAIN_MENU, MAIN_MENU_BUTTONS
from bot.users import User
from bot.utils.chat import track_message

router = Router()


def settings_keyboard(user: User) -> InlineKeyboardMarkup:
    photos_label = "🖼 Фото: вкл" if user.settings.photos_enabled else "🖼 Фото: выкл"
    rows = [
        [InlineKeyboardButton(text=photos_label, callback_data="settings:toggle_photos")],
    ]
    if user.is_admin:
        rows.append([InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_settings_text(user: User, app_settings: Settings) -> str:
    access_label = "открытый" if app_settings.access_mode == "open" else "по приглашению"
    photos = "включены" if user.settings.photos_enabled else "выключены"
    role = "администратор" if user.is_admin else "пользователь"

    lines = [
        "<b>⚙️ Настройки</b>",
        "",
        f"👤 {user.display_name}",
        f"🆔 <code>{user.user_id}</code>",
        f"🔑 Роль: {role}",
        "",
        f"🖼 Фото в уведомлениях: {photos}",
        f"🔒 Режим доступа: {access_label}",
    ]
    if app_settings.access_mode == "invite" and not user.is_admin:
        lines.append("\n<i>Чтобы пригласить кого-то — передайте админу свой ID выше.</i>")
    return "\n".join(lines)


@router.message(Command("settings"))
@router.message(F.text == MAIN_MENU_BUTTONS["settings"])
async def cmd_settings(message: Message, user: User | None, db: Database, app_settings: Settings) -> None:
    if not user:
        sent = await message.answer(
            "🔒 Нет доступа. Отправьте /start — там будет ваш ID для администратора.",
            parse_mode="HTML",
        )
        await track_message(message.from_user.id, sent.message_id)
        return

    sent = await message.answer(
        format_settings_text(user, app_settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(user),
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
