from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.database import Alert, Database, format_alert_summary, parse_kufar_url
from bot.handlers.alerts import skip_keyboard
from bot.kufar import KufarClient, REGIONS, build_search_url
from bot.states import EditAlertStates

router = Router()

CLEAR_HINT = "\n\nОтправьте <code>-</code> чтобы убрать фильтр."


def alerts_list_keyboard(alerts: list[Alert]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"✏️ {a.name} (ID {a.id})", callback_data=f"edit:pick:{a.id}")]
        for a in alerts
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="edit:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_fields_keyboard(alert_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Название", callback_data=f"edit:field:{alert_id}:name")],
            [InlineKeyboardButton(text="🔎 Запрос", callback_data=f"edit:field:{alert_id}:query")],
            [InlineKeyboardButton(text="🔗 Ссылка Kufar", callback_data=f"edit:field:{alert_id}:url")],
            [InlineKeyboardButton(text="📂 Категория", callback_data=f"edit:field:{alert_id}:cat")],
            [InlineKeyboardButton(text="📍 Регион", callback_data=f"edit:field:{alert_id}:rgn")],
            [InlineKeyboardButton(text="💰 Цена", callback_data=f"edit:field:{alert_id}:price")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="edit:back")],
        ]
    )


async def _seed_alert(alert: Alert, kufar: KufarClient, db: Database) -> int:
    await db.clear_seen(alert.id)
    try:
        ads = await kufar.search(**alert.search_params)
        ad_ids = [int(ad["ad_id"]) for ad in ads if ad.get("ad_id")]
        await db.seed_seen(alert.id, ad_ids)
        return len(ad_ids)
    except Exception:
        return 0


async def _finish_edit(
    message: Message,
    state: FSMContext,
    db: Database,
    kufar: KufarClient,
    alert: Alert,
    *,
    reseed: bool = True,
) -> None:
    seeded = await _seed_alert(alert, kufar, db) if reseed else 0
    await state.clear()
    text = f"✅ Подписка обновлена!\n\n{format_alert_summary(alert)}"
    if reseed:
        text += f"\n\nЗагружено {seeded} объявлений — уведомления только о новых."
    await message.answer(text, parse_mode="HTML")


