from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import get_settings
from bot.database import Database
from bot.handlers import alerts, start
from bot.kufar import KufarClient
from bot.middleware import InjectMiddleware
from bot.poller import AlertPoller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    db = Database(settings.database_path)

    async with aiohttp.ClientSession() as session:
        kufar = KufarClient(session, search_size=settings.search_size)
        await kufar.get_categories()

        dp.update.middleware(InjectMiddleware(db, kufar))

        dp.include_router(start.router)
        dp.include_router(alerts.router)

        poller = AlertPoller(
            bot=bot,
            db=db,
            kufar=kufar,
            interval=settings.poll_interval,
        )
        poller.start()

        logger.info("Bot started")
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            await poller.stop()
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
