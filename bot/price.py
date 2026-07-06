from __future__ import annotations

import re

PRICE_MAX = 999_999_999


def format_byn(amount: int | str) -> str:
    return f"{int(amount):,}".replace(",", " ")


def parse_price_input(text: str) -> str | None:
    """
    Parse user-friendly price input into Kufar API prc param.

    Examples:
        1500      → до 1500 BYN
        500-1500  → диапазон
        500+      → от 500 BYN
        -         → убрать фильтр
    """
    raw = (text or "").strip().lower().replace(" ", "").replace("byn", "")
    if raw in ("-", "—", "нет", "пропустить"):
        return None

    if raw.startswith("от"):
        raw = raw[2:].lstrip("+")

    if raw.startswith("до"):
        value = raw[2:]
        if value.isdigit():
            return f"r:0,{value}"
        raise ValueError("Неверный формат. Пример: 1500 или 500-1500")

    if raw.endswith("+"):
        min_price = raw[:-1]
        if min_price.isdigit():
            return f"r:{min_price},{PRICE_MAX}"
        raise ValueError("Неверный формат. Пример: 500+")

    if "-" in raw or "–" in raw:
        parts = re.split(r"[-–]", raw, maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            lo, hi = int(parts[0]), int(parts[1])
            if lo > hi:
                lo, hi = hi, lo
            return f"r:{lo},{hi}"
        raise ValueError("Неверный формат. Пример: 500-1500")

    if raw.isdigit():
        return f"r:0,{raw}"

    raise ValueError(
        "Не понял цену. Примеры:\n"
        "• <code>1500</code> — до 1500 BYN\n"
        "• <code>500-1500</code> — от 500 до 1500\n"
        "• <code>500+</code> — от 500 BYN\n"
        "• <code>-</code> — без фильтра"
    )


def format_price_display(prc: str | None) -> str:
    if not prc:
        return ""
    if not prc.startswith("r:"):
        return prc

    body = prc[2:]
    if "," not in body:
        return prc

    min_s, max_s = body.split(",", 1)
    try:
        min_v, max_v = int(min_s), int(max_s)
    except ValueError:
        return prc

    if min_v == 0:
        return f"до {format_byn(max_v)} BYN"
    if max_v >= PRICE_MAX:
        return f"от {format_byn(min_v)} BYN"
    if min_v == max_v:
        return f"{format_byn(min_v)} BYN"
    return f"{format_byn(min_v)} – {format_byn(max_v)} BYN"


PRICE_INPUT_HINT = (
    "Введите цену в BYN:\n"
    "• <code>1500</code> — до 1500 BYN\n"
    "• <code>500-1500</code> — диапазон\n"
    "• <code>500+</code> — от 500 BYN\n"
    "• <code>-</code> — без фильтра"
)
