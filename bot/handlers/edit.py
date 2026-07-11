from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.database import Alert, Database, parse_kufar_url
from bot.keyboards import MAIN_MENU, skip_keyboard
from bot.navigation import home_row
from bot.handlers.pickers import show_category_picker, show_extra_filters_picker, show_region_picker
from bot.kufar import KufarClient, build_search_url
from bot.price import PRICE_INPUT_HINT, format_price_display, parse_price_input
from bot.seeding import seed_alert
from bot.states import EditAlertStates
from bot.ui import alert_detail_keyboard, format_alert_card
from bot.users import User
from bot.utils.chat import prepare_menu_message, send_menu_message, send_panel_message, track_message, WizardCleaner

router = Router()

CLEAR_HINT = "\n\nОтправьте <code>-</code> чтобы убрать фильтр."


def edit_fields_keyboard(alert_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Название", callback_data=f"edit:field:{alert_id}:name")],
            [InlineKeyboardButton(text="🔎 Запрос", callback_data=f"edit:field:{alert_id}:query")],
            [InlineKeyboardButton(text="🔗 Ссылка Kufar", callback_data=f"edit:field:{alert_id}:url")],
            [InlineKeyboardButton(text="📂 Категория", callback_data=f"edit:field:{alert_id}:cat")],
            [InlineKeyboardButton(text="📍 Место", callback_data=f"edit:field:{alert_id}:loc")],
            [InlineKeyboardButton(text="💰 Цена", callback_data=f"edit:field:{alert_id}:price")],
            [InlineKeyboardButton(text="⚙️ Доп. фильтры", callback_data=f"edit:field:{alert_id}:extra")],
            [InlineKeyboardButton(text="◀️ К подписке", callback_data=f"alert:view:{alert_id}")],
            home_row(),
        ]
    )


async def _seed_alert(alert: Alert, kufar: KufarClient, db: Database) -> int:
    return await seed_alert(db, kufar, alert, clear_first=True)


async def _finish_edit(
    message: Message,
    state: FSMContext,
    db: Database,
    kufar: KufarClient,
    alert: Alert,
    user: User | None = None,
    *,
    reseed: bool = True,
) -> None:
    cleaner = WizardCleaner(state, user, db)
    await cleaner.cleanup_wizard(message.bot, message.chat.id, message.from_user.id)
    seeded = await _seed_alert(alert, kufar, db) if reseed else 0
    await state.clear()
    text = f"✅ <b>Подписка обновлена!</b>\n\n{format_alert_card(alert)}"
    if reseed:
        if seeded >= 0:
            text += f"\n\n📥 Загружено {seeded} объявлений — уведомления только о новых."
        else:
            text += "\n\n⚠️ Не удалось обновить список — проверьте фильтры."
    sent = await send_panel_message(
        message.bot,
        message.chat.id,
        message.from_user.id,
        user,
        db,
        text,
        parse_mode="HTML",
        reply_markup=alert_detail_keyboard(alert),
        disable_web_page_preview=True,
    )


@router.message(Command("edit"))
async def cmd_edit(message: Message, state: FSMContext, db: Database, user: User | None) -> None:
    parts = (message.text or "").split()
    user_id = message.from_user.id

    if len(parts) >= 2 and parts[1].isdigit():
        await prepare_menu_message(message, user, state, db)
        alert_id = int(parts[1])
        alert = await db.get_alert(alert_id, user_id)
        if not alert:
            sent = await message.answer("Подписка не найдена.")
            await track_message(user_id, sent.message_id)
            return
        await state.update_data(edit_alert_id=alert_id)
        sent = await message.answer(
            f"<b>✏️ Редактирование</b>\n\n{format_alert_card(alert)}\n\nЧто изменить?",
            parse_mode="HTML",
            reply_markup=edit_fields_keyboard(alert_id),
            disable_web_page_preview=True,
        )
        await track_message(user_id, sent.message_id)
        return

    sent = await message.answer(
        "Откройте <b>📋 Мои подписки</b>, выберите подписку и нажмите <b>✏️ Изменить</b>.",
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
    )
    await track_message(user_id, sent.message_id)


@router.callback_query(F.data == "edit:cancel")
async def edit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Редактирование отменено.")
    await callback.answer()


