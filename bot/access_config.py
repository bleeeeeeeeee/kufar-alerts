from __future__ import annotations

ACCESS_MODE_OPEN = "open"
ACCESS_MODE_INVITE = "invite"
ACCESS_MODE_KEY = "access_mode"


def normalize_access_mode(value: str | None, *, default: str = ACCESS_MODE_INVITE) -> str:
    mode = (value or default).strip().lower()
    if mode not in (ACCESS_MODE_OPEN, ACCESS_MODE_INVITE):
        return default
    return mode


def access_mode_label(mode: str) -> str:
    return "открытый" if mode == ACCESS_MODE_OPEN else "по приглашению"


def access_mode_description(mode: str) -> str:
    if mode == ACCESS_MODE_OPEN:
        return "любой может начать пользоваться ботом"
    return "только пользователи, добавленные администратором"
