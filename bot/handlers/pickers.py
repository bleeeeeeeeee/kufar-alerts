from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.database import Database
from bot.keyboards import skip_keyboard
from bot.kufar import KufarClient
from bot.pickers import (
    area_keyboard,
    area_title,
    category_keyboard,
    category_title,
    region_keyboard,
)
from bot.price import PRICE_INPUT_HINT
from bot.states import NewAlertStates

router = Router()


async def show_category_picker(target: Message | CallbackQuery, state: FSMContext, kufar: KufarClient, parent_id: int | None = None) -> None:
    data = await state.get_data()
    step = ""
    if data.get("flow") == "new" and parent_id is None:
        step = "<b>Шаг 2/5 — Категория</b>\n\n"
    text = step + category_title(kufar, parent_id)
    kb = category_keyboard(kufar, parent_id)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


async def show_region_picker(target: Message | CallbackQuery) -> None:
    text = "<b>Шаг 3/5 — Место</b>\n\n📍 Выберите регион"
    kb = region_keyboard()
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


async def show_area_picker(callback: CallbackQuery, region_id: int, page: int = 0) -> None:
    await callback.message.edit_text(
        area_title(region_id, page),
        reply_markup=area_keyboard(region_id, page),
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


async def _go_new_price(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewAlertStates.waiting_price)
    await callback.message.edit_text(
        "<b>Шаг 4/5 — Цена</b>\n\n" + PRICE_INPUT_HINT,
        parse_mode="HTML",
        reply_markup=skip_keyboard("new:skip_price"),
    )


@router.callback_query(F.data.startswith("pick:ca:"))
async def pick_category(callback: CallbackQuery, state: FSMContext, kufar: KufarClient, db: Database) -> None:
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
        else:
            await show_region_picker(callback)
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
        else:
            await show_region_picker(callback)
        await callback.answer()
        return

    await callback.answer()


@router.callback_query(F.data.startswith("pick:lo:"))
async def pick_location(callback: CallbackQuery, state: FSMContext, db: Database, kufar: KufarClient) -> None:
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
        else:
            await _go_new_price(callback, state)
        await callback.answer()
        return

    if action == "b":
        await show_region_picker(callback)
        await callback.answer()
        return

    if action == "r":
        region_id = int(parts[3])
        await state.update_data(pick_rgn=region_id)
        await show_area_picker(callback, region_id, 0)
        await callback.answer()
        return

    if action == "p":
        region_id = int(parts[3])
        page = int(parts[4])
        await show_area_picker(callback, region_id, page)
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
        else:
            await _go_new_price(callback, state)
        await callback.answer()
        return

    await callback.answer()
