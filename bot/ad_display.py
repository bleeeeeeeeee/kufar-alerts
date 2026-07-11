from __future__ import annotations

import ast
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


def format_param_value(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):
        parts = [format_param_value(item) for item in raw]
        return ", ".join(part for part in parts if part)
    if isinstance(raw, dict):
        parts = [str(value).strip() for value in raw.values() if value not in (None, "")]
        return ", ".join(part for part in parts if part)
    text = str(raw).strip()
    if not text:
        return ""
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return ", ".join(format_param_value(item) for item in parsed if item not in (None, ""))
        except (SyntaxError, ValueError):
            inner = text[1:-1].strip()
            if inner:
                parts = [part.strip().strip("'\"") for part in inner.split(",")]
                return ", ".join(part for part in parts if part)
    return text


def get_param_value(ad: dict[str, Any], param_name: str) -> str:
    for param in ad.get("ad_parameters") or []:
        if param.get("p") == param_name:
            return format_param_value(param.get("vl"))
    return ""


def format_price(ad: dict[str, Any]) -> str:
    return format_listing_price_byn(ad.get("price_byn"))


def format_ad_location(ad: dict[str, Any]) -> str:
    region = get_param_value(ad, "region")
    area = get_param_value(ad, "area")
    if region and area:
        return f"{region}, {area}"
    return region or area or ""


def format_posted_at(ad: dict[str, Any], *, compact: bool = False) -> str:
    dt = parse_iso_time(ad.get("list_time"))
    if dt is None:
        return ""
    local = dt.astimezone(BY_OFFSET)
    date_part = local.strftime("%d.%m") if compact else local.strftime("%d.%m.%Y")
    time_part = local.strftime("%H:%M")
    # Разделитель даты и времени: сейчас « · ». Чтобы убрать — замените на пробел
    # или склейте в одну строку: return f"{date_part} {time_part}"
    return f"{date_part} · {time_part}"


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
        value = format_param_value(param.get("vl"))
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

