from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.database import Database, format_alert_summary, parse_kufar_url
from bot.kufar import KufarClient, REGIONS, build_search_url
from bot.states import NewAlertStates

router = Router()


def method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Вставить ссылку с Kufar", callback_data="new:url")],
            [InlineKeyboardButton(text="✏️ Настроить вручную", callback_data="new:manual")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="new:cancel")],
        ]
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать подписку", callback_data="new:confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="new:cancel")],
        ]
    )


def skip_keyboard(callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data=callback)]]
    )


async def _show_draft(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    query = data.get("query", "")
    params = data.get("params", {})
    name = data.get("name") or query or "Подписка"

    summary_parts = [f"<b>Предпросмотр подписки</b>", f"Название: {name}"]
    if query:
        summary_parts.append(f"Запрос: <code>{query}</code>")
    if params.get("cat"):
        summary_parts.append(f"Категория ID: {params['cat']}")
    if params.get("rgn"):
        region_name = REGIONS.get(int(params["rgn"]), params["rgn"])
        summary_parts.append(f"Регион: {region_name}")
    if params.get("prc"):
        summary_parts.append(f"Цена: {params['prc']}")

    url = build_search_url(query, **params)
    summary_parts.append(f'\n🔗 <a href="{url}">Открыть поиск</a>')

    await message.answer(
        "\n".join(summary_parts),
        parse_mode="HTML",
        reply_markup=confirm_keyboard(),
        disable_web_page_preview=True,
    )
    await state.set_state(NewAlertStates.confirm)


@router.message(Command("new"))
async def cmd_new(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Как создать подписку?",
        reply_markup=method_keyboard(),
    )
    await state.set_state(NewAlertStates.waiting_method)


@router.callback_query(F.data == "new:cancel")
async def cancel_new(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Создание подписки отменено.")
    await callback.answer()


@router.callback_query(F.data == "new:url", NewAlertStates.waiting_method)
async def new_via_url(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Отправьте ссылку на страницу поиска с kufar.by\n"
        "Например: https://www.kufar.by/l?query=iphone&cat=17010"
    )
    await state.set_state(NewAlertStates.waiting_url)
    await callback.answer()


@router.callback_query(F.data == "new:manual", NewAlertStates.waiting_method)
async def new_manual(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(query="", params={})
    await callback.message.edit_text(
        "Введите поисковый запрос (слова в названии).\n"
        "Или нажмите «Пропустить», если нужны только фильтры.",
        reply_markup=skip_keyboard("new:skip_query"),
    )
    await state.set_state(NewAlertStates.waiting_query)
    await callback.answer()


@router.message(NewAlertStates.waiting_url)
async def process_url(message: Message, state: FSMContext) -> None:
    try:
        query, params = parse_kufar_url(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    name = query or params.get("cat") or "Подписка"
    await state.update_data(query=query, params=params, name=str(name))
    await _show_draft(message, state)


@router.callback_query(F.data == "new:skip_query", NewAlertStates.waiting_query)
async def skip_query(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Введите ID категории (например 17010 — телефоны).\n"
        "ID можно взять из URL на kufar.by (параметр cat).",
        reply_markup=skip_keyboard("new:skip_cat"),
    )
    await state.set_state(NewAlertStates.waiting_category)
    await callback.answer()


@router.message(NewAlertStates.waiting_query)
async def process_query(message: Message, state: FSMContext) -> None:
    query = (message.text or "").strip()
    await state.update_data(query=query)
    await message.answer(
        "Введите ID категории (например 17010) или пропустите.",
        reply_markup=skip_keyboard("new:skip_cat"),
    )
    await state.set_state(NewAlertStates.waiting_category)


@router.callback_query(F.data == "new:skip_cat", NewAlertStates.waiting_category)
async def skip_cat(callback: CallbackQuery, state: FSMContext) -> None:
    regions_text = "\n".join(f"{k} — {v}" for k, v in REGIONS.items())
    await callback.message.edit_text(
        f"Введите ID региона или пропустите:\n\n{regions_text}",
        reply_markup=skip_keyboard("new:skip_region"),
    )
    await state.set_state(NewAlertStates.waiting_region)
    await callback.answer()


@router.message(NewAlertStates.waiting_category)
async def process_category(message: Message, state: FSMContext) -> None:
    cat = (message.text or "").strip()
    if not cat.isdigit():
        await message.answer("Введите числовой ID категории или пропустите.")
        return

    data = await state.get_data()
    params = data.get("params", {})
    params["cat"] = cat
    await state.update_data(params=params)

    regions_text = "\n".join(f"{k} — {v}" for k, v in REGIONS.items())
    await message.answer(
        f"Введите ID региона или пропустите:\n\n{regions_text}",
        reply_markup=skip_keyboard("new:skip_region"),
    )
    await state.set_state(NewAlertStates.waiting_region)


@router.callback_query(F.data == "new:skip_region", NewAlertStates.waiting_region)
async def skip_region(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Введите минимальную цену в BYN или пропустите.",
        reply_markup=skip_keyboard("new:skip_price_min"),
    )
    await state.set_state(NewAlertStates.waiting_price_min)
    await callback.answer()


@router.message(NewAlertStates.waiting_region)
async def process_region(message: Message, state: FSMContext) -> None:
    region = (message.text or "").strip()
    if not region.isdigit():
        await message.answer("Введите числовой ID региона или пропустите.")
        return

    data = await state.get_data()
    params = data.get("params", {})
    params["rgn"] = region
    await state.update_data(params=params)

    await message.answer(
        "Введите минимальную цену в BYN или пропустите.",
        reply_markup=skip_keyboard("new:skip_price_min"),
    )
    await state.set_state(NewAlertStates.waiting_price_min)


@router.callback_query(F.data == "new:skip_price_min", NewAlertStates.waiting_price_min)
async def skip_price_min(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Введите максимальную цену в BYN или пропустите.",
        reply_markup=skip_keyboard("new:skip_price_max"),
    )
    await state.set_state(NewAlertStates.waiting_price_max)
    await callback.answer()


@router.message(NewAlertStates.waiting_price_min)
async def process_price_min(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите число (BYN) или пропустите.")
        return

    data = await state.get_data()
    params = data.get("params", {})
    params["_price_min"] = text
    await state.update_data(params=params)

    await message.answer(
        "Введите максимальную цену в BYN или пропустите.",
        reply_markup=skip_keyboard("new:skip_price_max"),
    )
    await state.set_state(NewAlertStates.waiting_price_max)


@router.callback_query(F.data == "new:skip_price_max", NewAlertStates.waiting_price_max)
async def skip_price_max(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    params = data.get("params", {})
    price_min = params.pop("_price_min", None)
    if price_min is not None:
        params["prc"] = f"r:{price_min},999999999"
        await state.update_data(params=params)

    await callback.message.edit_text("Введите название подписки (для удобства):")
    await state.set_state(NewAlertStates.waiting_name)
    await callback.answer()


@router.message(NewAlertStates.waiting_price_max)
async def process_price_max(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите число (BYN) или пропустите.")
        return

    data = await state.get_data()
    params = data.get("params", {})
    price_min = params.pop("_price_min", "0")
    params["prc"] = f"r:{price_min},{text}"
    await state.update_data(params=params)

    await message.answer("Введите название подписки (для удобства):")
    await state.set_state(NewAlertStates.waiting_name)


@router.message(NewAlertStates.waiting_name)
async def process_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip() or "Подписка"
    await state.update_data(name=name)
    await _show_draft(message, state)


@router.callback_query(F.data == "new:confirm", NewAlertStates.confirm)
async def confirm_new(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    kufar: KufarClient,
) -> None:
    data = await state.get_data()
    query = data.get("query", "")
    params = data.get("params", {})
    name = data.get("name") or query or "Подписка"

    alert = await db.create_alert(
        user_id=callback.from_user.id,
        name=name,
        query=query,
        params=params,
    )

    # Seed with current results so we don't spam old ads
    try:
        ads = await kufar.search(**alert.search_params)
        ad_ids = [int(ad["ad_id"]) for ad in ads if ad.get("ad_id")]
        await db.seed_seen(alert.id, ad_ids)
        seeded = len(ad_ids)
    except Exception:
        seeded = 0

    await state.clear()
    await callback.message.edit_text(
        f"✅ Подписка создана!\n\n{format_alert_summary(alert)}\n\n"
        f"Загружено {seeded} текущих объявлений — уведомления только о новых.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(Command("list"))
async def cmd_list(message: Message, db: Database) -> None:
    alerts = await db.get_user_alerts(message.from_user.id)
    if not alerts:
        await message.answer("У вас нет подписок. Создайте: /new")
        return

    text = "<b>Ваши подписки:</b>\n\n" + "\n\n".join(
        format_alert_summary(alert) for alert in alerts
    )
    text += "\n\n✏️ Редактировать: /edit"
    await message.answer(text, parse_mode="HTML")


@router.message(Command("pause"))
async def cmd_pause(message: Message, db: Database) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /pause ID")
        return

    alert_id = int(parts[1])
    if await db.set_alert_active(alert_id, message.from_user.id, False):
        await message.answer(f"⏸ Подписка {alert_id} на паузе.")
    else:
        await message.answer("Подписка не найдена.")


@router.message(Command("resume"))
async def cmd_resume(message: Message, db: Database, kufar: KufarClient) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /resume ID")
        return

    alert_id = int(parts[1])
    alert = await db.get_alert(alert_id, message.from_user.id)
    if not alert:
        await message.answer("Подписка не найдена.")
        return

    if await db.set_alert_active(alert_id, message.from_user.id, True):
        try:
            ads = await kufar.search(**alert.search_params)
            ad_ids = [int(ad["ad_id"]) for ad in ads if ad.get("ad_id")]
            await db.seed_seen(alert.id, ad_ids)
        except Exception:
            pass
        await message.answer(f"✅ Подписка {alert_id} возобновлена.")
    else:
        await message.answer("Не удалось возобновить подписку.")


@router.message(Command("delete"))
async def cmd_delete(message: Message, db: Database) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /delete ID")
        return

    alert_id = int(parts[1])
    if await db.delete_alert(alert_id, message.from_user.id):
        await message.answer(f"🗑 Подписка {alert_id} удалена.")
    else:
        await message.answer("Подписка не найдена.")
