from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.database import Database
from bot.keyboards import skip_keyboard, step_nav_keyboard
from bot.kufar import KufarClient
from bot.navigation import extend_keyboard, wizard_nav_rows
from bot.users import User
from bot.utils.chat import save_panel, track_message
from bot.pickers import (
    area_keyboard,
    area_title,
    category_keyboard,
    category_title,
    region_keyboard,
)
from bot.search_filters import (
    CHOICE_FILTERS,
    TOGGLE_FILTERS,
    choice_filter_keyboard,
    extra_filters_keyboard,
    extra_filters_summary,
)
from bot.price import PRICE_INPUT_HINT
from bot.states import NewAlertStates

router = Router()


async def _keyboard_with_nav(keyboard, state: FSMContext):
    data = await state.get_data()
    return extend_keyboard(keyboard, wizard_nav_rows(data))


async def _track_wizard_message(
    message: Message,
    user: User | None,
    db: Database | None,
) -> None:
    await track_message(message.from_user.id, message.message_id)
    if db is not None:
        await save_panel(db, message.from_user.id, message.message_id, user)


async def _send_or_edit_wizard_message(
    target: Message | CallbackQuery,
    text: str,
    reply_markup,
    state: FSMContext,
    user: User | None = None,
    db: Database | None = None,
    **kwargs,
) -> None:
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=reply_markup, **kwargs)
    else:
        sent = await target.answer(text, reply_markup=reply_markup, **kwargs)
        await _track_wizard_message(sent, user, db)


async def show_category_picker(
    target: Message | CallbackQuery,
    state: FSMContext,
    kufar: KufarClient,
    parent_id: int | None = None,
    *,
    user: User | None = None,
    db: Database | None = None,
) -> None:
    data = await state.get_data()
    step = ""
    if data.get("flow") == "new" and parent_id is None and data.get("return_to") != "confirm":
        step = "<b>Шаг 2/6 — Категория</b>\n\n"
    text = step + category_title(kufar, parent_id)
    kb = await _keyboard_with_nav(category_keyboard(kufar, parent_id), state)
    await _send_or_edit_wizard_message(target, text, kb, state, user=user, db=db)
    if data.get("flow") == "new" and data.get("return_to") != "confirm":
        await state.set_state(NewAlertStates.picking_category)


async def show_region_picker(
    target: Message | CallbackQuery,
    state: FSMContext,
    *,
    user: User | None = None,
    db: Database | None = None,
) -> None:
    text = "<b>Шаг 3/6 — Место</b>\n\n📍 Выберите регион или «Вся Беларусь»"
    kb = await _keyboard_with_nav(region_keyboard(), state)
    await _send_or_edit_wizard_message(target, text, kb, state, user=user, db=db)
    data = await state.get_data()
    if data.get("flow") == "new" and data.get("return_to") != "confirm":
        await state.set_state(NewAlertStates.picking_region)


async def show_area_picker(callback: CallbackQuery, region_id: int, state: FSMContext, page: int = 0) -> None:
    await callback.message.edit_text(
        area_title(region_id, page),
        reply_markup=await _keyboard_with_nav(area_keyboard(region_id, page), state),
    )


async def _finish_edit_location(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    kufar: KufarClient,
    params: dict,
) -> None:
    from bot.handlers.edit import _finish_edit

    data = await state.get_data()
    alert_id = data.get("edit_alert_id")
    alert = await db.update_alert(alert_id, callback.from_user.id, params=params)
    if not alert:
        await callback.answer("Подписка не найдена.", show_alert=True)
        await state.clear()
        return
    await callback.message.delete()
    await _finish_edit(callback.message, state, db, kufar, alert)


async def show_extra_filters_picker(
    target: Message | CallbackQuery,
    state: FSMContext,
    *,
    user: User | None = None,
    db: Database | None = None,
) -> None:
    data = await state.get_data()
    params = dict(data.get("params", {}))
    step = ""
    if data.get("flow") == "new" and data.get("return_to") != "confirm":
        step = "<b>Шаг 5/6 — Доп. фильтры</b>\n\n"
    text = (
        f"{step}Уточните поиск. Можно выбрать несколько опций:\n\n"
        f"{extra_filters_summary(params)}"
    )
    kb = await _keyboard_with_nav(extra_filters_keyboard(params), state)
    await _send_or_edit_wizard_message(
        target,
        text,
        kb,
        state,
        user=user,
        db=db,
        parse_mode="HTML",
    )
    if data.get("flow") == "new" and data.get("return_to") != "confirm":
        await state.set_state(NewAlertStates.picking_extra)


