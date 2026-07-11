from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.access import extract_forwarded_user, extract_shared_user_ids, forwarded_user_error_hint
from bot.database import Database
from bot.users import User
from bot.utils.chat import track_message

router = Router()


class AdminStates(StatesGroup):
    waiting_user_id = State()


def _require_admin(user: User | None) -> bool:
    return user is not None and user.is_admin


def admin_users_keyboard(users: list[User], alert_counts: dict[int, int]) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        icon = "🟢" if u.active else "⚪️"
        crown = "👑 " if u.is_admin else ""
        count = alert_counts.get(u.user_id, 0)
        label = f"{icon} {crown}{u.display_name} ({count})"
        if len(label) > 60:
            label = label[:57] + "..."
        rows.append([InlineKeyboardButton(text=label, callback_data=f"admin:user:{u.user_id}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="admin:add")])
    rows.append([InlineKeyboardButton(text="◀️ Настройки", callback_data="admin:back_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_detail_keyboard(target: User, current_admin_id: int) -> InlineKeyboardMarkup:
    rows = []
    if target.active:
        rows.append([InlineKeyboardButton(text="⛔️ Заблокировать", callback_data=f"admin:deactivate:{target.user_id}")])
    else:
        rows.append([InlineKeyboardButton(text="✅ Разрешить доступ", callback_data=f"admin:activate:{target.user_id}")])

    if target.user_id != current_admin_id:
        if target.is_admin:
            rows.append([InlineKeyboardButton(text="👤 Снять админа", callback_data=f"admin:demote:{target.user_id}")])
        else:
            rows.append([InlineKeyboardButton(text="👑 Сделать админом", callback_data=f"admin:promote:{target.user_id}")])
        rows.append([InlineKeyboardButton(text="🗑 Удалить пользователя", callback_data=f"admin:delete_user:{target.user_id}")])

    rows.append([InlineKeyboardButton(text="◀️ К списку", callback_data="admin:users")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_delete_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❌ Да, удалить", callback_data=f"admin:delete_user_confirm:{user_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"admin:user:{user_id}"),
            ],
        ]
    )


async def _format_users_list(db: Database) -> tuple[str, InlineKeyboardMarkup]:
    users = await db.list_users()
    alert_counts = {u.user_id: await db.count_user_alerts(u.user_id) for u in users}
    active = sum(1 for u in users if u.active)
    text = (
        f"<b>👥 Пользователи</b> ({len(users)})\n\n"
        f"🟢 {active} с доступом · ⚪️ {len(users) - active} заблокированы\n\n"
        "Выберите пользователя:"
    )
    return text, admin_users_keyboard(users, alert_counts)


async def _format_user_detail(db: Database, user_id: int, current_admin_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    target = await db.get_user(user_id)
    if not target:
        return None
    alerts = await db.count_user_alerts(user_id)
    status = "✅ доступ есть" if target.active else "⛔️ заблокирован"
    role = "администратор" if target.is_admin else "пользователь"
    lines = [
        f"<b>{target.display_name}</b>",
        "",
        f"🆔 <code>{target.user_id}</code>",
    ]
    if target.username:
        lines.append(f"📎 @{target.username}")
    lines.extend([f"🔑 {role}", f"📋 {status}", f"📌 Подписок: {alerts}"])
    return "\n".join(lines), admin_user_detail_keyboard(target, current_admin_id)


@router.message(Command("users"))
async def cmd_users(message: Message, user: User | None, db: Database) -> None:
    if not _require_admin(user):
        sent = await message.answer("Только для администраторов.")
        await track_message(message.from_user.id, sent.message_id)
        return
    text, kb = await _format_users_list(db)
    sent = await message.answer(text, parse_mode="HTML", reply_markup=kb)
    await track_message(message.from_user.id, sent.message_id)


@router.message(Command("adduser"))
async def cmd_adduser(message: Message, user: User | None, db: Database) -> None:
    if not _require_admin(user):
        sent = await message.answer("Только для администраторов.")
        await track_message(message.from_user.id, sent.message_id)
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        sent = await message.answer("Использование: /adduser TELEGRAM_ID")
        await track_message(message.from_user.id, sent.message_id)
        return
    new_id = int(parts[1])
    await db.upsert_user(new_id, active=True, role="user")
    sent = await message.answer(f"✅ Пользователь <code>{new_id}</code> добавлен.", parse_mode="HTML")
    await track_message(message.from_user.id, sent.message_id)


@router.callback_query(F.data == "admin:users")
async def admin_users_cb(callback: CallbackQuery, user: User | None, db: Database) -> None:
    if not _require_admin(user):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    text, kb = await _format_users_list(db)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin:add")
async def admin_add_cb(callback: CallbackQuery, user: User | None, state: FSMContext) -> None:
    if not _require_admin(user):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_user_id)
    await callback.message.edit_text(
        "<b>➕ Добавить пользователя</b>\n\n"
        "Отправьте Telegram ID нового пользователя.\n"
        "Человек может узнать ID, отправив боту /start.\n\n"
        "Или перешлите любое сообщение от этого человека.\n"
        "Если ID не определяется — у пользователя скрыта пересылка, введите ID вручную.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.waiting_user_id)
async def admin_add_id(message: Message, user: User | None, db: Database, state: FSMContext) -> None:
    if not _require_admin(user):
        await state.clear()
        return

    target_id: int | None = None
    profile: dict[str, str | None] = {}

    shared_ids = extract_shared_user_ids(message)
    if len(shared_ids) == 1:
        target_id = shared_ids[0]
    elif len(shared_ids) > 1:
        sent = await message.answer("Выберите одного пользователя — отправьте одну пересылку или один ID.")
        await track_message(message.from_user.id, sent.message_id)
        return
    else:
        forwarded = extract_forwarded_user(message)
        if forwarded:
            target_id, profile = forwarded
        elif (message.text or "").strip().isdigit():
            target_id = int((message.text or "").strip())
        else:
            sent = await message.answer(forwarded_user_error_hint(message))
            await track_message(message.from_user.id, sent.message_id)
            return

    await db.upsert_user(target_id, active=True, role="user", **profile)
    await state.clear()
    text, kb = await _format_users_list(db)
    sent = await message.answer(
        f"✅ Пользователь <code>{target_id}</code> добавлен.\n\n{text}",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await track_message(message.from_user.id, sent.message_id)


@router.callback_query(F.data.startswith("admin:user:"))
async def admin_user_detail_cb(callback: CallbackQuery, user: User | None, db: Database) -> None:
    if not _require_admin(user):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    target_id = int(callback.data.split(":")[-1])
    result = await _format_user_detail(db, target_id, user.user_id)
    if not result:
        await callback.answer("Не найден", show_alert=True)
        return
    text, kb = result
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:activate:"))
async def admin_activate_cb(callback: CallbackQuery, user: User | None, db: Database) -> None:
    if not _require_admin(user):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    target_id = int(callback.data.split(":")[-1])
    await db.set_user_active(target_id, True)
    result = await _format_user_detail(db, target_id, user.user_id)
    if result:
        await callback.message.edit_text(result[0], parse_mode="HTML", reply_markup=result[1])
    await callback.answer("✅ Доступ открыт")


@router.callback_query(F.data.startswith("admin:deactivate:"))
async def admin_deactivate_cb(callback: CallbackQuery, user: User | None, db: Database) -> None:
    if not _require_admin(user):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    target_id = int(callback.data.split(":")[-1])
    if target_id == user.user_id:
        await callback.answer("Нельзя заблокировать себя", show_alert=True)
        return
    await db.set_user_active(target_id, False)
    result = await _format_user_detail(db, target_id, user.user_id)
    if result:
        await callback.message.edit_text(result[0], parse_mode="HTML", reply_markup=result[1])
    await callback.answer("⛔️ Доступ закрыт")


@router.callback_query(F.data.startswith("admin:promote:"))
async def admin_promote_cb(callback: CallbackQuery, user: User | None, db: Database) -> None:
    if not _require_admin(user):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    target_id = int(callback.data.split(":")[-1])
    await db.set_user_role(target_id, "admin")
    result = await _format_user_detail(db, target_id, user.user_id)
    if result:
        await callback.message.edit_text(result[0], parse_mode="HTML", reply_markup=result[1])
    await callback.answer("👑 Назначен админом")


@router.callback_query(F.data.startswith("admin:demote:"))
async def admin_demote_cb(callback: CallbackQuery, user: User | None, db: Database) -> None:
    if not _require_admin(user):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    target_id = int(callback.data.split(":")[-1])
    if target_id == user.user_id:
        await callback.answer("Нельзя снять админа с себя", show_alert=True)
        return
    await db.set_user_role(target_id, "user")
    result = await _format_user_detail(db, target_id, user.user_id)
    if result:
        await callback.message.edit_text(result[0], parse_mode="HTML", reply_markup=result[1])
    await callback.answer("Роль изменена")


@router.callback_query(F.data.startswith("admin:delete_user_confirm:"))
async def admin_delete_user_confirm_cb(callback: CallbackQuery, user: User | None, db: Database) -> None:
    if not _require_admin(user):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    target_id = int(callback.data.split(":")[-1])
    if target_id == user.user_id:
        await callback.answer("Нельзя удалить себя", show_alert=True)
        return
    target = await db.get_user(target_id)
    if not target:
        await callback.answer("Уже удалён", show_alert=True)
        return
    name = target.display_name
    if not await db.delete_user(target_id):
        await callback.answer("Не удалось удалить", show_alert=True)
        return
    text, kb = await _format_users_list(db)
    await callback.message.edit_text(
        f"🗑 Пользователь <b>{name}</b> удалён.\n\n{text}",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer("Удалено")


@router.callback_query(F.data.startswith("admin:delete_user:"))
async def admin_delete_user_cb(callback: CallbackQuery, user: User | None, db: Database) -> None:
    if not _require_admin(user):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    target_id = int(callback.data.split(":")[-1])
    if target_id == user.user_id:
        await callback.answer("Нельзя удалить себя", show_alert=True)
        return
    target = await db.get_user(target_id)
    if not target:
        await callback.answer("Не найден", show_alert=True)
        return
    alerts = await db.count_user_alerts(target_id)
    await callback.message.edit_text(
        f"Удалить пользователя <b>{target.display_name}</b>?\n\n"
        f"🆔 <code>{target_id}</code>\n"
        f"📌 Подписок: {alerts}\n\n"
        "Будут удалены все подписки и данные пользователя. Это нельзя отменить.",
        parse_mode="HTML",
        reply_markup=admin_user_delete_confirm_keyboard(target_id),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:back_settings")
async def admin_back_settings(callback: CallbackQuery, user: User | None, db: Database) -> None:
    from bot.config import get_settings
    from bot.handlers.settings import settings_screen

    if not user:
        await callback.answer()
        return
    app_settings = get_settings()
    text, keyboard = await settings_screen(db, user, app_settings)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer()