@router.callback_query(F.data.startswith("edit:field:"))
async def edit_field_pick(callback: CallbackQuery, state: FSMContext, db: Database, kufar: KufarClient) -> None:
    _, _, alert_id_str, field = callback.data.split(":", 3)
    alert_id = int(alert_id_str)
    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return

    await state.update_data(edit_alert_id=alert_id)

    if field == "name":
        await callback.message.edit_text(
            f"Текущее название: <b>{alert.name}</b>\n\nВведите новое название:",
            parse_mode="HTML",
        )
        await state.set_state(EditAlertStates.waiting_name)
    elif field == "query":
        current = alert.query or "—"
        await callback.message.edit_text(
            f"Текущий запрос: <code>{current}</code>\n\nВведите новый поисковый запрос:{CLEAR_HINT}",
            parse_mode="HTML",
        )
        await state.set_state(EditAlertStates.waiting_query)
    elif field == "url":
        url = build_search_url(alert.query, **{k: v for k, v in alert.params.items() if not k.startswith("_")})
        await callback.message.edit_text(
            f"Текущий поиск:\n<a href=\"{url}\">{url}</a>\n\n"
            "Отправьте новую ссылку с kufar.by — она заменит запрос и все фильтры.",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await state.set_state(EditAlertStates.waiting_url)
    elif field == "cat":
        await state.update_data(flow="edit", params=dict(alert.params))
        await show_category_picker(callback, state, kufar)
    elif field == "loc":
        await state.update_data(flow="edit", params=dict(alert.params))
        await show_region_picker(callback, state)
    elif field == "price":
        current = format_price_display(alert.params.get("prc")) or "—"
        await callback.message.edit_text(
            f"Текущая цена: <b>{current}</b>\n\n{PRICE_INPUT_HINT}",
            parse_mode="HTML",
            reply_markup=skip_keyboard(f"edit:skip_price:{alert_id}"),
        )
        await state.set_state(EditAlertStates.waiting_price)
    elif field == "extra":
        await state.update_data(flow="edit", params=dict(alert.params))
        await show_extra_filters_picker(callback, state)

    await callback.answer()


@router.message(EditAlertStates.waiting_name)
async def edit_name(message: Message, state: FSMContext, db: Database, kufar: KufarClient, user: User | None) -> None:
    cleaner = WizardCleaner(state, user, db)
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    name = (message.text or "").strip()
    if not name:
        await cleaner.send(message, "Название не может быть пустым.", delete_user=True)
        return

    alert = await db.update_alert(alert_id, message.from_user.id, name=name)
    if not alert:
        await cleaner.send(message, "Подписка не найдена.", delete_user=True)
        await state.clear()
        return

    await cleaner.delete_user(message)
    await _finish_edit(message, state, db, kufar, alert, user, reseed=False)


@router.message(EditAlertStates.waiting_query)
async def edit_query(message: Message, state: FSMContext, db: Database, kufar: KufarClient, user: User | None) -> None:
    cleaner = WizardCleaner(state, user, db)
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    text = (message.text or "").strip()
    query = "" if text == "-" else text

    alert = await db.update_alert(alert_id, message.from_user.id, query=query)
    if not alert:
        await cleaner.send(message, "Подписка не найдена.", delete_user=True)
        await state.clear()
        return

    await cleaner.delete_user(message)
    await _finish_edit(message, state, db, kufar, alert, user)


@router.message(EditAlertStates.waiting_url)
async def edit_url(message: Message, state: FSMContext, db: Database, kufar: KufarClient, user: User | None) -> None:
    cleaner = WizardCleaner(state, user, db)
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    try:
        query, params = parse_kufar_url(message.text or "")
    except ValueError as exc:
        await cleaner.send(message, str(exc), delete_user=True)
        return

    alert = await db.update_alert(alert_id, message.from_user.id, query=query, params=params)
    if not alert:
        await cleaner.send(message, "Подписка не найдена.", delete_user=True)
        await state.clear()
        return

    await cleaner.delete_user(message)
    await _finish_edit(message, state, db, kufar, alert, user)


@router.callback_query(F.data.startswith("edit:skip_price:"))
async def edit_skip_price(callback: CallbackQuery, state: FSMContext, db: Database, kufar: KufarClient, user: User | None) -> None:
    alert_id = int(callback.data.split(":")[-1])
    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена.", show_alert=True)
        await state.clear()
        return

    params = dict(alert.params)
    params.pop("prc", None)
    alert = await db.update_alert(alert_id, callback.from_user.id, params=params)
    await callback.message.delete()
    await _finish_edit(callback.message, state, db, kufar, alert, user)
    await callback.answer()


@router.message(EditAlertStates.waiting_price)
async def edit_price(message: Message, state: FSMContext, db: Database, kufar: KufarClient, user: User | None) -> None:
    cleaner = WizardCleaner(state, user, db)
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")

    alert = await db.get_alert(alert_id, message.from_user.id)
    if not alert:
        await cleaner.send(message, "Подписка не найдена.", delete_user=True)
        await state.clear()
        return

    try:
        prc = parse_price_input(message.text or "")
    except ValueError as exc:
        await cleaner.send(message, str(exc), parse_mode="HTML", delete_user=True)
        return

    params = dict(alert.params)
    if prc:
        params["prc"] = prc
    else:
        params.pop("prc", None)

    alert = await db.update_alert(alert_id, message.from_user.id, params=params)
    await cleaner.delete_user(message)
    await _finish_edit(message, state, db, kufar, alert, user)
