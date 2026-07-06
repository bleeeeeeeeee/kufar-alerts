from __future__ import annotations

CATEGORY_NAMES: dict[int, str] = {}


def set_category_names(names: dict[int, str]) -> None:
    global CATEGORY_NAMES
    CATEGORY_NAMES = names


def category_name(cat_id: int | str | None) -> str:
    if cat_id is None:
        return ""
    try:
        return CATEGORY_NAMES.get(int(cat_id), str(cat_id))
    except (TypeError, ValueError):
        return str(cat_id)
