from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

HOME_CB = "nav:home"


def home_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🏠 Главное меню", callback_data=HOME_CB)


def home_row() -> list[InlineKeyboardButton]:
    return [home_button()]


def extend_keyboard(
    keyboard: InlineKeyboardMarkup,
    extra_rows: list[list[InlineKeyboardButton]],
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=keyboard.inline_keyboard + extra_rows)


def wizard_nav_rows(state_data: dict, *, include_home: bool = True) -> list[list[InlineKeyboardButton]]:
    """Contextual back navigation for multi-step flows."""
    rows: list[list[InlineKeyboardButton]] = []

    if state_data.get("flow") == "edit" and state_data.get("edit_alert_id"):
        alert_id = state_data["edit_alert_id"]
        rows.append(
            [InlineKeyboardButton(text="◀️ К редактированию", callback_data=f"alert:edit:{alert_id}")]
        )
    elif state_data.get("return_to") == "confirm":
        rows.append(
            [InlineKeyboardButton(text="◀️ К предпросмотру", callback_data="new:edit:back")]
        )
    elif state_data.get("flow") == "new":
        rows.append(
            [InlineKeyboardButton(text="❌ Отменить создание", callback_data="new:cancel_confirm")]
        )

    if include_home:
        rows.append(home_row())
    return rows


def wizard_nav_keyboard(state_data: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=wizard_nav_rows(state_data))


def format_home_text(display_name: str, alerts_count: int, active_count: int) -> str:
    if alerts_count:
        status = f"\n\n📋 У вас <b>{alerts_count}</b> подписок ({active_count} активных)."
        hint = "Выберите действие в меню ниже."
    else:
        status = ""
        hint = "Нажмите <b>➕ Новая подписка</b>, чтобы начать."

    return (
        "👋 <b>Kufar Alerts</b>\n\n"
        f"Привет, <b>{display_name}</b>!\n"
        "Присылаю уведомления о новых объявлениях на Kufar."
        f"{status}\n\n{hint}"
    )
