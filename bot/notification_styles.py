from __future__ import annotations

import html
from typing import Any

from bot.ad_display import (
    _collect_detail_lines,
    format_ad_location,
    format_posted_at,
    format_price,
    format_seller,
    get_param_value,
)
from bot.users import NotificationDisplay

NOTIFICATION_STYLES: dict[str, dict[str, str]] = {
    "minimal": {
        "label": "Минимализм",
        "hint": "Без значков у полей, заголовок — ссылка на объявление.",
    },
    "classic": {
        "label": "Классика",
        "hint": "Значки у полей и отдельная ссылка «Открыть на Kufar».",
    },
}

NOTIFICATION_LAYOUTS: dict[str, dict[str, str]] = {
    "row": {
        "label": "В строку",
        "hint": "Цена, место и остальные поля в одной строке через ·",
    },
    "column": {
        "label": "Столбцом",
        "hint": "Каждое поле с новой строки — удобнее читать длинные списки.",
    },
}

DEFAULT_NOTIFICATION_STYLE = "minimal"
DEFAULT_NOTIFICATION_LAYOUT = "row"


def normalize_notification_style(value: str | None) -> str:
    if value in NOTIFICATION_STYLES:
        return value
    return DEFAULT_NOTIFICATION_STYLE


def normalize_notification_layout(value: str | None) -> str:
    if value in NOTIFICATION_LAYOUTS:
        return value
    return DEFAULT_NOTIFICATION_LAYOUT


def notification_style_label(style: str) -> str:
    return NOTIFICATION_STYLES[normalize_notification_style(style)]["label"]


def notification_layout_label(layout: str) -> str:
    return NOTIFICATION_LAYOUTS[normalize_notification_layout(layout)]["label"]


def format_notification_message(
    ad: dict[str, Any],
    *,
    subscription_name: str,
    display: NotificationDisplay | None = None,
    style: str | None = None,
    layout: str | None = None,
) -> str:
    resolved_style = normalize_notification_style(style)
    resolved_layout = normalize_notification_layout(layout)
    prefs = display or NotificationDisplay()
    body = (
        _format_ad_classic(ad, display=prefs, layout=resolved_layout)
        if resolved_style == "classic"
        else _format_ad_minimal(ad, display=prefs, layout=resolved_layout)
    )
    return _wrap_notification(subscription_name, body, resolved_style)


def _wrap_notification(subscription_name: str, body: str, style: str) -> str:
    name = html.escape(subscription_name)
    # Первая строка — название подписки. Сейчас без курсива (просто текст).
    # Чтобы вернуть курсив: f"<i>{name}</i>\n\n{body}" (и то же для classic после 📌).
    # Другие варианты: <b>{name}</b> — жирный, <code>{name}</code> — моноширинный.
    if style == "classic":
        return f"🆕 <b>Новое объявление</b>\n📌 {name}\n\n{body}"
    return f"{name}\n\n{body}"


def _ad_link(ad: dict[str, Any]) -> str:
    return ad.get("ad_link") or f"https://www.kufar.by/item/{ad.get('ad_id')}"


def _append_group(lines: list[str], parts: list[str], layout: str) -> None:
    if not parts:
        return
    if layout == "row":
        lines.append(" · ".join(parts))
    else:
        lines.extend(parts)


def _format_ad_minimal(ad: dict[str, Any], *, display: NotificationDisplay, layout: str) -> str:
    subject = html.escape(ad.get("subject") or "Без названия")
    link = _ad_link(ad)
    lines: list[str] = [f'<b><a href="{link}">{subject}</a></b>']

    meta: list[str] = []
    if display.price:
        price = format_price(ad)
        if price:
            meta.append(f"<b>{html.escape(price)}</b>")

    if display.location:
        location = format_ad_location(ad)
        if location:
            meta.append(html.escape(location))

    if display.category:
        category = get_param_value(ad, "category")
        if category:
            meta.append(html.escape(category))

    if display.condition:
        condition = get_param_value(ad, "condition")
        if condition:
            meta.append(html.escape(condition))

    if display.seller:
        meta.append(html.escape(format_seller(ad)))

    if display.posted_at:
        posted = format_posted_at(ad, compact=True)
        if posted:
            meta.append(html.escape(posted))

    if display.delivery:
        delivery = get_param_value(ad, "delivery_enabled")
        if delivery:
            meta.append(f"доставка: {html.escape(delivery)}")

    _append_group(lines, meta, layout)

    if display.details:
        details = _collect_detail_lines(ad)
        if details:
            detail_parts = [html.escape(detail.lstrip("• ").strip()) for detail in details]
            _append_group(lines, detail_parts, layout)

    return "\n".join(lines)


def _format_ad_classic(ad: dict[str, Any], *, display: NotificationDisplay, layout: str) -> str:
    subject = html.escape(ad.get("subject") or "Без названия")
    link = _ad_link(ad)
    lines = [f"<b>{subject}</b>"]

    parts: list[str] = []
    if display.price:
        parts.append(f"💰 {html.escape(format_price(ad))}")

    if display.location:
        location = format_ad_location(ad)
        if location:
            parts.append(f"📍 {html.escape(location)}")

    if display.category:
        category = get_param_value(ad, "category")
        if category:
            parts.append(f"📂 {html.escape(category)}")

    if display.condition:
        condition = get_param_value(ad, "condition")
        if condition:
            parts.append(f"✨ {html.escape(condition)}")

    if display.delivery:
        delivery = get_param_value(ad, "delivery_enabled")
        if delivery:
            parts.append(f"📦 Доставка: {html.escape(delivery)}")

    if display.seller:
        parts.append(f"👤 {html.escape(format_seller(ad))}")

    if display.posted_at:
        posted = format_posted_at(ad)
        if posted:
            parts.append(f"🕐 {html.escape(posted)}")

    _append_group(lines, parts, layout)

    if display.details:
        details = _collect_detail_lines(ad)
        if details:
            if layout == "row":
                detail_parts = [html.escape(detail.lstrip("• ").strip()) for detail in details]
                lines.append("📋 " + " · ".join(detail_parts))
            else:
                lines.append("📋 " + html.escape(details[0].lstrip("• ")))
                for detail in details[1:]:
                    lines.append(html.escape(detail))

    lines.append(f'🔗 <a href="{link}">Открыть на Kufar</a>')
    return "\n".join(lines)
