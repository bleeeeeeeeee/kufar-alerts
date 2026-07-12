from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- НОВАЯ ПЕРЕМЕННАЯ ДЛЯ AIVEN ---
DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or None


@dataclass(frozen=True)
class Settings:
    bot_token: str
    poll_interval: int
    database_path: str  # для SQLite (если используется)
    database_url: str | None  # для PostgreSQL (Aiven)
    search_size: int
    admin_user_ids: tuple[int, ...]
    access_mode: str  # open | invite
    webhook_enabled: bool
    webhook_url: str | None
    webhook_path: str
    webhook_secret_token: str | None

    @property
    def use_postgres(self) -> bool:
        """Проверяет, используем ли мы PostgreSQL."""
        return bool(self.database_url)


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    ids: list[int] = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return tuple(ids)


def _default_database_path() -> str:
    explicit = os.getenv("DATABASE_PATH", "").strip()
    if explicit:
        return explicit

    volume_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if volume_mount:
        return str(Path(volume_mount) / "kufar_alerts.db")

    return "data/kufar_alerts.db"


def get_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and add your token.")

    access_mode = os.getenv("ACCESS_MODE", "invite").strip().lower()
    if access_mode not in ("open", "invite"):
        access_mode = "invite"

    webhook_url = os.getenv("WEBHOOK_URL", "").strip()
    webhook_enabled = os.getenv("WEBHOOK_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if webhook_url:
        webhook_enabled = True

    webhook_path = os.getenv("WEBHOOK_PATH", "/webhook/telegram").strip()
    if not webhook_path.startswith("/"):
        webhook_path = f"/{webhook_path}"

    webhook_secret_token = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip() or None

    # --- ПОЛУЧАЕМ DATABASE_URL ---
    database_url = os.getenv("DATABASE_URL", "").strip() or None

    return Settings(
        bot_token=token,
        poll_interval=max(15, int(os.getenv("POLL_INTERVAL", "45"))),
        database_path=_default_database_path(),
        database_url=database_url,  # <-- НОВОЕ ПОЛЕ
        search_size=min(50, max(10, int(os.getenv("SEARCH_SIZE", "50")))),
        admin_user_ids=_parse_admin_ids(os.getenv("ADMIN_USER_IDS", "")),
        access_mode=access_mode,
        webhook_enabled=webhook_enabled,
        webhook_url=webhook_url or None,
        webhook_path=webhook_path,
        webhook_secret_token=webhook_secret_token,
    )