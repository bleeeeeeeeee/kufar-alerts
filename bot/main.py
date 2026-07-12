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
from bot.error_handling import ErrorHandlingMiddleware
from bot.handlers import admin, alerts, edit, notifications, pickers, settings as settings_handlers, start
from bot.instance_lock import single_instance_lock
from bot.kufar import KufarClient
from bot.middleware import AccessMiddleware, DedupMiddleware, InjectMiddleware
from bot.menu import setup_bot_menu
from bot.poller import AlertPoller
from bot.web import run_web_in_thread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    # Запускаем веб-сервер для health check (Flask)
    run_web_in_thread()
    
    # Получаем настройки
    app_settings = get_settings()
    
    # --- ВЫБОР БАЗЫ ДАННЫХ: POSTGRESQL ИЛИ SQLITE ---
    if app_settings.database_url:
        # Используем PostgreSQL (Aiven)
        logger.info("Using PostgreSQL database (Aiven)")
        db = Database(app_settings.database_url)
        await db.init(admin_user_ids=app_settings.admin_user_ids)
    else:
        # Используем SQLite (локально или PythonAnywhere)
        logger.info("Using SQLite database")
        Path(app_settings.database_path).parent.mkdir(parents=True, exist_ok=True)
        # Если у вас есть отдельный файл для SQLite, импортируйте его
        from bot.database_sqlite import Database as SQLiteDatabase
        db = SQLiteDatabase(app_settings.database_path)
        await db.init(admin_user_ids=app_settings.admin_user_ids)

    # --- БЛОКИРОВКА ДЛЯ ПРЕДОТВРАЩЕНИЯ ДВОЙНОГО ЗАПУСКА ---
    lock_path = Path(app_settings.database_path).with_suffix(".lock")
    try:
        with single_instance_lock(lock_path):
            # Инициализация бота
            bot = Bot(
                token=app_settings.bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            dp = Dispatcher(storage=MemoryStorage())

            # Сессия для Kufar API
            async with aiohttp.ClientSession() as session:
                kufar = KufarClient(session, search_size=app_settings.search_size)
                try:
                    await kufar.load_category_tree()
                except Exception:
                    logger.exception("Failed to load category tree, continuing without it")

                # --- МИДЛВАРЫ ---
                dp.update.outer_middleware(ErrorHandlingMiddleware())
                dp.update.middleware(DedupMiddleware())
                dp.update.middleware(InjectMiddleware(db, kufar, app_settings))
                dp.update.middleware(AccessMiddleware(db, app_settings))

                # --- МЕНЮ БОТА ---
                await setup_bot_menu(bot)

                # --- ПОДКЛЮЧЕНИЕ РОУТЕРОВ ---
                dp.include_router(start.router)
                dp.include_router(settings_handlers.router)
                dp.include_router(notifications.router)
                dp.include_router(admin.router)
                dp.include_router(alerts.router)
                dp.include_router(edit.router)
                dp.include_router(pickers.router)

                # --- ПОЛЛЕР (ФОНОВАЯ ПРОВЕРКА ОБЪЯВЛЕНИЙ) ---
                poller = AlertPoller(
                    bot=bot,
                    db=db,
                    kufar=kufar,
                    interval=app_settings.poll_interval,
                )
                poller.start()

                # --- ЗАПУСК БОТА ---
                logger.info("Bot started")
                await bot.delete_webhook(drop_pending_updates=True)
                try:
                    await dp.start_polling(
                        bot,
                        allowed_updates=dp.resolve_used_update_types(),
                        drop_pending_updates=True,
                    )
                finally:
                    await poller.stop()
                    await bot.session.close()
    except RuntimeError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    asyncio.run(main())