async def _go_new_price(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewAlertStates.waiting_price)
    data = await state.get_data()
    await callback.message.edit_text(
        "<b>Шаг 4/6 — Цена</b>\n\n" + PRICE_INPUT_HINT,
        parse_mode="HTML",
        reply_markup=step_nav_keyboard(
            "new:skip_price",
            extra_rows=wizard_nav_rows(data, include_home=False),
        ),
    )


async def _go_new_name(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewAlertStates.waiting_name)
    data = await state.get_data()
    from bot.navigation import wizard_nav_keyboard

    await callback.message.edit_text(
        "<b>Шаг 6/6 — Название</b>\n\nКак назвать подписку? (для удобства в списке)",
        parse_mode="HTML",
        reply_markup=wizard_nav_keyboard(data),
    )


async def _return_to_draft_if_needed(
    callback: CallbackQuery,
    state: FSMContext,
    user,
    db: Database,
) -> bool:
    data = await state.get_data()
    if data.get("return_to") != "confirm":
        return False
    from bot.handlers.alerts import _show_draft_callback
    from bot.utils.chat import WizardCleaner

    cleaner = WizardCleaner(state, user, db)
    await _show_draft_callback(callback, state, cleaner)
    return True


@router.callback_query(F.data.startswith("pick:ca:"))
async def pick_category(
    callback: CallbackQuery,
    state: FSMContext,
    kufar: KufarClient,
    db: Database,
    user=None,
) -> None:
    action = callback.data.split(":", 2)[2]
    data = await state.get_data()
    flow = data.get("flow", "new")
    params = dict(data.get("params", {}))

    if action == "sk":
        params.pop("cat", None)
        await state.update_data(params=params)
        if flow == "edit":
            alert = await db.update_alert(data["edit_alert_id"], callback.from_user.id, params=params)
            from bot.handlers.edit import _finish_edit
            await callback.message.delete()
            await _finish_edit(callback.message, state, db, kufar, alert)
        elif await _return_to_draft_if_needed(callback, state, user, db):
            pass
        else:
            await show_region_picker(callback, state)
        await callback.answer()
        return

    if action.startswith("n:"):
        raw = action[2:]
        parent_id = None if raw == "root" else int(raw)
        await show_category_picker(callback, state, kufar, parent_id)
        await callback.answer()
        return

    if action.startswith("s:"):
        cat_id = int(action[2:])
        params["cat"] = str(cat_id)
        await state.update_data(params=params)

        if flow == "edit":
            alert = await db.update_alert(data["edit_alert_id"], callback.from_user.id, params=params)
            from bot.handlers.edit import _finish_edit
            await callback.message.delete()
            await _finish_edit(callback.message, state, db, kufar, alert)
        elif await _return_to_draft_if_needed(callback, state, user, db):
            pass
        else:
            await show_region_picker(callback, state)
        await callback.answer()
        return

    await callback.answer()


