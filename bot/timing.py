from __future__ import annotations

POLL_INTERVAL_OPTIONS: tuple[int, ...] = (15, 30, 45, 60, 90, 120, 180, 300)
NOTIFY_COOLDOWN_OPTIONS: tuple[int, ...] = (0, 30, 60, 300, 900)


def format_poll_interval(seconds: int | None, *, default: int) -> str:
    value = seconds if seconds is not None else default
    if seconds is None:
        return f"по умолчанию (~{default} сек)"
    return f"каждые {value} сек"


def format_notify_cooldown(seconds: int) -> str:
    if seconds <= 0:
        return "без паузы"
    if seconds < 60:
        return f"{seconds} сек"
    if seconds % 60 == 0:
        minutes = seconds // 60
        if minutes == 1:
            return "1 мин"
        return f"{minutes} мин"
    return f"{seconds} сек"


def poll_interval_label(seconds: int | None, *, default: int) -> str:
    if seconds is None:
        return f"По умолчанию (~{default} сек)"
    return f"Каждые {seconds} сек"


def notify_cooldown_label(seconds: int) -> str:
    mapping = {
        0: "Без паузы",
        30: "30 секунд",
        60: "1 минута",
        300: "5 минут",
        900: "15 минут",
    }
    return mapping.get(seconds, format_notify_cooldown(seconds))
