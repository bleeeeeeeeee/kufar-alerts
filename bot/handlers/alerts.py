from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.database import Database, parse_kufar_url
from bot.handlers.pickers import show_category_picker
from bot.keyboards import MAIN_MENU, MAIN_MENU_BUTTONS, skip_keyboard
from bot.kufar import KufarClient
from bot.price import PRICE_INPUT_HINT, parse_price_input
from bot.seeding import seed_alert
from bot.states import NewAlertStates
from bot.ui import (
    alert_delete_confirm_keyboard,
    alert_detail_keyboard,
    alerts_list_keyboard,
    confirm_subscription_keyboard,
    format_alert_card,
    format_alerts_overview,
    format_draft_preview,
    new_subscription_keyboard,
)
from bot.utils.chat import WizardCleaner, track_message

router = Router()


async def _show_alert_detail(target: Message, alert, user_id: int) -> None:
    sent = await target.answer(
        format_alert_card(alert),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=alert_detail_keyboard(alert),
    )
    await track_message(user_id, sent.message_id)


async def _edit_alert_detail(callback: CallbackQuery, alert) -> None:
    await callback.message.edit_text(
        format_alert_card(alert),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=alert_detail_keyboard(alert),
    )


async def _show_draft(message: Message, state: FSMContext, cleaner: WizardCleaner) -> None:
    data = await state.get_data()
    query = data.get("query", "")
    params = data.get("params", {})
    name = data.get("name") or query or "Подписка"

    await cleaner.send(
        message,
        format_draft_preview(name, query, params),
        parse_mode="HTML",
        reply_markup=confirm_subscription_keyboard(),
        disable_web_page_preview=True,
        delete_user=True,
    )
    await state.set_state(NewAlertStates.confirm)


