from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.database import Database, format_alert_summary, parse_kufar_url
from bot.keyboards import MAIN_MENU, MAIN_MENU_BUTTONS, skip_keyboard
from bot.kufar import KufarClient, REGIONS, build_search_url
from bot.price import PRICE_INPUT_HINT, format_price_display, parse_price_input
from bot.states import NewAlertStates
from bot.utils.chat import WizardCleaner, track_message

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


async def _show_draft(message: Message, state: FSMContext, cleaner: WizardCleaner) -> None:
    data = await state.get_data()
    query = data.get("query", "")
    params = data.get("params", {})
    name = data.get("name") or query or "Подписка"

    summary_parts = [f"<b>Предпросмотр подписки</b>", f"Название: {name}"]
    if query:
        summary_parts.append(f"Запрос: <code>{query}</code>")
    if params.get("cat"):
        summary_parts.append(f"📂 Категория: {params['cat']}")
    if params.get("rgn"):
        region_name = REGIONS.get(int(params["rgn"]), params["rgn"])
        summary_parts.append(f"📍 Регион: {region_name}")
    if params.get("prc"):
        summary_parts.append(f"💰 Цена: {format_price_display(params['prc'])}")

    url = build_search_url(query, **{k: v for k, v in params.items() if not k.startswith("_")})
    summary_parts.append(f'\n🔗 <a href="{url}">Открыть поиск</a>')

    await cleaner.send(
        message,
        "\n".join(summary_parts),
        parse_mode="HTML",
        reply_markup=confirm_keyboard(),
        disable_web_page_preview=True,
        delete_user=True,
    )
    await state.set_state(NewAlertStates.confirm)


