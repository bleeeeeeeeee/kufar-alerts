from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CORE_PARAM_KEYS = frozenset({"cat", "rgn", "ar", "prc"})

TOGGLE_FILTERS: dict[str, dict[str, str]] = {
    "oph": {"label": "Только с фото", "icon": "📷"},
    "dle": {"label": "Куфар Доставка", "icon": "📦"},
    "pse": {"label": "Возможен обмен", "icon": "🔄"},
    "sde": {"label": "Безопасная сделка", "icon": "🛡"},
}

CHOICE_FILTERS: dict[str, dict[str, Any]] = {
    "cnd": {
        "label": "Состояние",
        "icon": "✨",
        "options": [("", "Любое"), ("1", "Б/у"), ("2", "Новое")],
    },
    "cmp": {
        "label": "Продавец",
        "icon": "👤",
        "options": [("", "Любой"), ("0", "Частник"), ("1", "Магазин")],
    },
}

EXTRA_FILTER_KEYS = frozenset(TOGGLE_FILTERS) | frozenset(CHOICE_FILTERS)


def is_extra_filter_key(key: str) -> bool:
    return key in EXTRA_FILTER_KEYS


def format_extra_filter_lines(params: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, meta in TOGGLE_FILTERS.items():
        if params.get(key) == "1":
            lines.append(f"{meta['icon']} {meta['label']}")
    for key, meta in CHOICE_FILTERS.items():
        value = params.get(key) or ""
        if not value:
            continue
        label = next((name for val, name in meta["options"] if val == value), value)
        lines.append(f"{meta['icon']} {meta['label']}: {label}")
    return lines


def _toggle_label(key: str, params: dict[str, Any]) -> str:
    meta = TOGGLE_FILTERS[key]
    on = params.get(key) == "1"
    mark = "✅" if on else "⬜️"
    return f"{mark} {meta['icon']} {meta['label']}"


def _choice_label(key: str, params: dict[str, Any]) -> str:
    meta = CHOICE_FILTERS[key]
    value = params.get(key) or ""
    label = next((name for val, name in meta["options"] if val == value), meta["options"][0][1])
    return f"{meta['icon']} {meta['label']}: {label}"


def extra_filters_keyboard(
    params: dict[str, Any],
    *,
    done_data: str = "xf:done",
    skip_data: str = "xf:skip",
    back_data: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for key in TOGGLE_FILTERS:
        rows.append([InlineKeyboardButton(text=_toggle_label(key, params), callback_data=f"xf:t:{key}")])

    for key in CHOICE_FILTERS:
        rows.append([InlineKeyboardButton(text=_choice_label(key, params), callback_data=f"xf:m:{key}")])

    nav = [
        InlineKeyboardButton(text="✅ Готово", callback_data=done_data),
        InlineKeyboardButton(text="⏭ Пропустить", callback_data=skip_data),
    ]
    rows.append(nav)
    if back_data:
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def choice_filter_keyboard(
    filter_key: str,
    params: dict[str, Any],
    *,
    back_data: str = "xf:back",
) -> InlineKeyboardMarkup:
    meta = CHOICE_FILTERS[filter_key]
    current = params.get(filter_key) or ""
    rows: list[list[InlineKeyboardButton]] = []
    for value, label in meta["options"]:
        mark = "✓ " if value == current else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{label}",
                    callback_data=f"xf:c:{filter_key}:{value or '_'}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def extra_filters_summary(params: dict[str, Any]) -> str:
    lines = format_extra_filter_lines(params)
    if not lines:
        return "Дополнительные фильтры не выбраны."
    return "\n".join(lines)
