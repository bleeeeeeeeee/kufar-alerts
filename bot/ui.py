from __future__ import annotations

import html
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.catalog import category_name
from bot.database import Alert
from bot.kufar import build_search_url
from bot.locations import format_location


def format_filters(query: str, params: dict[str, Any]) -> list[str]:
    """Human-readable filter lines for any subscription."""
    lines: list[str] = []
    if query:
        lines.append(f"🔎 <code>{html.escape(query)}</code>")
    else:
        lines.append("🔎 <i>без текстового запроса</i>")

    cat = params.get("cat")
    if cat:
        lines.append(f"📂 {html.escape(category_name(cat))}")
    else:
        lines.append("📂 <i>все категории</i>")

    location = format_location(params)
    if location:
        lines.append(f"📍 {html.escape(location)}")
    else:
        lines.append("📍 <i>вся Беларусь</i>")

    prc = params.get("prc")
    if prc:
        from bot.price import format_price_display

        lines.append(f"💰 {html.escape(format_price_display(prc))}")
    else:
        lines.append("💰 <i>любая цена</i>")

    return lines


def format_alert_card(alert: Alert, *, compact: bool = False) -> str:
    status = "✅ Активна" if alert.active else "⏸ На паузе"
    title = html.escape(alert.name)

    if compact:
        icon = "🟢" if alert.active else "⚪️"
        return f"{icon} <b>{title}</b> · ID {alert.id}"

    filters = format_filters(alert.query, alert.params)
    search_params = {k: v for k, v in alert.params.items() if not str(k).startswith("_")}
    url = build_search_url(alert.query, **search_params)

    lines = [
        f"━━━━━━━━━━━━━━",
        f"📌 <b>{title}</b>",
        f"━━━━━━━━━━━━━━",
        "",
        *filters,
        "",
        f"Статус: {status}",
        f"ID: {alert.id}",
        f'🔗 <a href="{url}">Открыть поиск на Kufar</a>',
    ]
    return "\n".join(lines)


def format_draft_preview(name: str, query: str, params: dict[str, Any]) -> str:
    filters = format_filters(query, params)
    search_params = {k: v for k, v in params.items() if not str(k).startswith("_")}
    url = build_search_url(query, **search_params)

    lines = [
        "<b>📋 Предпросмотр подписки</b>",
        "",
        f"📝 Название: <b>{html.escape(name)}</b>",
        "",
        *filters,
        "",
        f'🔗 <a href="{url}">Проверить на Kufar</a>',
        "",
        "Всё верно? Нажмите «Создать» или «Изменить».",
    ]
    return "\n".join(lines)


def format_alerts_overview(alerts: list[Alert]) -> str:
    active = sum(1 for a in alerts if a.active)
    paused = len(alerts) - active
    lines = [
        f"<b>📋 Мои подписки</b> ({len(alerts)})",
        "",
        f"🟢 {active} активных · ⚪️ {paused} на паузе",
        "",
        "Выберите подписку для просмотра и управления:",
    ]
    return "\n".join(lines)


def alerts_list_keyboard(alerts: list[Alert]) -> InlineKeyboardMarkup:
    rows = []
    for alert in alerts:
        icon = "🟢" if alert.active else "⚪️"
        rows.append([
            InlineKeyboardButton(
                text=f"{icon} {alert.name}",
                callback_data=f"alert:view:{alert.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="➕ Новая подписка", callback_data="alert:new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def alert_detail_keyboard(alert: Alert) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if alert.active:
        rows.append([
            InlineKeyboardButton(text="⏸ Пауза", callback_data=f"alert:pause:{alert.id}"),
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"alert:edit:{alert.id}"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="▶️ Возобновить", callback_data=f"alert:resume:{alert.id}"),
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"alert:edit:{alert.id}"),
        ])

    rows.append([
        InlineKeyboardButton(text="🔄 Синхронизировать", callback_data=f"alert:resync:{alert.id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"alert:delete:{alert.id}"),
    ])
    rows.append([
        InlineKeyboardButton(text="◀️ К списку", callback_data="alert:list"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def alert_delete_confirm_keyboard(alert_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❌ Да, удалить", callback_data=f"alert:delete_confirm:{alert_id}"),
                InlineKeyboardButton(text="◀️ Отмена", callback_data=f"alert:view:{alert_id}"),
            ]
        ]
    )


def new_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Ссылка с Kufar", callback_data="new:url")],
            [InlineKeyboardButton(text="✏️ Настроить вручную", callback_data="new:manual")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="new:cancel")],
        ]
    )


def confirm_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать подписку", callback_data="new:confirm")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="new:edit")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="new:cancel_confirm")],
        ]
    )


def draft_edit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Название", callback_data="new:edit:name"),
                InlineKeyboardButton(text="🔎 Запрос", callback_data="new:edit:query"),
            ],
            [
                InlineKeyboardButton(text="📂 Категория", callback_data="new:edit:cat"),
                InlineKeyboardButton(text="📍 Место", callback_data="new:edit:loc"),
            ],
            [InlineKeyboardButton(text="💰 Цена", callback_data="new:edit:price")],
            [InlineKeyboardButton(text="🔗 Ссылка Kufar", callback_data="new:edit:url")],
            [InlineKeyboardButton(text="◀️ К предпросмотру", callback_data="new:edit:back")],
        ]
    )


def cancel_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Вернуться к редактированию", callback_data="new:edit:back")],
            [InlineKeyboardButton(text="🗑 Да, отменить", callback_data="new:cancel")],
        ]
    )
