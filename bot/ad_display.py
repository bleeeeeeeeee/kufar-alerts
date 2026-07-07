from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any

from bot.price import format_listing_price_byn
from bot.time_utils import parse_iso_time
from bot.users import NotificationDisplay

BY_OFFSET = timezone(timedelta(hours=3))

DETAIL_PARAM_PRIORITY = (
    "phones_brand",
    "phablet_phones_model",
    "phablet_phones_memory",
    "phablet_phones_ram",
    "phablet_phones_os",
    "phablet_phones_sim",
    "regdate",
    "mileage",
    "cars_engine",
    "cars_capacity",
    "cars_gearbox",
    "cars_type",
    "cars_color",
    "rooms",
    "size",
    "sls",
    "floor",
    "re_number_floors",
    "flat_repair",
    "bathroom",
    "balcony",
    "metro",
    "computers_laptop_brand",
    "computers_laptop_processor",
    "computers_laptop_ram",
    "computers_laptop_ssd",
    "computers_laptop_gpu",
    "jobs_profession",
    "jobs_experience",
    "jobs_type",
)

SKIP_DETAIL_PARAMS = frozenset(
    {
        "region",
        "area",
        "category",
        "condition",
        "delivery_enabled",
        "type",
        "remuneration_type",
    }
)

MAX_DETAIL_LINES = 8


def get_param_value(ad: dict[str, Any], param_name: str) -> str:
    for param in ad.get("ad_parameters") or []:
        if param.get("p") == param_name:
            return str(param.get("vl") or "")
    return ""


def format_price(ad: dict[str, Any]) -> str:
    return format_listing_price_byn(ad.get("price_byn"))


def format_ad_location(ad: dict[str, Any]) -> str:
    region = get_param_value(ad, "region")
    area = get_param_value(ad, "area")
    if region and area:
        return f"{region}, {area}"
    return region or area or ""


def format_posted_at(ad: dict[str, Any]) -> str:
    dt = parse_iso_time(ad.get("list_time"))
    if dt is None:
        return ""
    local = dt.astimezone(BY_OFFSET)
    return local.strftime("%d.%m.%Y %H:%M")


def format_seller(ad: dict[str, Any]) -> str:
    if ad.get("company_ad"):
        return "Магазин"
    return "Частник"


def _collect_detail_lines(ad: dict[str, Any]) -> list[str]:
    params = ad.get("ad_parameters") or []
    by_name = {p.get("p"): p for p in params if p.get("p")}

    lines: list[str] = []
    seen: set[str] = set()

    def add_param(name: str) -> None:
        if name in seen or name in SKIP_DETAIL_PARAMS:
            return
        param = by_name.get(name)
        if not param:
            return
        label = str(param.get("pl") or "").strip()
        value = str(param.get("vl") or "").strip()
        if not value:
            return
        seen.add(name)
        if label:
            lines.append(f"• {label}: {value}")
        else:
            lines.append(f"• {value}")

    for name in DETAIL_PARAM_PRIORITY:
        add_param(name)
        if len(lines) >= MAX_DETAIL_LINES:
            return lines

    remaining = sorted(
        (
            p
            for p in params
            if p.get("p") not in seen
            and p.get("p") not in SKIP_DETAIL_PARAMS
            and p.get("vl")
        ),
        key=lambda p: str(p.get("pl") or p.get("p") or ""),
    )
    for param in remaining:
        add_param(str(param.get("p")))
        if len(lines) >= MAX_DETAIL_LINES:
            break

    return lines


def format_ad_message(
    ad: dict[str, Any],
    *,
    display: NotificationDisplay | None = None,
) -> str:
    prefs = display or NotificationDisplay()
    subject = html.escape(ad.get("subject") or "Без названия")
    link = ad.get("ad_link") or f"https://www.kufar.by/item/{ad.get('ad_id')}"

    lines = [f"<b>{subject}</b>"]

    if prefs.price:
        lines.append(f"💰 {html.escape(format_price(ad))}")

    if prefs.location:
        location = format_ad_location(ad)
        if location:
            lines.append(f"📍 {html.escape(location)}")

    if prefs.category:
        category = get_param_value(ad, "category")
        if category:
            lines.append(f"📂 {html.escape(category)}")

    if prefs.condition:
        condition = get_param_value(ad, "condition")
        if condition:
            lines.append(f"✨ {html.escape(condition)}")

    if prefs.delivery:
        delivery = get_param_value(ad, "delivery_enabled")
        if delivery:
            lines.append(f"📦 Доставка: {html.escape(delivery)}")

    if prefs.seller:
        lines.append(f"👤 {html.escape(format_seller(ad))}")

    if prefs.posted_at:
        posted = format_posted_at(ad)
        if posted:
            lines.append(f"🕐 {html.escape(posted)}")

    if prefs.details:
        details = _collect_detail_lines(ad)
        if details:
            lines.append("📋 " + html.escape(details[0]))
            for detail in details[1:]:
                lines.append(html.escape(detail))

    lines.append(f'🔗 <a href="{link}">Открыть на Kufar</a>')
    return "\n".join(lines)
