from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.kufar import KufarClient
from bot.locations import AREAS, REGION_ORDER, region_name

AREA_PAGE_SIZE = 8
CAT_COLS = 2


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _short(text: str, max_len: int = 28) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def category_keyboard(kufar: KufarClient, parent_id: int | None = None) -> InlineKeyboardMarkup:
    children = kufar.get_category_children(parent_id)
    rows: list[list[InlineKeyboardButton]] = []

    if parent_id is not None:
        name = kufar.category_name(parent_id)
        rows.append([
            InlineKeyboardButton(text=f"✅ Выбрать «{_short(name, 24)}»", callback_data=f"pick:ca:s:{parent_id}")
        ])

    for row in _chunk(children, CAT_COLS):
        rows.append([
            InlineKeyboardButton(
                text=_short(node["name"]),
                callback_data=f"pick:ca:n:{node['id']}",
            )
            for node in row
        ])

    nav: list[InlineKeyboardButton] = []
    if parent_id is not None:
        parent = kufar.get_category_parent(parent_id)
        back_id = parent if parent is not None else "root"
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"pick:ca:n:{back_id}"))
    nav.append(InlineKeyboardButton(text="⏭ Пропустить", callback_data="pick:ca:sk"))
    rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_title(kufar: KufarClient, parent_id: int | None) -> str:
    if parent_id is None:
        return "📂 Выберите категорию"
    return f"📂 {kufar.category_name(parent_id)}"


def region_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    buttons = [
        InlineKeyboardButton(text=_short(region_name(rid)), callback_data=f"pick:lo:r:{rid}")
        for rid in REGION_ORDER
    ]
    for row in _chunk(buttons, 2):
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🇧🇾 Вся Беларусь", callback_data="pick:lo:sk")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def area_keyboard(region_id: int, page: int = 0) -> InlineKeyboardMarkup:
    areas = list(AREAS.get(region_id, {}).items())
    total_pages = max(1, (len(areas) + AREA_PAGE_SIZE - 1) // AREA_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * AREA_PAGE_SIZE
    chunk = areas[start : start + AREA_PAGE_SIZE]

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"✅ Вся {region_name(region_id)}", callback_data="pick:lo:w")]
    ]

    for row in _chunk(chunk, 2):
        rows.append([
            InlineKeyboardButton(text=_short(name), callback_data=f"pick:lo:a:{area_id}")
            for area_id, name in row
        ])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"pick:lo:p:{region_id}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"pick:lo:p:{region_id}:{page + 1}"))
    nav.append(InlineKeyboardButton(text="◀️ Регионы", callback_data="pick:lo:b"))
    rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def area_title(region_id: int, page: int = 0) -> str:
    region = region_name(region_id)
    if region_id == 7:
        return f"📍 {region} — выберите район"
    areas = AREAS.get(region_id, {})
    total_pages = max(1, (len(areas) + AREA_PAGE_SIZE - 1) // AREA_PAGE_SIZE)
    suffix = f" (стр. {page + 1}/{total_pages})" if total_pages > 1 else ""
    return f"📍 {region} — выберите город{suffix}"
