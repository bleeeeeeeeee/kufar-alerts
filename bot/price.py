from __future__ import annotations

import re

PRICE_MAX = 999_999_999
# Kufar website uses cents; this is the open-max sentinel in cents (÷100 = PRICE_MAX BYN).
WEBSITE_PRICE_MAX_CENTS = 100_000_000_000


def format_byn(amount: int | str) -> str:
    return f"{int(amount):,}".replace(",", " ")


def format_listing_price_byn(price_byn: int | str | None) -> str:
    """Format listing price from Kufar API (stored in kopecks)."""
    if price_byn in (None, "", "0"):
        return "Договорная"
    try:
        cents = int(price_byn)
    except (TypeError, ValueError):
        return f"{price_byn} BYN"
    if cents <= 0:
        return "Договорная"
    whole = cents // 100
    remainder = cents % 100
    if remainder:
        return f"{format_byn(whole)},{remainder:02d} BYN"
    return f"{format_byn(whole)} BYN"


def parse_prc(prc: str | None) -> tuple[int | None, int | None]:
    """Parse prc into (min_byn, max_byn). None means unbounded."""
    if not prc or not prc.startswith("r:"):
        return None, None

    body = prc[2:]
    if "," not in body:
        return None, None

    min_s, max_s = body.split(",", 1)
    min_v = int(min_s) if min_s.strip() else None
    max_v = int(max_s) if max_s.strip() else None

    if min_v == 0:
        min_v = None
    if max_v is not None and max_v >= PRICE_MAX:
        max_v = None

    return min_v, max_v


def build_prc(min_v: int | None, max_v: int | None) -> str | None:
    if min_v is None and max_v is None:
        return None
    min_s = str(min_v) if min_v is not None else ""
    max_s = str(max_v) if max_v is not None else ""
    return f"r:{min_s},{max_s}"


def normalize_prc(prc: str | None) -> str | None:
    """Canonical internal prc in BYN with open bounds."""
    if not prc:
        return None
    if not prc.startswith("r:"):
        return prc

    body = prc[2:]
    if "," not in body:
        return prc

    min_s, max_s = body.split(",", 1)
    min_raw = int(min_s) if min_s.strip() else None
    max_raw = int(max_s) if max_s.strip() else None

    if max_raw in (WEBSITE_PRICE_MAX_CENTS, PRICE_MAX * 100):
        return prc_from_website(prc)
    if min_raw is not None and min_raw >= 50_000:
        return prc_from_website(prc)
    if max_raw is not None and max_raw >= 50_000 and min_raw is None:
        return prc_from_website(prc)

    return build_prc(*parse_prc(prc))


def prc_for_api(prc: str | None) -> str | None:
    min_v, max_v = parse_prc(normalize_prc(prc))
    if min_v is None and max_v is None:
        return None
    return f"r:{min_v or 0},{max_v if max_v is not None else PRICE_MAX}"


def prc_for_website(prc: str | None) -> str | None:
    min_v, max_v = parse_prc(normalize_prc(prc))
    if min_v is None and max_v is None:
        return None
    # Kufar website breaks on open bounds (r:150000,) and adds a fake max on submit.
    # Only include price when both bounds are set; alerts still use API prc_for_api().
    if min_v is None or max_v is None:
        return None
    return f"r:{min_v * 100},{max_v * 100}"


def prc_from_website(prc: str) -> str:
    """Convert website prc (cents, open bounds) to internal BYN format."""
    if not prc or not prc.startswith("r:"):
        return prc

    body = prc[2:]
    if "," not in body:
        return prc

    min_s, max_s = body.split(",", 1)
    min_v = int(min_s) // 100 if min_s.strip() else None
    max_v = int(max_s) // 100 if max_s.strip() else None
    if min_v == 0:
        min_v = None
    if max_v is not None and max_v >= PRICE_MAX:
        max_v = None
    return build_prc(min_v, max_v) or prc


def parse_price_input(text: str) -> str | None:
    """
    Parse user-friendly price input into internal prc param (BYN, open bounds).

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
            return build_prc(None, int(value))
        raise ValueError("Неверный формат. Пример: 1500 или 500-1500")

    if raw.endswith("+"):
        min_price = raw[:-1]
        if min_price.isdigit():
            return build_prc(int(min_price), None)
        raise ValueError("Неверный формат. Пример: 500+")

    if "-" in raw or "–" in raw:
        parts = re.split(r"[-–]", raw, maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            lo, hi = int(parts[0]), int(parts[1])
            if lo > hi:
                lo, hi = hi, lo
            return build_prc(lo, hi)
        raise ValueError("Неверный формат. Пример: 500-1500")

    if raw.isdigit():
        return build_prc(None, int(raw))

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

    min_v, max_v = parse_prc(normalize_prc(prc))
    if min_v is None and max_v is None:
        if prc.startswith("r:"):
            return prc
        return ""

    if min_v is None:
        return f"до {format_byn(max_v)} BYN"
    if max_v is None:
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
