from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    poll_interval: int
    database_path: str
    search_size: int


def get_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and add your token.")

    return Settings(
        bot_token=token,
        poll_interval=max(15, int(os.getenv("POLL_INTERVAL", "45"))),
        database_path=os.getenv("DATABASE_PATH", "data/kufar_alerts.db"),
        search_size=min(50, max(5, int(os.getenv("SEARCH_SIZE", "30")))),
    )