@router.message(Command("edit"))
async def cmd_edit(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    parts = (message.text or "").split()
    user_id = message.from_user.id

    if len(parts) >= 2 and parts[1].isdigit():
        alert_id = int(parts[1])
        alert = await db.get_alert(alert_id, user_id)
        if not alert:
            await message.answer("Подписка не найдена.")
            return
        await state.update_data(edit_alert_id=alert_id)
        await message.answer(
            f"Редактирование подписки:\n\n{format_alert_summary(alert)}\n\nЧто изменить?",
            parse_mode="HTML",
            reply_markup=edit_fields_keyboard(alert_id),
        )
        return

    alerts = await db.get_user_alerts(user_id)
    if not alerts:
        await message.answer("У вас нет подписок. Создайте: /new")
        return

    await message.answer(
        "Выберите подписку для редактирования:",
        reply_markup=alerts_list_keyboard(alerts),
    )


@router.callback_query(F.data == "edit:cancel")
async def edit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Редактирование отменено.")
    await callback.answer()


@router.callback_query(F.data == "edit:back")
async def edit_back(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    alerts = await db.get_user_alerts(callback.from_user.id)
    if not alerts:
        await callback.message.edit_text("У вас нет подписок.")
        await callback.answer()
        return
    await callback.message.edit_text(
        "Выберите подписку для редактирования:",
        reply_markup=alerts_list_keyboard(alerts),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit:pick:"))
async def edit_pick(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    alert_id = int(callback.data.split(":")[-1])
    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return

    await state.update_data(edit_alert_id=alert_id)
    await callback.message.edit_text(
        f"Редактирование подписки:\n\n{format_alert_summary(alert)}\n\nЧто изменить?",
        parse_mode="HTML",
        reply_markup=edit_fields_keyboard(alert_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit:field:"))
async def edit_field_pick(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
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
        current = alert.params.get("cat", "—")
        await callback.message.edit_text(
            f"Текущая категория: <code>{current}</code>\n\n"
            f"Введите ID категории (например 17010):{CLEAR_HINT}",
            parse_mode="HTML",
        )
        await state.set_state(EditAlertStates.waiting_category)
    elif field == "rgn":
        current = alert.params.get("rgn", "—")
        regions_text = "\n".join(f"{k} — {v}" for k, v in REGIONS.items())
        await callback.message.edit_text(
            f"Текущий регион: <code>{current}</code>\n\n"
            f"{regions_text}\n\nВведите ID региона:{CLEAR_HINT}",
            parse_mode="HTML",
        )
        await state.set_state(EditAlertStates.waiting_region)
    elif field == "price":
        current = alert.params.get("prc", "—")
        await callback.message.edit_text(
            f"Текущая цена: <code>{current}</code>\n\n"
            "Введите минимальную цену в BYN:",
            parse_mode="HTML",
            reply_markup=skip_keyboard(f"edit:skip_price_min:{alert_id}"),
        )
        await state.set_state(EditAlertStates.waiting_price_min)

    await callback.answer()


@router.message(EditAlertStates.waiting_name)
async def edit_name(message: Message, state: FSMContext, db: Database, kufar: KufarClient) -> None:
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым.")
        return

    alert = await db.update_alert(alert_id, message.from_user.id, name=name)
    if not alert:
        await message.answer("Подписка не найдена.")
        await state.clear()
        return

    await _finish_edit(message, state, db, kufar, alert, reseed=False)


@router.message(EditAlertStates.waiting_query)
async def edit_query(message: Message, state: FSMContext, db: Database, kufar: KufarClient) -> None:
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    text = (message.text or "").strip()
    query = "" if text == "-" else text

    alert = await db.update_alert(alert_id, message.from_user.id, query=query)
    if not alert:
        await message.answer("Подписка не найдена.")
        await state.clear()
        return

    await _finish_edit(message, state, db, kufar, alert)


@router.message(EditAlertStates.waiting_url)
async def edit_url(message: Message, state: FSMContext, db: Database, kufar: KufarClient) -> None:
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    try:
        query, params = parse_kufar_url(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    alert = await db.update_alert(alert_id, message.from_user.id, query=query, params=params)
    if not alert:
        await message.answer("Подписка не найдена.")
        await state.clear()
        return

    await _finish_edit(message, state, db, kufar, alert)


@router.message(EditAlertStates.waiting_category)
async def edit_category(message: Message, state: FSMContext, db: Database, kufar: KufarClient) -> None:
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    text = (message.text or "").strip()

    alert = await db.get_alert(alert_id, message.from_user.id)
    if not alert:
        await message.answer("Подписка не найдена.")
        await state.clear()
        return

    params = dict(alert.params)
    if text == "-":
        params.pop("cat", None)
    elif text.isdigit():
        params["cat"] = text
    else:
        await message.answer("Введите числовой ID или <code>-</code> для удаления.", parse_mode="HTML")
        return

    alert = await db.update_alert(alert_id, message.from_user.id, params=params)
    await _finish_edit(message, state, db, kufar, alert)


@router.message(EditAlertStates.waiting_region)
async def edit_region(message: Message, state: FSMContext, db: Database, kufar: KufarClient) -> None:
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    text = (message.text or "").strip()

    alert = await db.get_alert(alert_id, message.from_user.id)
    if not alert:
        await message.answer("Подписка не найдена.")
        await state.clear()
        return

    params = dict(alert.params)
    if text == "-":
        params.pop("rgn", None)
    elif text.isdigit():
        params["rgn"] = text
    else:
        await message.answer("Введите числовой ID или <code>-</code> для удаления.", parse_mode="HTML")
        return

    alert = await db.update_alert(alert_id, message.from_user.id, params=params)
    await _finish_edit(message, state, db, kufar, alert)


@router.callback_query(F.data.startswith("edit:skip_price_min:"))
async def edit_skip_price_min(callback: CallbackQuery, state: FSMContext) -> None:
    alert_id = int(callback.data.split(":")[-1])
    await state.update_data(edit_alert_id=alert_id, edit_params_patch={"_clear_price": True})
    await callback.message.edit_text(
        "Введите максимальную цену в BYN:",
        reply_markup=skip_keyboard(f"edit:skip_price_max:{alert_id}"),
    )
    await state.set_state(EditAlertStates.waiting_price_max)
    await callback.answer()


@router.message(EditAlertStates.waiting_price_min)
async def edit_price_min(message: Message, state: FSMContext, db: Database, kufar: KufarClient) -> None:
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    text = (message.text or "").strip()

    if text == "-":
        alert = await db.get_alert(alert_id, message.from_user.id)
        if not alert:
            await message.answer("Подписка не найдена.")
            await state.clear()
            return
        params = dict(alert.params)
        params.pop("prc", None)
        params.pop("_price_min", None)
        alert = await db.update_alert(alert_id, message.from_user.id, params=params)
        await _finish_edit(message, state, db, kufar, alert)
        return

    if not text.isdigit():
        await message.answer("Введите число (BYN) или <code>-</code> для удаления.", parse_mode="HTML")
        return

    await state.update_data(edit_params_patch={"_price_min": text})
    await message.answer(
        "Введите максимальную цену в BYN:",
        reply_markup=skip_keyboard(f"edit:skip_price_max:{alert_id}"),
    )
    await state.set_state(EditAlertStates.waiting_price_max)


@router.callback_query(F.data.startswith("edit:skip_price_max:"))
async def edit_skip_price_max(
    callback: CallbackQuery, state: FSMContext, db: Database, kufar: KufarClient
) -> None:
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    patch = data.get("edit_params_patch", {})

    alert = await db.get_alert(alert_id, callback.from_user.id)
    if not alert:
        await callback.answer("Подписка не найдена.", show_alert=True)
        await state.clear()
        return

    params = dict(alert.params)
    params.pop("_price_min", None)

    if patch.get("_clear_price"):
        params.pop("prc", None)
    elif "_price_min" in patch:
        params["prc"] = f"r:{patch['_price_min']},999999999"
    else:
        await callback.answer("Сначала укажите минимальную цену.", show_alert=True)
        return

    alert = await db.update_alert(alert_id, callback.from_user.id, params=params)
    await callback.message.edit_text("✅ Цена обновлена.")
    await _finish_edit(callback.message, state, db, kufar, alert)
    await callback.answer()


@router.message(EditAlertStates.waiting_price_max)
async def edit_price_max(message: Message, state: FSMContext, db: Database, kufar: KufarClient) -> None:
    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    patch = data.get("edit_params_patch", {})
    text = (message.text or "").strip()

    alert = await db.get_alert(alert_id, message.from_user.id)
    if not alert:
        await message.answer("Подписка не найдена.")
        await state.clear()
        return

    params = dict(alert.params)

    if text == "-":
        params.pop("prc", None)
    elif text.isdigit():
        price_min = patch.get("_price_min", "0")
        params["prc"] = f"r:{price_min},{text}"
    else:
        await message.answer("Введите число (BYN) или <code>-</code> для удаления.", parse_mode="HTML")
        return

    params.pop("_price_min", None)
    alert = await db.update_alert(alert_id, message.from_user.id, params=params)
    await _finish_edit(message, state, db, kufar, alert)