@router.message(Command("new"))
@router.message(F.text == MAIN_MENU_BUTTONS["new"])
async def cmd_new(message: Message, state: FSMContext) -> None:
    await state.clear()
    cleaner = WizardCleaner(state)
    await cleaner.send(
        message,
        "Как создать подписку?",
        reply_markup=method_keyboard(),
    )
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
    cleaner = WizardCleaner(state)
    try:
        query, params = parse_kufar_url(message.text or "")
    except ValueError as exc:
        await cleaner.send(message, str(exc), delete_user=True)
        return

    name = query or params.get("cat") or "Подписка"
    await state.update_data(query=query, params=params, name=str(name))
    await _show_draft(message, state, cleaner)


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
    cleaner = WizardCleaner(state)
    query = (message.text or "").strip()
    await state.update_data(query=query)
    await cleaner.send(
        message,
        "Введите ID категории (например 17010) или пропустите.",
        reply_markup=skip_keyboard("new:skip_cat"),
        delete_user=True,
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
    cleaner = WizardCleaner(state)
    cat = (message.text or "").strip()
    if not cat.isdigit():
        await cleaner.send(message, "Введите числовой ID категории или пропустите.", delete_user=True)
        return

    data = await state.get_data()
    params = data.get("params", {})
    params["cat"] = cat
    await state.update_data(params=params)

    regions_text = "\n".join(f"{k} — {v}" for k, v in REGIONS.items())
    await cleaner.send(
        message,
        f"Введите ID региона или пропустите:\n\n{regions_text}",
        reply_markup=skip_keyboard("new:skip_region"),
        delete_user=True,
    )
    await state.set_state(NewAlertStates.waiting_region)


@router.callback_query(F.data == "new:skip_region", NewAlertStates.waiting_region)
async def skip_region(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        PRICE_INPUT_HINT,
        parse_mode="HTML",
        reply_markup=skip_keyboard("new:skip_price"),
    )
    await state.set_state(NewAlertStates.waiting_price)
    await callback.answer()


@router.message(NewAlertStates.waiting_region)
async def process_region(message: Message, state: FSMContext) -> None:
    cleaner = WizardCleaner(state)
    region = (message.text or "").strip()
    if not region.isdigit():
        await cleaner.send(message, "Введите числовой ID региона или пропустите.", delete_user=True)
        return

    data = await state.get_data()
    params = data.get("params", {})
    params["rgn"] = region
    await state.update_data(params=params)

    await cleaner.send(
        message,
        PRICE_INPUT_HINT,
        parse_mode="HTML",
        reply_markup=skip_keyboard("new:skip_price"),
        delete_user=True,
    )
    await state.set_state(NewAlertStates.waiting_price)


@router.callback_query(F.data == "new:skip_price", NewAlertStates.waiting_price)
async def skip_price(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("Введите название подписки (для удобства):")
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

    await cleaner.send(message, "Введите название подписки (для удобства):", delete_user=True)
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

    try:
        ads = await kufar.search(**alert.search_params)
        ad_ids = [int(ad["ad_id"]) for ad in ads if ad.get("ad_id")]
        await db.seed_seen(alert.id, ad_ids)
        seeded = len(ad_ids)
    except Exception:
        seeded = 0

    await cleaner.cleanup_wizard(callback.message.bot, callback.message.chat.id)
    await state.clear()

    try:
        await callback.message.delete()
    except Exception:
        pass

    sent = await callback.message.answer(
        f"✅ Подписка создана!\n\n{format_alert_summary(alert)}\n\n"
        f"Загружено {seeded} текущих объявлений — уведомления только о новых.",
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
    )
    await track_message(callback.from_user.id, sent.message_id)
    await callback.answer()


@router.message(Command("list"))
@router.message(F.text == MAIN_MENU_BUTTONS["list"])
async def cmd_list(message: Message, db: Database) -> None:
    alerts = await db.get_user_alerts(message.from_user.id)
    if not alerts:
        sent = await message.answer("У вас нет подписок. Создайте: ➕ Новая подписка")
        await track_message(message.from_user.id, sent.message_id)
        return

    text = "<b>Ваши подписки:</b>\n\n" + "\n\n".join(
        format_alert_summary(alert) for alert in alerts
    )
    sent = await message.answer(text, parse_mode="HTML")
    await track_message(message.from_user.id, sent.message_id)


@router.message(Command("pause"))
async def cmd_pause(message: Message, db: Database) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        sent = await message.answer("Использование: /pause ID")
        await track_message(message.from_user.id, sent.message_id)
        return

    alert_id = int(parts[1])
    if await db.set_alert_active(alert_id, message.from_user.id, False):
        sent = await message.answer(f"⏸ Подписка {alert_id} на паузе.")
    else:
        sent = await message.answer("Подписка не найдена.")
    await track_message(message.from_user.id, sent.message_id)


@router.message(Command("resume"))
async def cmd_resume(message: Message, db: Database, kufar: KufarClient) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        sent = await message.answer("Использование: /resume ID")
        await track_message(message.from_user.id, sent.message_id)
        return

    alert_id = int(parts[1])
    alert = await db.get_alert(alert_id, message.from_user.id)
    if not alert:
        sent = await message.answer("Подписка не найдена.")
        await track_message(message.from_user.id, sent.message_id)
        return

    if await db.set_alert_active(alert_id, message.from_user.id, True):
        try:
            ads = await kufar.search(**alert.search_params)
            ad_ids = [int(ad["ad_id"]) for ad in ads if ad.get("ad_id")]
            await db.seed_seen(alert.id, ad_ids)
        except Exception:
            pass
        sent = await message.answer(f"✅ Подписка {alert_id} возобновлена.")
    else:
        sent = await message.answer("Не удалось возобновить подписку.")
    await track_message(message.from_user.id, sent.message_id)


@router.message(Command("delete"))
async def cmd_delete(message: Message, db: Database) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        sent = await message.answer("Использование: /delete ID")
        await track_message(message.from_user.id, sent.message_id)
        return

    alert_id = int(parts[1])
    if await db.delete_alert(alert_id, message.from_user.id):
        sent = await message.answer(f"🗑 Подписка {alert_id} удалена.")
    else:
        sent = await message.answer("Подписка не найдена.")
    await track_message(message.from_user.id, sent.message_id)