@router.callback_query(F.data.startswith("pick:lo:"))
async def pick_location(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    kufar: KufarClient,
    user=None,
) -> None:
    parts = callback.data.split(":")
    action = parts[2]
    data = await state.get_data()
    flow = data.get("flow", "new")
    params = dict(data.get("params", {}))

    if action == "sk":
        params.pop("rgn", None)
        params.pop("ar", None)
        await state.update_data(params=params)
        if flow == "edit":
            alert = await db.update_alert(data["edit_alert_id"], callback.from_user.id, params=params)
            from bot.handlers.edit import _finish_edit
            await callback.message.delete()
            await _finish_edit(callback.message, state, db, kufar, alert)
        elif await _return_to_draft_if_needed(callback, state, user, db):
            pass
        else:
            await _go_new_price(callback, state)
        await callback.answer()
        return

    if action == "b":
        await show_region_picker(callback, state)
        await callback.answer()
        return

    if action == "r":
        region_id = int(parts[3])
        await state.update_data(pick_rgn=region_id)
        await show_area_picker(callback, region_id, state, 0)
        await callback.answer()
        return

    if action == "p":
        region_id = int(parts[3])
        page = int(parts[4])
        await show_area_picker(callback, region_id, state, page)
        await callback.answer()
        return

    if action == "w":
        region_id = data.get("pick_rgn")
        if region_id is None:
            await callback.answer("Сначала выберите регион.", show_alert=True)
            return
        params["rgn"] = str(region_id)
        params.pop("ar", None)
        await state.update_data(params=params)
        if flow == "edit":
            await _finish_edit_location(callback, state, db, kufar, params)
        elif await _return_to_draft_if_needed(callback, state, user, db):
            pass
        else:
            await _go_new_price(callback, state)
        await callback.answer()
        return

    if action == "a":
        region_id = data.get("pick_rgn")
        area_id = int(parts[3])
        if region_id is None:
            await callback.answer("Сначала выберите регион.", show_alert=True)
            return
        params["rgn"] = str(region_id)
        params["ar"] = str(area_id)
        await state.update_data(params=params)
        if flow == "edit":
            await _finish_edit_location(callback, state, db, kufar, params)
        elif await _return_to_draft_if_needed(callback, state, user, db):
            pass
        else:
            await _go_new_price(callback, state)
        await callback.answer()
        return

    await callback.answer()


async def _finish_extra_filters(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    kufar: KufarClient,
    params: dict,
    user=None,
) -> None:
    data = await state.get_data()
    flow = data.get("flow", "new")
    await state.update_data(params=params)

    if flow == "edit":
        alert_id = data.get("edit_alert_id")
        alert = await db.update_alert(alert_id, callback.from_user.id, params=params)
        if not alert:
            await callback.answer("Подписка не найдена.", show_alert=True)
            await state.clear()
            return
        from bot.handlers.edit import _finish_edit

        await callback.message.delete()
        await _finish_edit(callback.message, state, db, kufar, alert)
        return

    if await _return_to_draft_if_needed(callback, state, user, db):
        return

    await _go_new_name(callback, state)


@router.callback_query(F.data.startswith("xf:"))
async def pick_extra_filters(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    kufar: KufarClient,
    user=None,
) -> None:
    parts = callback.data.split(":")
    action = parts[1]
    data = await state.get_data()
    params = dict(data.get("params", {}))

    if action in {"done", "skip"}:
        # If user chose to skip, remove any extra-filter keys from params.
        if action == "skip":
            from bot.search_filters import is_extra_filter_key

            params = {k: v for k, v in params.items() if not is_extra_filter_key(k)}
        await _finish_extra_filters(callback, state, db, kufar, params, user)
        await callback.answer()
        return

    if action == "back":
        await show_extra_filters_picker(callback, state)
        await callback.answer()
        return

    if action == "t" and len(parts) >= 3:
        key = parts[2]
        if key in TOGGLE_FILTERS:
            if params.get(key) == "1":
                params.pop(key, None)
            else:
                params[key] = "1"
            await state.update_data(params=params)
            await show_extra_filters_picker(callback, state)
        await callback.answer()
        return

    if action == "m" and len(parts) >= 3:
        key = parts[2]
        if key in CHOICE_FILTERS:
            data = await state.get_data()
            await callback.message.edit_text(
                f"<b>{CHOICE_FILTERS[key]['label']}</b>\n\nВыберите значение:",
                parse_mode="HTML",
                reply_markup=await _keyboard_with_nav(choice_filter_keyboard(key, params), state),
            )
        await callback.answer()
        return

    if action == "c" and len(parts) >= 4:
        key = parts[2]
        value = parts[3]
        if key in CHOICE_FILTERS:
            if value == "_":
                params.pop(key, None)
            else:
                params[key] = value
            await state.update_data(params=params)
            await show_extra_filters_picker(callback, state)
        await callback.answer()
        return

    await callback.answer()