@router.message(Command("new"))
@router.message(F.text == MAIN_MENU_BUTTONS["new"])
@router.callback_query(F.data == "alert:new")
async def cmd_new(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text = (
        "<b>➕ Новая подписка</b>\n\n"
        "Самый быстрый способ — вставить ссылку с поиска на kufar.by.\n"
        "Или настройте фильтры вручную шаг за шагом."
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=new_subscription_keyboard())
        await event.answer()
    else:
        cleaner = WizardCleaner(state)
        await cleaner.send(event, text, parse_mode="HTML", reply_markup=new_subscription_keyboard())
    await state.set_state(NewAlertStates.waiting_method)


@router.callback_query(F.data == "new:cancel")
async def cancel_new(callback: CallbackQuery, state: FSMContext) -> None:
    cleaner = WizardCleaner(state)
    await cleaner.cleanup_wizard(callback.message.bot, callback.message.chat.id)
    await state.clear()
    sent = await callback.message.answer("Создание подписки отменено.", reply_markup=MAIN_MENU)
    await track_message(callback.from_user.id, sent.message_id)
    await callback.answer()


@router.callback_query(F.data == "new:url", NewAlertStates.waiting_method)
async def new_via_url(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "<b>Шаг 1/1 — Ссылка</b>\n\n"
        "Отправьте ссылку на страницу поиска с kufar.by.\n\n"
        "Пример:\n"
        "<code>https://www.kufar.by/l?query=iphone&rgn=1</code>",
        parse_mode="HTML",
    )
    await state.set_state(NewAlertStates.waiting_url)
    await callback.answer()


@router.callback_query(F.data == "new:manual", NewAlertStates.waiting_method)
async def new_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(query="", params={}, flow="new")
    await callback.message.edit_text(
        "<b>Шаг 1/5 — Поисковый запрос</b>\n\n"
        "Введите слова для поиска в названии объявления.\n"
        "Или нажмите «Пропустить», если нужны только фильтры.",
        parse_mode="HTML",
        reply_markup=skip_keyboard("new:skip_query"),
    )
    await state.set_state(NewAlertStates.waiting_query)
    await callback.answer()


@router.message(NewAlertStates.waiting_url)
async def process_url(message: Message, state: FSMContext) -> None:
    cleaner = WizardCleaner(state)
    try:
        query, params = parse_kufar_url(message.text or "")
    except ValueError as exc:
        await cleaner.send(message, str(exc), delete_user=True)
        return

    name = query or "Подписка"
    if params.get("cat"):
        from bot.catalog import category_name
        name = query or category_name(params["cat"]) or name

    await state.update_data(query=query, params=params, name=str(name))
    await _show_draft(message, state, cleaner)


@router.callback_query(F.data == "new:skip_query", NewAlertStates.waiting_query)
async def skip_query(callback: CallbackQuery, state: FSMContext, kufar: KufarClient) -> None:
    await state.update_data(flow="new")
    await callback.message.edit_text("<b>Шаг 2/5 — Категория</b>", parse_mode="HTML")
    await show_category_picker(callback, state, kufar)
    await callback.answer()


@router.message(NewAlertStates.waiting_query)
async def process_query(message: Message, state: FSMContext, kufar: KufarClient) -> None:
    cleaner = WizardCleaner(state)
    query = (message.text or "").strip()
    await state.update_data(query=query, flow="new")
    await cleaner.delete_user(message)
    sent = await message.answer("<b>Шаг 2/5 — Категория</b>", parse_mode="HTML")
    await track_message(message.from_user.id, sent.message_id)
    await show_category_picker(message, state, kufar)


@router.callback_query(F.data == "new:skip_price", NewAlertStates.waiting_price)
async def skip_price(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "<b>Шаг 5/5 — Название</b>\n\n"
        "Как назвать подписку? (для удобства в списке)",
        parse_mode="HTML",
    )
    await state.set_state(NewAlertStates.waiting_name)
    await callback.answer()


@router.message(NewAlertStates.waiting_price)
async def process_price(message: Message, state: FSMContext) -> None:
    cleaner = WizardCleaner(state)
    try:
        prc = parse_price_input(message.text or "")
    except ValueError as exc:
        await cleaner.send(message, str(exc), parse_mode="HTML", delete_user=True)
        return

    data = await state.get_data()
    params = data.get("params", {})
    if prc:
        params["prc"] = prc
    else:
        params.pop("prc", None)
    await state.update_data(params=params)

    await cleaner.send(
        message,
        "<b>Шаг 5/5 — Название</b>\n\nКак назвать подписку?",
        parse_mode="HTML",
        delete_user=True,
    )
    await state.set_state(NewAlertStates.waiting_name)


@router.message(NewAlertStates.waiting_name)
async def process_name(message: Message, state: FSMContext) -> None:
    cleaner = WizardCleaner(state)
    name = (message.text or "").strip() or "Подписка"
    await state.update_data(name=name)
    await _show_draft(message, state, cleaner)


@router.callback_query(F.data == "new:confirm", NewAlertStates.confirm)
async def confirm_new(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    kufar: KufarClient,
) -> None:
    cleaner = WizardCleaner(state)
    data = await state.get_data()
    query = data.get("query", "")
    params = {k: v for k, v in data.get("params", {}).items() if not k.startswith("_")}
    name = data.get("name") or query or "Подписка"

    alert = await db.create_alert(
        user_id=callback.from_user.id,
        name=name,
        query=query,
        params=params,
    )

    seeded = await seed_alert(db, kufar, alert)
    seed_note = (
        f"📥 Загружено {seeded} текущих объявлений.\n"
        "Уведомления придут только о <b>новых</b>."
        if seeded >= 0
        else "⚠️ Не удалось загрузить объявления — проверьте фильтры."
    )

    await cleaner.cleanup_wizard(callback.message.bot, callback.message.chat.id)
    await state.clear()

    try:
        await callback.message.delete()
    except Exception:
        pass

    sent = await callback.message.answer(
        f"✅ <b>Подписка создана!</b>\n\n{format_alert_card(alert)}\n\n{seed_note}",
        parse_mode="HTML",
        reply_markup=alert_detail_keyboard(alert),
        disable_web_page_preview=True,
    )
    await track_message(callback.from_user.id, sent.message_id)
    await callback.answer("Подписка создана!")


@router.message(Command("list"))
@router.message(F.text == MAIN_MENU_BUTTONS["list"])
@router.callback_query(F.data == "alert:list")
async def cmd_list(event: Message | CallbackQuery, db: Database) -> None:
    user_id = event.from_user.id
    alerts = await db.get_user_alerts(user_id)

    if not alerts:
        text = (
            "У вас пока нет подписок.\n\n"
            "Нажмите <b>➕ Новая подписка</b> или вставьте ссылку с kufar.by."
        )
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(text, parse_mode="HTML", reply_markup=new_subscription_keyboard())
            await event.answer()
        else:
            sent = await event.answer(text, parse_mode="HTML", reply_markup=MAIN_MENU)
            await track_message(user_id, sent.message_id)
        return

    text = format_alerts_overview(alerts)
    kb = alerts_list_keyboard(alerts)

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        await event.answer()
    else:
        sent = await event.answer(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        await track_message(user_id, sent.message_id)


@router.callback_query(F.data.startswith("alert:view:"))
async def alert_view_cb(callback: CallbackQuery, db: Database) -> None:
    alert_id = int(callback.data.split(":")[-1])
    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    await _edit_alert_detail(callback, alert)
    await callback.answer()


@router.callback_query(F.data.startswith("alert:pause:"))
async def alert_pause_cb(callback: CallbackQuery, db: Database) -> None:
    alert_id = int(callback.data.split(":")[-1])
    if not await db.set_alert_active(alert_id, callback.from_user.id, False):
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    alert = await db.get_alert(alert_id, callback.from_user.id)
    await _edit_alert_detail(callback, alert)
    await callback.answer("⏸ Подписка на паузе")


@router.callback_query(F.data.startswith("alert:resume:"))
async def alert_resume_cb(callback: CallbackQuery, db: Database, kufar: KufarClient) -> None:
    alert_id = int(callback.data.split(":")[-1])
    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    if not await db.set_alert_active(alert_id, callback.from_user.id, True):
        await callback.answer("Не удалось возобновить", show_alert=True)
        return
    alert = await db.get_alert(alert_id, callback.from_user.id)
    seeded = await seed_alert(db, kufar, alert, clear_first=True)
    await _edit_alert_detail(callback, alert)
    note = f", синхронизировано {seeded} объявлений" if seeded >= 0 else ""
    await callback.answer(f"✅ Подписка возобновлена{note}")


@router.callback_query(F.data.startswith("alert:resync:"))
async def alert_resync_cb(callback: CallbackQuery, db: Database, kufar: KufarClient) -> None:
    alert_id = int(callback.data.split(":")[-1])
    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    seeded = await seed_alert(db, kufar, alert, clear_first=True)
    if seeded >= 0:
        await callback.answer(f"🔄 Синхронизировано: {seeded} объявлений")
    else:
        await callback.answer("Ошибка синхронизации", show_alert=True)


@router.callback_query(F.data.startswith("alert:delete:"))
async def alert_delete_cb(callback: CallbackQuery, db: Database) -> None:
    alert_id = int(callback.data.split(":")[-1])
    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    await callback.message.edit_text(
        f"Удалить подписку <b>{alert.name}</b>?\n\nЭто действие нельзя отменить.",
        parse_mode="HTML",
        reply_markup=alert_delete_confirm_keyboard(alert_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("alert:delete_confirm:"))
async def alert_delete_confirm_cb(callback: CallbackQuery, db: Database) -> None:
    alert_id = int(callback.data.split(":")[-1])
    if not await db.delete_alert(alert_id, callback.from_user.id):
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    alerts = await db.get_user_alerts(callback.from_user.id)
    if alerts:
        await callback.message.edit_text(
            format_alerts_overview(alerts),
            parse_mode="HTML",
            reply_markup=alerts_list_keyboard(alerts),
            disable_web_page_preview=True,
        )
    else:
        await callback.message.edit_text(
            "🗑 Подписка удалена.\n\nУ вас больше нет подписок.",
            reply_markup=new_subscription_keyboard(),
        )
    await callback.answer("Подписка удалена")


@router.callback_query(F.data.startswith("alert:edit:"))
async def alert_edit_cb(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    from bot.handlers.edit import edit_fields_keyboard

    alert_id = int(callback.data.split(":")[-1])
    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    await state.update_data(edit_alert_id=alert_id)
    await callback.message.edit_text(
        f"<b>✏️ Редактирование</b>\n\n{format_alert_card(alert)}\n\nЧто изменить?",
        parse_mode="HTML",
        reply_markup=edit_fields_keyboard(alert_id),
        disable_web_page_preview=True,
    )
    await callback.answer()


# Legacy commands — still work but UI prefers buttons
@router.message(Command("pause"))
async def cmd_pause(message: Message, db: Database) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        sent = await message.answer("Укажите ID подписки или откройте 📋 Мои подписки.")
        await track_message(message.from_user.id, sent.message_id)
        return
    alert_id = int(parts[1])
    if await db.set_alert_active(alert_id, message.from_user.id, False):
        alert = await db.get_alert(alert_id, message.from_user.id)
        await _show_alert_detail(message, alert, message.from_user.id)
    else:
        sent = await message.answer("Подписка не найдена.")
        await track_message(message.from_user.id, sent.message_id)


@router.message(Command("resume"))
async def cmd_resume(message: Message, db: Database, kufar: KufarClient) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        sent = await message.answer("Укажите ID подписки или откройте 📋 Мои подписки.")
        await track_message(message.from_user.id, sent.message_id)
        return
    alert_id = int(parts[1])
    alert = await db.get_alert(alert_id, message.from_user.id)
    if not alert:
        sent = await message.answer("Подписка не найдена.")
        await track_message(message.from_user.id, sent.message_id)
        return
    if await db.set_alert_active(alert_id, message.from_user.id, True):
        alert = await db.get_alert(alert_id, message.from_user.id)
        await seed_alert(db, kufar, alert, clear_first=True)
        await _show_alert_detail(message, alert, message.from_user.id)
    else:
        sent = await message.answer("Не удалось возобновить подписку.")
        await track_message(message.from_user.id, sent.message_id)


@router.message(Command("resync"))
async def cmd_resync(message: Message, db: Database, kufar: KufarClient) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        sent = await message.answer("Укажите ID или нажмите 🔄 в карточке подписки.")
        await track_message(message.from_user.id, sent.message_id)
        return
    alert_id = int(parts[1])
    alert = await db.get_alert(alert_id, message.from_user.id)
    if not alert:
        sent = await message.answer("Подписка не найдена.")
        await track_message(message.from_user.id, sent.message_id)
        return
    seeded = await seed_alert(db, kufar, alert, clear_first=True)
    if seeded >= 0:
        sent = await message.answer(f"🔄 Синхронизировано: {seeded} объявлений помечены как просмотренные.")
    else:
        sent = await message.answer("Не удалось синхронизировать. Проверьте фильтры.")
    await track_message(message.from_user.id, sent.message_id)


@router.message(Command("delete"))
async def cmd_delete(message: Message, db: Database) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        sent = await message.answer("Укажите ID или удалите через 📋 Мои подписки.")
        await track_message(message.from_user.id, sent.message_id)
        return
    alert_id = int(parts[1])
    if await db.delete_alert(alert_id, message.from_user.id):
        sent = await message.answer(f"🗑 Подписка {alert_id} удалена.")
    else:
        sent = await message.answer("Подписка не найдена.")
    await track_message(message.from_user.id, sent.message_id)
